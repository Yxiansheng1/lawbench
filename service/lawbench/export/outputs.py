"""确认保存（/api/outputs/confirm）与生成修订版（/api/redline）（Spec 12.1、12.2、20.8；F-OUT-03）。

- 确认：草稿只在 工作区/任务/<任务>/草稿/；律师确认后导出到 成果/<标题>-v<N>.<md|docx>，N 按本案 成果/ 里同标题
  已有的最大版本加 1（md、docx 同一次确认用同一个 N），旧版本不覆盖；再在 成果/索引.json 追加一条。
  标题取草稿文件名去掉 -v<N> 和扩展名：草稿保存时已过闸门（非法字符、设备名、过长都写不进去），所以标题本身
  就是合法文件名；写 成果/ 时再过一次闸门。
- 修订版：读修改清单和合同原件（只读），在内存里生成，存为该任务的草稿 草稿/<合同材料名>-修订版-v<N>.docx。
- 只读草稿、修改清单、材料文本和原件；写只经闸门落在 工作区/、成果/。日志只记元数据（不记标题、修改内容）。
"""
from __future__ import annotations

import contextlib
import json
import re
import threading
import zipfile

from lxml import etree

from .. import checks, contracts, logs
from ..case import gate
from ..case.task import OUTPUTS_REL, now_iso, sha256_file
from ..errors import ApiError
from ..ingest import ParseError
from . import pandoc, redline

OUTPUT_DIR = "成果"
_DRAFT = re.compile(r"^(?P<title>.+)-v(?P<n>\d+)\.(?P<ext>md|docx)$")
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _case_lock(case_id: str) -> threading.Lock:
    """成果/ 和 成果/索引.json 的读-改-写：同一案件一次一个确认。"""
    with _guard:
        return _locks.setdefault(case_id, threading.Lock())


def read_index(root: str) -> dict:
    p = gate.resolve_internal(root, OUTPUTS_REL, op="outputs_index")
    if not p.is_file():
        return {"v": 1, "outputs": []}
    data = contracts.read_json(p)
    contracts.validate("files/outputs_index.schema.json", "", data)
    return data


@contextlib.contextmanager
def index_update(root: str, case_id: str):
    """成果/索引.json 唯一的写入途径（确认保存、案卷归档共用）：持本案锁读出索引交给调用方，调用方往
    outputs 里追加；块正常结束时按契约校验后原子写回，块里出错则不写。调用方在块里写的成果文件，出错时自己清。"""
    with _case_lock(case_id):
        index = read_index(root)
        yield index
        contracts.validate("files/outputs_index.schema.json", "", index)
        gate.write_bytes(root, OUTPUTS_REL, json.dumps(index, ensure_ascii=False, indent=2).encode("utf-8"),
                         op="outputs_index")


def remove_outputs(root: str, paths: list[str]) -> None:
    """索引没写成时，刚写的成果文件也不留，免得成果区和索引对不上。"""
    for p in paths:
        try:
            gate.resolve_write(root, p, op="outputs_rollback").unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001
            logs.event("export", "rollback", status="fail", error=type(e).__name__)


def result_passed(tasks, root: str, task_id: str) -> bool:
    """没有出处可核的成果（修订版、归档文件）：取本任务 result.json 的核对结果（合同审查的意见稿、归档核对表
    在同一任务里），没有算 false。"""
    try:
        res = tasks.result(root, task_id)
    except Exception:  # noqa: BLE001 result.json 不在或不合契约
        return False
    chk = res.get("citation_check")
    return bool(chk and chk.get("passed"))


