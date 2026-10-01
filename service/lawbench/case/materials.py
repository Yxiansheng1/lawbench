"""材料：扫描原件区、解析、材料索引、导入（Spec 4.1、5.1–5.3、20.2；契约 files/material_index、
api/materials_scan、api/materials_list、api/materials_import）。

- 原件区 = 案件根目录下除 工作区/、成果/ 和以 . 开头的项以外的全部内容；不跟随链接和 junction；
  Office 锁文件（~$…）和不支持的格式不进材料清单。
- 新增、变化、删除：按大小和修改时间缓存哈希，变了才重算；变化的重新解析（已有识别结果据 case.db 判为过期）；
  删除的标 source_deleted，保留文本。
- 材料编号 M + 4 位序号，同一案件内不复用；改名或移动视为删除后新增。
- 材料名三级唯一规则（Spec 20.2）；新材料导致重名时，已有材料的名字也改长，并更新其材料文本的标题。
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import sqlite3
import stat
import threading
import time
import uuid
import zipfile
from datetime import datetime

from .. import contracts, logs
from ..errors import ApiError
from ..ingest import MAX_BYTES, REASONS, RETRY_MESSAGES, Parsed, ParseError
from ..ingest import detect, docx, image, links, pdf, text, xlsx
from ..ingest.libreoffice import Converter, remove_tree
from ..search import fts as search_fts
from . import gate
from .registry import TEMPLATES, CaseRegistry

INDEX_REL = "工作区/材料/index.json"
TEXT_DIR = "工作区/材料/文本"
FORMULA_DIR = "工作区/材料/公式"
STATUS_REL = "工作区/材料/_处理状态.md"
TEMP_REL = "工作区/临时"
INDEX_SCHEMA = "files/material_index.schema.json"
SOURCE_KIND = {"none": "文字版", "partial": "部分识别", "full": "识别所得"}
CONVERTED_NOTE = {"doc": "由 doc 转换", "wps": "由 wps 转换", "xls": "由 xls 转换"}
SHORTCUT_EXT = {".lnk", ".url"}
ZIP_MAX_FILES = 500
# 材料文本的格式版本（X13）：写在 _处理状态.md 里（那个文件"无固定格式"，不加契约字段）。版本变了，下次扫描时
# 这几种材料原件没变也重新解析：2 = Excel 按显示值写（N27）、整份待识别的 Source 行写"待识别"（N28）
TEXT_FORMAT_VERSION = 2
REFORMAT_TYPES = ("xlsx", "xls", "pdf", "image")
_FORMAT_LINE = re.compile(r"^材料文本格式版本：(\d+)\s*$", re.M)
EXTERNAL_NOTE = "有外部链接，未重算公式"  # 契约 1.2 N21
# 本服务在 工作区/临时/ 下自己建的项的前缀（X6 按前缀清残留）
TEMP_PREFIXES = ("lo-", "unzip-", gate.IMPORT_TMP_PREFIX)
# 只认本服务自己建的形状（T5 第二轮）：lo-/unzip- 加 8 位十六进制的目录、imp- 加 8 位十六进制的文件；
# 律师自己放的 lo-截图.png、imp-合同.pdf 不动
_OWN_TEMP_DIR = re.compile(r"^(lo|unzip)-[0-9a-f]{8}$")
_OWN_TEMP_FILE = re.compile(r"^imp-[0-9a-f]{8}$")
ZERO_SHA = "0" * 64
STANDARD_TOPS = {rel for t in TEMPLATES.values() for rel in t if "/" not in rel}
_FILE_ATTRIBUTE_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def mtime_iso(st: os.stat_result) -> str:
    return datetime.fromtimestamp(st.st_mtime).astimezone().isoformat(timespec="microseconds")


def sha256_file(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_link_entry(st: os.stat_result) -> bool:
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _key(rel: str) -> str:
    return os.path.normcase(rel)


# ---------- 材料名（Spec 20.2） ----------

def _clean(name: str) -> str:
    return name.replace(" ", "_").replace("、", "_")


def assign_names(rels: list[str]) -> dict[str, str]:
    """① 文件名去扩展名；② 重复时用去扩展名的相对路径；③ 仍重复时用带扩展名的相对路径。

    ③ 之后仍重名（空格、顿号换成下划线后撞上等）按主编排的临时裁决（T5 返修 X10，候 owner N25）：排在前面的名字不变，
    后来者在末尾加 _2、_3……直到不重名。rels 的顺序就是先后：index.json 里已有的材料按原顺序在前，
    同一次扫描新增的按原件相对路径排序接在后面。比较不分大小写。"""
    def stem_path(r: str) -> str:
        p = pathlib.PurePosixPath(r)
        return str(p.with_suffix("")) if p.suffix else r

    levels = [lambda r: pathlib.PurePosixPath(stem_path(r)).name, stem_path, lambda r: r]
    names: dict[str, str] = {}
    pending = list(rels)
    for i, level in enumerate(levels):
        cand = {r: _clean(level(r)) for r in pending}
        counts: dict[str, int] = {}
        for n in cand.values():
            counts[n.casefold()] = counts.get(n.casefold(), 0) + 1
        taken = {n.casefold() for n in names.values()}
        nxt = []
        last = i == len(levels) - 1
        for r, n in cand.items():
            if last:
                base, k = n, 2
                while n.casefold() in taken:
                    n = f"{base}_{k}"
                    k += 1
                names[r] = n
                taken.add(n.casefold())
            elif counts[n.casefold()] == 1 and n.casefold() not in taken:
                names[r] = n
            else:
                nxt.append(r)
        pending = nxt
        if not pending:
            break
    return names


# ---------- 渲染材料文本（formats.md 第 2 节） ----------

def render(name: str, entry: dict, parsed: Parsed) -> str:
    kind = SOURCE_KIND[entry["is_ocr"]]
    if entry["is_ocr"] == "none" and parsed.unit == "page" and parsed.pages_need_ocr and \
            len(parsed.pages_need_ocr) == parsed.unit_count:
        kind = "待识别"  # 整份都是扫描件、还没有识别结果（契约 1.2 N28）
    head = [f"# {name}", "", f"> Source: {entry['rel_path']}（{kind}，{parsed.unit_count}{parsed.count_word}）",
            f"> Collected: {entry['imported_at'][:10]}"]
    if entry["note"]:
        head.append(f"> Note: {entry['note']}")
    parts = ["\n".join(head)]
    for b in parsed.blocks:
        parts.append(f"【{b.label}】\n{escape_marks(b.text)}" if b.text else f"【{b.label}】")
    return "\n\n".join(parts) + "\n"


# 正文里恰好与位置标记相同的整行（PDF 原文、识别文本里有一行就是"【第1页】"）：行首加一个全角空格，
# 读回时不会被当成我方的位置标记（注记 20261001-1354；formats.md 第 2 节）。
_MARK_LINE = re.compile(r"^(?=【(?:第[0-9]+[页段行]|表:[^\n]+)】$)", re.M)


def escape_marks(body: str) -> str:
    return _MARK_LINE.sub("\u3000", body)


class Materials:
    def __init__(self, cases: CaseRegistry, lo_base: pathlib.Path):
        self.lo_base = lo_base  # LibreOffice 配置目录的上级：<应用数据>/临时/lo（Spec 5.2）
        self.cases = cases
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        # 识别队列（T12）挂上：重新生成文本后把已有识别结果合并回去，签名 (root, index, material_ids)；持锁调用
        self.after_render = None

    def _lock(self, case_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(case_id, threading.Lock())

    # ---------- index.json ----------

    def _load_index(self, root: str, case_id: str) -> dict:
        p = gate.resolve_internal(root, INDEX_REL, op="materials_index")
        if not p.exists():
            return {"v": 1, "case_id": case_id, "next_seq": _recover_next_seq(root), "materials": []}
        data = contracts.read_json(p)
        if data.get("v") != 1:
            raise ApiError("INTERNAL", "index_unknown_v")
        contracts.validate(INDEX_SCHEMA, "", data)
        return data

    def _save_index(self, root: str, data: dict) -> None:
        contracts.validate(INDEX_SCHEMA, "", data)
        gate.write_bytes(root, INDEX_REL, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
                         op="materials_index")

    # ---------- 原件区遍历 ----------

    @staticmethod
    def walk(root: str) -> dict[str, tuple[str, os.stat_result | None]]:
        """{rel_path: (绝对路径, stat)}；不跟随链接，跳过 工作区、成果、以 . 开头的项和锁文件。"""
        return Materials.walk_all(root)[0]

    @staticmethod
    def walk_all(root: str) -> tuple[dict[str, tuple[str, os.stat_result | None]], list[str]]:
        """同 walk，另返回读不了的子文件夹（相对路径，以 / 结尾）。

        用长路径前缀（\\\\?\\）遍历：路径超过 259 字符的原件也要列出来，登记为失败而不是静默消失（T5 返修 X8）；
        它们的材料文本路径更长，解析时按 path_too_long 失败。stat 取不到的，stat 为 None，按"无法读取"登记。"""
        found: dict[str, tuple[str, os.stat_result | None]] = {}
        unreadable: list[str] = []
        stack: list[tuple[str, str]] = [(_long_path(root), "")]
        while stack:
            d, prefix = stack.pop()
            try:
                entries = list(os.scandir(d))
            except OSError:
                unreadable.append(prefix)
                continue
            for e in entries:
                name = e.name
                if name.startswith(".") or detect.is_ignored(name):
                    continue
                if not prefix and name in gate.WRITABLE_TOP:
                    continue
                rel = f"{prefix}{name}"
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    if detect.material_type(pathlib.Path(name)):
                        found[rel] = (e.path, None)
                    continue
                if _is_link_entry(st):
                    continue
                if stat.S_ISDIR(st.st_mode):
                    stack.append((e.path, rel + "/"))
                elif stat.S_ISREG(st.st_mode) and detect.material_type(pathlib.Path(name)):
                    found[rel] = (e.path, st)
        return found, sorted(unreadable)

    # ---------- 解析一份 ----------

    def _parse(self, root: str, rel: str, mtype: str, conv: Converter) -> Parsed:
        """扩展名定"哪一类材料"，文件头定"走哪条解析、过哪道检查"（T5 返修 X1）：
        - Word 类（docx / doc / wps）：压缩包 → 直接读 XML（不经 LibreOffice）；OLE → 查加密、查外链后交给
          LibreOffice 转 docx；其他（RTF、HTML 冒充 .doc 等）→ 查不了外链，不交给 LibreOffice（unchecked）。
        - Excel 类（xlsx / xls）：压缩包 → 查全部关系文件后直接读，只有没有外链才交给 LibreOffice 重算；
          OLE → 查加密后转 xlsx，转出来的再查关系文件；其他 → 同上不交给 LibreOffice。
        - PDF、文本、图片不经 LibreOffice，按扩展名解析，内容不符的由各自的解析器报损坏。"""
        path = gate.resolve_read(root, rel, op="materials_read")
        if path.stat().st_size > MAX_BYTES:
            raise ParseError("too_large")
        with conv.session() as s:
            if mtype == "pdf":
                return pdf.parse(path)
            if mtype in ("csv", "md", "txt"):
                return text.parse(path)
            if mtype == "image":
                return image.parse(path)
            kind = detect.content_kind(path)
            if mtype in ("docx", "doc", "wps"):
                if kind == "zip":
                    return docx.parse(path)
                if kind != "ole":
                    raise ParseError("corrupt" if mtype == "docx" else "not_office")  # N44 ①
                if detect.ole_encrypted(path):
                    raise ParseError("encrypted")
                if links.has_external_picture(path):
                    raise ParseError("external_link")  # 不交给 LibreOffice（Spec 14.3 ②a）
                return docx.parse(s.convert(path, "docx", suffix=".doc" if mtype == "docx" else None),
                                  note=CONVERTED_NOTE.get(mtype))
            if mtype in ("xlsx", "xls"):
                if kind == "zip":
                    rc = self._recalc(path, s)
                    return xlsx.parse(path, recalc=rc, blocked_note=None if rc else EXTERNAL_NOTE)
                if kind != "ole":
                    raise ParseError("corrupt" if mtype == "xlsx" else "not_office")  # N44 ①
                if detect.ole_encrypted(path):
                    raise ParseError("encrypted")
                converted = s.convert(path, "xlsx", suffix=".xls")
                rc = self._recalc(converted, s)
                return xlsx.parse(converted, recalc=rc, note=CONVERTED_NOTE["xls"],
                                  blocked_note=None if rc else EXTERNAL_NOTE)
        raise ParseError("corrupt")

    @staticmethod
    def _recalc(path: pathlib.Path, s):
        """有外链图片或对象的 xlsx 不交给 LibreOffice 重算（Calc 导入时会去取，设置拦不住；Spec 14.3 ②b）：
        返回 None，没有缓存值的单元格只写公式。关系文件查不了的报 unchecked（X2），整份不解析。"""
        if links.xlsx_has_external_rels(path):
            return None
        return lambda p: s.convert(p, "xlsx", suffix=".xlsx")

    # ---------- 扫描 ----------

    def scan(self, case_id: str) -> dict:
        root = self.cases.root_of(case_id)
        t0 = time.monotonic()
        with self._lock(case_id):
            result = self._scan(root, case_id)
        logs.event("materials", "scan", case_id=case_id, duration_ms=(time.monotonic() - t0) * 1000)
        return result

    def _scan(self, root: str, case_id: str) -> dict:
        if not os.path.isdir(root):
            raise ApiError("CASE_NOT_FOUND", "root_missing")
        for rel in ("工作区/材料", TEXT_DIR, TEMP_REL):
            gate.mkdir_work(root, rel, op="materials_scan")
        self._clean_temp(root)
        index = self._load_index(root, case_id)
        by_key = {_key(m["rel_path"]): m for m in index["materials"]}
        found, unreadable_dirs = self.walk_all(root)
        conv = Converter(gate.resolve_internal(root, TEMP_REL), lo_base=self.lo_base)
        stale_format = self._text_format(root) < TEXT_FORMAT_VERSION
        ids = _MaterialIds(root, self.cases.sql_path)
        ids.backfill(index)  # 升级前已有的材料：按 index.json 回填编号留底（T5 第三轮 P3-1）
        added = changed = removed = failed = recovered = 0
        parsed_now: dict[str, Parsed | None] = {}
        now = now_iso()

        counts = {"added": 0, "changed": 0, "failed": 0, "recovered": 0}
        for rel, (abspath, st) in sorted(found.items()):
            entry = by_key.get(_key(rel))
            live = entry is not None and entry["status"] != "source_deleted"
            # 跟环境有关的失败（转换程序异常、超时、路径太长、无法读取等）每次扫描都重试（X9）
            retry = live and entry["status"] == "failed" and entry["error"] in RETRY_MESSAGES
            # 材料文本格式版本变了：这几种材料原件没变也重新解析（X13）
            refresh = live and stale_format and entry["type"] in REFORMAT_TYPES and entry["status"] != "failed"
            redo = retry or refresh
            mt = mtime_iso(st) if st is not None else None
            if live and not redo and st is not None and entry["size"] == st.st_size and entry["mtime"] == mt:
                continue
            try:
                digest = sha256_file(abspath) if st is not None else None
            except OSError:
                digest = None  # 被占用、没有权限：登记为失败（X8），下次扫描重试
            if live and not redo and digest is not None and entry["sha256"] == digest:
                entry["size"], entry["mtime"] = st.st_size, mt
                continue
            mtype = detect.material_type(pathlib.Path(rel))
            if entry is None:
                used = {m["material_id"] for m in index["materials"]}
                mid = ids.reuse(rel, digest, used) if digest else None  # index.json 重建后拿回原编号（N26）
                if mid is None:
                    seq = max(index["next_seq"], ids.next_seq())
                    mid = f"M{seq:04d}"
                    index["next_seq"] = seq + 1
                ids.record(mid, rel, digest or "0" * 64, now, index["next_seq"])
                entry = {"material_id": mid, "rel_path": rel, "name": "", "imported_at": now}
                index["materials"].append(entry)
                by_key[_key(rel)] = entry
                counts["added"] += 1
            elif redo and (digest is None or digest == entry["sha256"] or entry["sha256"] == ZERO_SHA):
                pass  # 原件没变（或第一次就读不了、没有哈希可比），只是重试或按新格式重写
            else:
                counts["changed"] += 1
            if digest and entry.get("sha256") == ZERO_SHA:
                ids.fix_sha(entry["material_id"], digest)  # 第一次读不了时留底的是 64 个 0，现在更正
            # 读不了的原件没有哈希：沿用上次的；第一次就读不了的先填 64 个 0（契约要求 sha256 格式），下次重试时更正
            entry.update(type=mtype, size=st.st_size if st is not None else entry.get("size", 0),
                         mtime=mt or entry.get("mtime", now), sha256=digest or entry.get("sha256", "0" * 64),
                         updated_at=now, text_path=f"{TEXT_DIR}/{rel}.md", is_ocr="none")
            try:
                if digest is None:
                    raise ParseError("unreadable")
                if _too_long(root, entry["text_path"]) or (
                        mtype in ("xlsx", "xls") and _too_long(root, f"{FORMULA_DIR}/{rel}.txt")):
                    raise ParseError("path_too_long")  # 文本写不下去：只让这一份失败，不中断整次扫描
                p = self._parse(root, rel, mtype, conv)
            except ParseError as e:
                p = None
                entry.update(status="failed", unit=_default_unit(mtype), unit_count=0, pages_need_ocr=[],
                             pages_mixed=[], note=None, error=e.message)
                counts["failed"] += 1
                logs.event("materials", "parse", status="fail", case_id=case_id, error=e.reason)
            except ApiError:
                raise
            except Exception as e:  # noqa: BLE001 解析器报错一律按损坏处理，只记异常类名
                p = None
                entry.update(status="failed", unit=_default_unit(mtype), unit_count=0, pages_need_ocr=[],
                             pages_mixed=[], note=None, error=REASONS["corrupt"])
                counts["failed"] += 1
                logs.event("materials", "parse", status="fail", case_id=case_id, error=type(e).__name__)
            else:
                entry.update(status="needs_ocr" if p.pages_need_ocr else "parsed", unit=p.unit,
                             unit_count=p.unit_count, pages_need_ocr=p.pages_need_ocr, pages_mixed=p.pages_mixed,
                             note=p.note, error=None)
                if retry:
                    counts["recovered"] += 1
            parsed_now[entry["material_id"]] = p
        ids.close()
        added, changed, failed, recovered = counts["added"], counts["changed"], counts["failed"], counts["recovered"]

        seen = {_key(r) for r in found}
        for m in index["materials"]:
            if _key(m["rel_path"]) in seen or m["status"] == "source_deleted":
                continue
            if any(m["rel_path"].startswith(d) for d in unreadable_dirs):
                continue  # 所在文件夹这次读不了：不知道原件还在不在，不标"原件已删除"（X8）
            m["status"] = "source_deleted"
            m["updated_at"] = now
            removed += 1

        # 材料名：新材料导致重名时，已有材料的名字也改长
        names = assign_names([m["rel_path"] for m in index["materials"]])
        renamed = []
        for m in index["materials"]:
            new = names[m["rel_path"]]
            if m["name"] and m["name"] != new and m["material_id"] not in parsed_now:
                renamed.append(m)
            m["name"] = new

        for m in index["materials"]:
            if m["material_id"] not in parsed_now:
                continue
            p = parsed_now[m["material_id"]]
            if p is None:
                if m["text_path"].startswith(gate.WORK + "/"):
                    gate.delete_work_file(root, m["text_path"], op="materials_text")  # 不留旧版本的文本
                continue
            gate.write_bytes(root, m["text_path"], render(m["name"], m, p).encode("utf-8"), op="materials_text")
            if p.formulas:
                gate.write_bytes(root, f"{FORMULA_DIR}/{m['rel_path']}.txt", (p.formulas + "\n").encode("utf-8"),
                                 op="materials_text")
        for m in renamed:
            self._retitle(root, m)
        if self.after_render is not None:
            self.after_render(root, index, [mid for mid, p in parsed_now.items() if p is not None])

        self._save_index(root, index)
        self._write_status(root, index, unreadable_dirs)
        search_fts.refresh_after_scan(root, case_id, index)  # T9：扫描完就建检索索引（自己兜住异常）
        return {"added": added, "changed": changed, "removed": removed, "failed": failed,
                "review_needed": bool(added or changed or removed or recovered)}

    @staticmethod
    def _text_format(root: str) -> int:
        """_处理状态.md 里记的材料文本格式版本；没有这个文件或这一行的算 1（X13 之前）。"""
        try:
            p = gate.resolve_internal(root, STATUS_REL, op="materials_status")
            m = _FORMAT_LINE.search(p.read_text(encoding="utf-8")) if p.is_file() else None
        except (ApiError, OSError, UnicodeDecodeError):
            return 1
        return int(m.group(1)) if m else 1

    @staticmethod
    def _clean_temp(root: str) -> None:
        """扫描开始时（已在该案件的锁内）清掉本服务自己前缀的残留：转换的 lo-*、解压的 unzip-*、导入复制的 imp-*
        （T5 返修 X6）。只认这几个前缀：工作区/临时/ 里粘贴的截图、委托材料窗口的下载不能动。链接一律不碰。"""
        tdir = gate.resolve_internal(root, TEMP_REL, op="materials_scan")
        try:
            entries = list(os.scandir(tdir))
        except OSError:
            return
        for e in entries:
            if not (_OWN_TEMP_DIR.match(e.name) or _OWN_TEMP_FILE.match(e.name)):
                continue
            try:
                st = e.stat(follow_symlinks=False)
                if _is_link_entry(st):
                    logs.event("materials", "temp_cleanup", status="denied", error="LINK")
                elif stat.S_ISDIR(st.st_mode) and _OWN_TEMP_DIR.match(e.name):
                    remove_tree(pathlib.Path(e.path))  # 删不掉会记日志
                elif stat.S_ISREG(st.st_mode) and _OWN_TEMP_FILE.match(e.name):
                    os.unlink(e.path)
            except OSError as err:
                logs.event("materials", "temp_cleanup", status="fail", error=type(err).__name__)

    def _retitle(self, root: str, m: dict) -> None:
        p = gate.resolve_internal(root, m["text_path"], op="materials_text")
        if not p.is_file():
            return
        lines = p.read_text(encoding="utf-8").split("\n", 1)
        body = lines[1] if len(lines) > 1 else ""
        gate.write_bytes(root, m["text_path"], f"# {m['name']}\n{body}".encode("utf-8"), op="materials_text")

    def _write_status(self, root: str, index: dict, unreadable_dirs: list[str] = ()) -> None:
        mats = index["materials"]
        count = {s: sum(1 for m in mats if m["status"] == s) for s in
                 ("parsed", "needs_ocr", "failed", "source_deleted")}
        lines = ["# 材料处理状态", "", f"更新时间：{now_iso()}", f"材料文本格式版本：{TEXT_FORMAT_VERSION}", "",
                 f"共 {len(mats)} 份：已解析 {count['parsed']}，待识别 {count['needs_ocr']}，"
                 f"失败 {count['failed']}，原件已删除 {count['source_deleted']}。", ""]
        for title, st in (("处理失败", "failed"), ("待识别", "needs_ocr"), ("原件已删除", "source_deleted")):
            rows = [m for m in mats if m["status"] == st]
            if rows:
                lines.append(f"## {title}")
                for m in rows:
                    extra = m["error"] if st == "failed" else (
                        "第 " + "、".join(map(str, m["pages_need_ocr"])) + " 页" if st == "needs_ocr" else "保留原有文本")
                    lines.append(f"- {m['name']}：{extra}")
                lines.append("")
        if unreadable_dirs:
            lines.append(f"## 无法读取的文件夹（{len(unreadable_dirs)} 个，其中的文件这次没有列入，以前列入的保持原状）")
            lines += [f"- {d.rstrip('/') or '（案件文件夹本身）'}" for d in unreadable_dirs]
            lines.append("")
        gate.write_bytes(root, STATUS_REL, "\n".join(lines).encode("utf-8"), op="materials_status")

    def index(self, case_id: str) -> dict:
        """材料索引（只读，给工具和覆盖清单用）。不拿案件锁（T8 返修 P2-5）：扫描、导入要持锁很久，
        index.json 是原子替换写入的，不加锁读到的一定是完整的旧版或新版。"""
        root = self.cases.root_of(case_id)
        return self._load_index(root, case_id)

    # ---------- 列表 ----------

    def list(self, case_id: str) -> dict:
        root = self.cases.root_of(case_id)
        with self._lock(case_id):
            index = self._load_index(root, case_id)
        stale = self._stale_ocr(root, index)
        return {"materials": [{
            "material_id": m["material_id"], "name": m["name"], "rel_path": m["rel_path"], "type": m["type"],
            "status": m["status"], "unit": m["unit"], "unit_count": m["unit_count"], "is_ocr": m["is_ocr"],
            "stale_ocr": m["material_id"] in stale, "error": m["error"], "pages_need_ocr": m["pages_need_ocr"],
            "pages_mixed": m["pages_mixed"]} for m in index["materials"]]}

    @staticmethod
    def _stale_ocr(root: str, index: dict) -> set[str]:
        """原件变了而识别结果还是旧版本：该材料有已完成页的识别任务，但没有一个是当前 sha256 的
        （T12：原件改过后重新识别过，就不再算过期）。"""
        db = gate.resolve_internal(root, "工作区/case.db", op="materials_list")
        if not db.exists():
            return set()
        cur = {m["material_id"]: m["sha256"] for m in index["materials"]}
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            rows = con.execute("SELECT material_id, material_version FROM ocr_jobs WHERE done > 0").fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            con.close()
        current = {mid for mid, ver in rows if mid in cur and cur[mid] == ver}
        return {mid for mid, ver in rows if mid in cur and cur[mid] != ver and mid not in current}

    stale_ocr = _stale_ocr  # 工具 case_list_materials 也用

    # ---------- 导入（Spec 5.1） ----------

    def import_(self, case_id: str, paths: list[str], target: str | None, unzip: bool) -> dict:
        root = self.cases.root_of(case_id)
        t0 = time.monotonic()
        with self._lock(case_id):
            copied, skipped = self._import(root, paths, target, unzip)
        scan = self.scan(case_id)
        logs.event("materials", "import", case_id=case_id, duration_ms=(time.monotonic() - t0) * 1000)
        return {"copied": copied, "skipped": skipped, "scan": scan}

    def _default_target(self, root: str) -> str:
        return "02案件材料" if os.path.isdir(os.path.join(root, "02案件材料")) else ""

    def _import(self, root: str, paths: list[str], target: str | None, unzip: bool):
        if target is None:
            target = self._default_target(root)
        else:
            target = target.strip("/")
            gate.check_ai_rel(target, op="import_target")
        copied: list[dict] = []
        skipped: list[dict] = []
        for src in paths:
            if not os.path.isabs(src):
                raise ApiError("INVALID_ARGUMENT", "path_not_abs")
            p = gate.strip_long_prefix(os.path.normpath(src))  # \\?\ 写法先去掉前缀（B-P2-1）
            try:
                st = os.lstat(p)
            except OSError:
                skipped.append({"path": src, "reason": "无法读取"})
                continue
            if _is_link_entry(st) or os.path.splitext(p)[1].lower() in SHORTCUT_EXT:
                skipped.append({"path": src, "reason": "链接或快捷方式"})
                continue
            real = os.path.realpath(p)
            # 是不是案件根目录或它里面：按文件身份逐级比对上级目录，\\?\、UNC 管理共享等别名写法也认得出（B-P2-1）
            parts = _parts_in_case(p, root)
            if parts is None and gate.is_within(root, real):
                parts = os.path.relpath(real, root).replace("\\", "/").split("/")
            if parts == []:
                continue  # 导入源就是案件根目录：按"已在案件内"处理，只扫描（X3）
            if parts is not None:
                if parts[0] == gate.WORK:
                    # 只有 工作区/临时/ 下的文件（粘贴的截图、委托材料下载）按临时文件导入：复制成功或判定
                    # "同名同内容已存在"之后才删；工作区 下其他位置的不接受导入（X7）
                    if len(parts) > 2 and parts[1] == "临时" and stat.S_ISREG(st.st_mode):
                        if self._import_file(root, p, target, os.path.basename(p), copied, skipped, unzip):
                            gate.delete_work_file(root, "/".join(parts), op="import")
                    else:
                        skipped.append({"path": src, "reason": "无法读取"})
                continue  # 已在案件文件夹内：不复制，直接解析
            if gate.in_sync_folder(p) or gate.in_sync_folder(real):
                skipped.append({"path": src, "reason": "云同步目录"})
                continue
            if stat.S_ISDIR(st.st_mode):
                self._import_dir(root, p, target, copied, skipped)
            elif stat.S_ISREG(st.st_mode):
                self._import_file(root, p, target, os.path.basename(p), copied, skipped, unzip)
            else:
                skipped.append({"path": src, "reason": "无法读取"})
        return copied, skipped

    def _import_dir(self, root: str, src_dir: str, target: str, copied, skipped) -> None:
        """案件根目录在导入源之内（拖进来的是案件的上级文件夹）：跳过案件根目录那一支，不复制也不计入跳过（X3）。
        任何层级以 . 开头的项都跳过，计入"跳过"（X12，与扫描一致）。"""
        base = _join(target, os.path.basename(src_dir.rstrip("\\/")))
        stack = [(src_dir, base)]
        while stack:
            d, dest = stack.pop()
            try:
                entries = sorted(os.scandir(d), key=lambda e: e.name)
            except OSError:
                skipped.append({"path": d, "reason": "无法读取"})
                continue
            for e in entries:
                if e.name.startswith("."):
                    skipped.append({"path": e.path, "reason": "无法读取"})
                    continue
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    skipped.append({"path": e.path, "reason": "无法读取"})
                    continue
                if _is_link_entry(st) or os.path.splitext(e.name)[1].lower() in SHORTCUT_EXT:
                    skipped.append({"path": e.path, "reason": "链接或快捷方式"})
                elif stat.S_ISDIR(st.st_mode):
                    if not _same_file(e.path, root):  # 案件根目录那一支：按文件身份比，别名写法也认得出
                        stack.append((e.path, _join(dest, e.name)))
                elif stat.S_ISREG(st.st_mode):
                    self._copy_one(root, e.path, _join(dest, e.name), copied, skipped)

    def _import_file(self, root: str, src: str, target: str, name: str, copied, skipped, unzip: bool) -> bool:
        """返回是否全部落位（复制成功或同名同内容已存在）：导入临时文件时只有这样才删源文件（X7）。"""
        if unzip and name.lower().endswith(".zip"):
            return self._import_zip(root, src, target, copied, skipped)
        return self._copy_one(root, src, _join(target, name), copied, skipped)

    def _copy_one(self, root: str, src: str, dest_rel: str, copied, skipped, from_label: str | None = None) -> bool:
        label = from_label or src
        try:
            size = os.path.getsize(src)
        except OSError:
            skipped.append({"path": label, "reason": "无法读取"})
            return False
        if size > MAX_BYTES:
            skipped.append({"path": label, "reason": "超过大小上限"})
            return False
        try:
            digest = sha256_file(src)
        except OSError:
            skipped.append({"path": label, "reason": "无法读取"})
            return False
        stem, ext = os.path.splitext(dest_rel)
        n = 1
        while True:
            cand = dest_rel if n == 1 else f"{stem}({n}){ext}"
            try:
                existing = gate.resolve_read(root, cand, op="import")
            except ApiError:
                # 文件名是设备名（con.txt）或以 . 开头（.env）等闸门不收的名字：只跳过这一个，不中止整次导入
                skipped.append({"path": label, "reason": "无法读取"})
                return False
            if os.path.lexists(existing):
                if os.path.isfile(existing) and not gate.is_link(existing) and sha256_file(existing) == digest:
                    skipped.append({"path": label, "reason": "同名同内容已存在"})
                    return True
                n += 1
                continue
            try:
                gate.copy_original(root, cand, src, op="import")
            except FileExistsError:
                continue  # 并发下被别人抢先建了同名文件：重新比对
            except OSError:
                skipped.append({"path": label, "reason": "无法读取"})
                return False
            copied.append({"from": label, "to": cand})
            return True

    def _import_zip(self, root: str, src: str, target: str, copied, skipped) -> bool:
        """ZIP 先解压到 工作区/临时/（拒绝越界、链接、超过 500 个文件），再按普通文件复制。
        任何层级以 . 开头的成员跳过（X12）。返回是否每个成员都已落位。"""
        try:
            zf = zipfile.ZipFile(src)
        except (zipfile.BadZipFile, OSError):
            skipped.append({"path": src, "reason": "无法读取"})
            return False
        with zf:
            members = [i for i in zf.infolist() if not i.is_dir()]
            if len(members) > ZIP_MAX_FILES or any(_zip_bad(i) for i in zf.infolist()):
                skipped.append({"path": src, "reason": "无法读取"})
                return False
            tops = {i.filename.replace("\\", "/").split("/")[0] for i in members}
            dest_base = "" if tops & STANDARD_TOPS else target
            work_rel = f"{TEMP_REL}/unzip-{uuid.uuid4().hex[:8]}"
            work = gate.mkdir_work(root, work_rel, op="import")
            done = True
            try:
                for i, info in enumerate(members):
                    name = info.filename.replace("\\", "/")
                    label = src + os.sep + name.replace("/", os.sep)
                    if any(part.startswith(".") for part in name.split("/")):
                        skipped.append({"path": label, "reason": "无法读取"})
                        done = False
                        continue
                    if info.file_size > MAX_BYTES:
                        skipped.append({"path": label, "reason": "超过大小上限"})
                        done = False
                        continue
                    tmp = gate.write_bytes(root, f"{work_rel}/{i}", zf.read(info), op="import")
                    done = self._copy_one(root, str(tmp), _join(dest_base, name), copied, skipped,
                                          from_label=label) and done
            finally:
                remove_tree(work)  # 删不掉记日志（Y2），下次扫描按 unzip- 前缀再清
            return done


def _zip_bad(info: zipfile.ZipInfo) -> bool:
    name = info.filename.replace("\\", "/")
    if name.startswith("/") or ":" in name or any(p == ".." for p in name.split("/")):
        return True
    mode = (info.external_attr >> 16) & 0o170000
    return mode == stat.S_IFLNK


# Windows 不开长路径支持时：文件完整路径不超过 259 字符，新建目录不超过 247 字符；
# 原子写的临时文件（.~lb-xxxxxxxx.tmp，17 字符）和目标在同一目录，也要放得下
_MAX_FILE = 259
_MAX_DIR = 247
_ATOMIC_TMP_NAME = 17


def _too_long(root: str, rel: str) -> bool:
    if os.name != "nt":
        return False
    full = os.path.join(root, *rel.split("/"))
    parent = os.path.dirname(full)
    return (len(full) > _MAX_FILE or len(parent) > _MAX_DIR
            or len(parent) + 1 + _ATOMIC_TMP_NAME > _MAX_FILE)


def _long_path(path: str) -> str:
    """Windows 上加长路径前缀，遍历、读取不受 260 字符上限影响（X8）。"""
    if os.name != "nt" or path.startswith("\\\\?\\"):
        return path
    path = os.path.abspath(path)
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


_MID = re.compile(r"^M(\d{4,})$")


def _recover_next_seq(root: str) -> int:
    """index.json 不在了（被删）时的起始编号（T5 返修 X11，裁决 2）：从"案件里还能找到的最大编号"加 1 起，
    来源是 case.db 里出现过的材料编号、工作区/材料/识别页/ 下的目录名、工作区/wiki/材料/ 下的文件名，旧编号不再复用。
    根治要在 case.db 里留底（改契约，候 owner N26）。"""
    seen: list[int] = []

    def take(mid) -> None:
        m = _MID.match(str(mid))
        if m:
            seen.append(int(m.group(1)))

    for rel, strip_suffix in (("工作区/材料/识别页", False), ("工作区/wiki/材料", True)):
        try:
            d = gate.resolve_internal(root, rel, op="materials_index")
            names = [e.name for e in os.scandir(d)] if d.is_dir() else []
        except (ApiError, OSError):
            names = []
        for n in names:
            take(os.path.splitext(n)[0] if strip_suffix else n)
    try:
        db = gate.resolve_internal(root, "工作区/case.db", op="materials_index")
        if db.is_file():
            con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
            try:
                for table in ("material_ids", "ocr_jobs", "search_units"):
                    try:
                        for (mid,) in con.execute(f"SELECT DISTINCT material_id FROM {table}"):
                            take(mid)
                    except sqlite3.Error:
                        pass
                try:
                    row = con.execute("SELECT value FROM meta WHERE key = 'next_material_seq'").fetchone()
                    if row and str(row[0]).isdigit():
                        seen.append(int(row[0]) - 1)
                except sqlite3.Error:
                    pass
            finally:
                con.close()
    except (ApiError, OSError, sqlite3.Error):
        pass
    return max(seen, default=0) + 1


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except (OSError, ValueError):
        return _same_path(os.path.realpath(a), b)


def _parts_in_case(path: str, root: str) -> list[str] | None:
    """path 是案件根目录本身返回 []；在根目录之内返回相对的各级名字；不在返回 None。逐级往上比文件身份。"""
    cur = os.path.abspath(path)
    names: list[str] = []
    while True:
        if _same_file(cur, root):
            return list(reversed(names))
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        names.append(os.path.basename(cur))
        cur = parent


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


class _MaterialIds:
    """case.db 的 material_ids 表（契约 1.2 N26，T5 返修 X11）：分配编号时写一行，meta 里记 next_material_seq；
    index.json 丢失后重建时，同一份原件（rel_path + sha256）拿回原编号，新编号从
    max(next_material_seq, 表内最大编号 + 1) 起。index.json 仍是主本：case.db 不在或读写出错时只记日志，照常扫描。"""

    def __init__(self, root: str, sql_path: pathlib.Path | None = None):
        self.con = None
        try:
            db = gate.resolve_internal(root, "工作区/case.db", op="materials_ids")
            if not db.is_file():
                logs.event("materials", "material_ids", status="fail", error="CASE_DB_MISSING")
                return
            con = sqlite3.connect(str(db), timeout=10)
            has = con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'material_ids'").fetchone()
            if not has:
                # 打开案件时已按契约补建；万一还没有（旧库、打开之后被人动过）：按契约补建并记日志，不静默跳过
                logs.event("materials", "material_ids", status="fail", error="TABLE_MISSING")
                if sql_path is not None:
                    con.executescript(pathlib.Path(sql_path).read_text(encoding="utf-8"))
            self.con = con
        except (ApiError, OSError, sqlite3.Error) as e:
            logs.event("materials", "material_ids", status="fail", error=type(e).__name__)

    def _q(self, sql: str, args=()):
        if self.con is None:
            return []
        try:
            return self.con.execute(sql, args).fetchall()
        except sqlite3.Error as e:
            logs.event("materials", "material_ids", status="fail", error=type(e).__name__)
            return []

    def reuse(self, rel: str, digest: str, used: set[str]) -> str | None:
        for (mid,) in self._q("SELECT material_id FROM material_ids WHERE rel_path = ? AND sha256 = ? "
                              "ORDER BY material_id", (rel, digest)):
            if mid not in used and _MID.match(mid):
                return mid
        return None

    def next_seq(self) -> int:
        n = 1
        for (mid,) in self._q("SELECT material_id FROM material_ids"):
            m = _MID.match(mid)
            if m:
                n = max(n, int(m.group(1)) + 1)
        for (v,) in self._q("SELECT value FROM meta WHERE key = 'next_material_seq'"):
            if str(v).isdigit():
                n = max(n, int(v))
        return n

    def record(self, mid: str, rel: str, digest: str, now: str, next_seq: int) -> None:
        if self.con is None:
            return
        try:
            with self.con:
                self.con.execute("INSERT OR IGNORE INTO material_ids (material_id, rel_path, sha256, first_seen) "
                                 "VALUES (?, ?, ?, ?)", (mid, rel, digest, now))
                cur = self.next_seq()
                self.con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('next_material_seq', ?)",
                                 (str(max(cur, next_seq)),))
        except sqlite3.Error as e:
            logs.event("materials", "material_ids", status="fail", error=type(e).__name__)

    def backfill(self, index: dict) -> None:
        """把 index.json 里已有的材料补进 material_ids（INSERT OR IGNORE）：1.2 之前建的库补表后是空的，
        不回填的话 index.json 再丢一次，这些材料就拿不回原编号。"""
        if self.con is None or not index["materials"]:
            return
        try:
            with self.con:
                self.con.executemany(
                    "INSERT OR IGNORE INTO material_ids (material_id, rel_path, sha256, first_seen) VALUES (?, ?, ?, ?)",
                    [(m["material_id"], m["rel_path"], m["sha256"], m["imported_at"]) for m in index["materials"]])
        except sqlite3.Error as e:
            logs.event("materials", "material_ids", status="fail", error=type(e).__name__)

    def fix_sha(self, mid: str, digest: str) -> None:
        if self.con is None:
            return
        try:
            with self.con:
                self.con.execute("UPDATE material_ids SET sha256 = ? WHERE material_id = ? AND sha256 = ?",
                                 (digest, mid, ZERO_SHA))
        except sqlite3.Error as e:
            logs.event("materials", "material_ids", status="fail", error=type(e).__name__)

    def close(self) -> None:
        if self.con is not None:
            self.con.close()
            self.con = None


def _join(a: str, b: str) -> str:
    return f"{a}/{b}" if a else b


def _default_unit(mtype: str) -> str:
    return {"pdf": "page", "image": "page", "docx": "para", "doc": "para", "wps": "para", "xlsx": "cell",
            "xls": "cell"}.get(mtype, "line")