class Exporter:
    def __init__(self, cases, tasks, materials, settings, skills_dirs=(), pandoc_exe: str | None = None):
        self.cases = cases
        self.tasks = tasks
        self.materials = materials
        self.settings = settings
        self.skills_dirs = tuple(skills_dirs)
        self.pandoc_exe = pandoc_exe

    def _task(self, case_id: str, task_id: str) -> tuple[str, dict]:
        cid, root, task = self.tasks.locate(task_id)
        if cid != case_id:
            raise ApiError("TASK_NOT_FOUND", "other_case")
        return root, task

    # ================================================================ 确认保存

    def confirm(self, d: dict) -> dict:
        root, task = self._task(d["case_id"], d["task_id"])
        rel = d["draft"]
        parts = rel.split("/")
        m = _DRAFT.match(parts[-1]) if parts else None
        if len(parts) != 5 or parts[:3] != ["工作区", "任务", d["task_id"]] or parts[3] != "草稿" or not m:
            raise ApiError("INVALID_ARGUMENT", "not_a_draft")
        src = gate.resolve_internal(root, rel, op="outputs_confirm")
        if not src.is_file():
            raise ApiError("INVALID_ARGUMENT", "draft_missing")
        title, ext = m.group("title"), m.group("ext")
        formats = sorted(set(d["formats"]), key=("md", "docx").index)
        if ext == "docx" and formats != ["docx"]:           # 修订版等 Word 草稿：只能按原样确认为 docx
            raise ApiError("INVALID_ARGUMENT", "docx_draft_only_docx")

        payload: dict[str, bytes] = {}
        if ext == "md":
            text = src.read_text(encoding="utf-8")
            clean = pandoc.strip_workspace_links(text)
            if "md" in formats:
                payload["md"] = clean.encode("utf-8")
            if "docx" in formats:
                ref = pandoc.template_path(d["template"] or "文书", self.settings.get())
                payload["docx"] = pandoc.to_docx(clean, ref, self.pandoc_exe)
            passed = self._citation_passed(root, d["case_id"], task, text)
        else:
            payload["docx"] = src.read_bytes()
            passed = self._result_passed(root, d["task_id"])

        written: list[str] = []
        try:
            with index_update(root, d["case_id"]) as index:
                version = self._next_version(root, index, title)
                for fmt in formats:
                    out = f"{OUTPUT_DIR}/{title}-v{version}.{fmt}"
                    gate.write_bytes(root, out, payload[fmt], op="outputs_confirm")
                    written.append(out)
                index["outputs"].append({
                    "title": title, "version": version,
                    "files": [{"format": f, "path": p} for f, p in zip(formats, written)],
                    "task_id": d["task_id"], "inputs": task["inputs"], "citation_passed": passed,
                    "confirmed_at": now_iso()})
        except Exception:
            remove_outputs(root, written)
            raise
        logs.event("export", "confirm", case_id=d["case_id"])
        return {"outputs": [{"format": f, "path": p, "version": version} for f, p in zip(formats, written)]}

    @staticmethod
    def _next_version(root: str, index: dict, title: str) -> int:
        """同标题（不分大小写：NTFS 上 A-v1 与 a-v1 是同一个文件）已有的最大版本 + 1；成果/ 里的文件和索引都算。"""
        key = title.casefold()
        pat = re.compile(re.escape(key) + r"-v(\d+)\.(md|docx)$")
        folder = gate.resolve_internal(root, OUTPUT_DIR, op="outputs_confirm")
        found = [int(m.group(1)) for p in (folder.iterdir() if folder.is_dir() else [])
                 if (m := pat.match(p.name.casefold()))]
        found += [o["version"] for o in index["outputs"] if o["title"].casefold() == key]
        return max(found, default=0) + 1

    def _citation_passed(self, root: str, case_id: str, task: dict, text: str) -> bool:
        """对确认的这一版草稿重新核一次出处（result.json 里的是本任务最后一次保存的结果，不一定是这一版）。"""
        kind = checks.skill_kind(self.skills_dirs, task.get("skill"))
        check, _cites = checks.check_text(text, checks.MaterialSet.from_case(root, self.materials.index(case_id)),
                                          kind)
        return bool(check["passed"])

    def _result_passed(self, root: str, task_id: str) -> bool:
        return result_passed(self.tasks, root, task_id)

    # ================================================================ 修订版

    def redline(self, d: dict) -> dict:
        root, task = self._task(d["case_id"], d["task_id"])
        rel = d["edit_list"]
        parts = rel.split("/")
        if len(parts) != 5 or parts[:3] != ["工作区", "任务", d["task_id"]] or parts[3] != "修改清单" \
                or not parts[4].endswith(".json"):
            raise ApiError("INVALID_ARGUMENT", "not_an_edit_list")
        p = gate.resolve_internal(root, rel, op="redline")
        if not p.is_file():
            raise ApiError("INVALID_ARGUMENT", "edit_list_missing")
        try:
            edits = contracts.read_json(p)
        except Exception:  # noqa: BLE001
            raise ApiError("INVALID_ARGUMENT", "edit_list_unreadable")
        if contracts.errors("tools/case_save_edit_list.schema.json", "#/$defs/args", edits):
            raise ApiError("INVALID_ARGUMENT", "edit_list_contract")
        m = next((x for x in self.materials.index(d["case_id"])["materials"] if x["name"] == edits["name"]), None)
        if m is None:
            raise ApiError("MATERIAL_NOT_FOUND", "unknown_material")
        if m["type"] != "docx":
            raise ApiError("INVALID_ARGUMENT", "not_docx")
        src = gate.resolve_read(root, m["rel_path"], op="redline")
        if not src.is_file() or sha256_file(src) != m["sha256"]:   # 原件在保存修改清单之后改过：段号可能对不上
            raise ApiError("INPUT_CHANGED", "original_changed")
        ids = [e["id"] for e in edits["edits"]]
        if len(ids) != len(set(ids)):
            raise ApiError("INVALID_ARGUMENT", "duplicate_edit_id")
        try:
            data, applied, manual = redline.generate(src.read_bytes(), edits["edits"])
        except redline.Revised:
            # 契约 1.4 加专用码 ORIGINAL_HAS_REVISIONS（主编排 2259 定）；1.4 之前过渡用 INVALID_ARGUMENT
            raise ApiError("INVALID_ARGUMENT", "original_has_revisions")
        except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError, ParseError):
            raise ApiError("MATERIAL_NOT_READY", "docx_unreadable")

        title = m["name"].replace("/", "_").replace("\\", "_") + "-修订版"
        tid = d["task_id"]
        drafts_rel = self.tasks.rel(tid, "草稿")
        with self.tasks.task_lock(tid):
            folder = gate.resolve_internal(root, drafts_rel, op="redline")
            pat = re.compile(re.escape(title.casefold()) + r"-v(\d+)\.docx$")
            version = max([int(x.group(1)) for f in (folder.iterdir() if folder.is_dir() else [])
                           if (x := pat.match(f.name.casefold()))], default=0) + 1
            out = f"{drafts_rel}/{title}-v{version}.docx"
            gate.write_bytes(root, out, data, op="redline")
            self._add_draft(root, tid, title, out, version)
        logs.event("export", "redline", case_id=d["case_id"])
        return {"path": out, "applied": len(applied), "manual": manual}

    def _add_draft(self, root: str, task_id: str, title: str, path: str, version: int) -> None:
        """登记到 result.json 的草稿列表（界面成果区从这里列）；还没有 result.json 的任务不登记。"""
        if not gate.resolve_internal(root, self.tasks.rel(task_id, "result.json"), op="redline").is_file():
            return
        res = self.tasks.result(root, task_id)
        res["drafts"].append({"title": title, "path": path, "version": version})
        self.tasks.save_result(root, res)
