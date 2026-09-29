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
from ..ingest import MAX_BYTES, REASONS, Parsed, ParseError
from ..ingest import detect, docx, image, links, pdf, text, xlsx
from ..ingest.libreoffice import Converter
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
    """① 文件名去扩展名；② 重复时用去扩展名的相对路径；③ 仍重复时用带扩展名的相对路径。"""
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
        for r, n in cand.items():
            if (counts[n.casefold()] == 1 and n.casefold() not in taken) or i == len(levels) - 1:
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
    head = [f"# {name}", "", f"> Source: {entry['rel_path']}（{kind}，{parsed.unit_count}{parsed.count_word}）",
            f"> Collected: {entry['imported_at'][:10]}"]
    if entry["note"]:
        head.append(f"> Note: {entry['note']}")
    parts = ["\n".join(head)]
    for b in parsed.blocks:
        parts.append(f"【{b.label}】\n{b.text}" if b.text else f"【{b.label}】")
    return "\n\n".join(parts) + "\n"


class Materials:
    def __init__(self, cases: CaseRegistry, lo_base: pathlib.Path | None = None):
        self.lo_base = lo_base  # LibreOffice 配置目录的上级：<应用数据>/临时/lo（Spec 5.2）
        self.cases = cases
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock(self, case_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(case_id, threading.Lock())

    # ---------- index.json ----------

    def _load_index(self, root: str, case_id: str) -> dict:
        p = gate.resolve_internal(root, INDEX_REL, op="materials_index")
        if not p.exists():
            return {"v": 1, "case_id": case_id, "next_seq": 1, "materials": []}
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
    def walk(root: str) -> dict[str, tuple[str, os.stat_result]]:
        """{rel_path: (绝对路径, stat)}；不跟随链接，跳过 工作区、成果、以 . 开头的项和锁文件。"""
        found: dict[str, tuple[str, os.stat_result]] = {}
        stack: list[tuple[str, str]] = [(root, "")]
        while stack:
            d, prefix = stack.pop()
            try:
                entries = list(os.scandir(d))
            except OSError:
                continue
            for e in entries:
                name = e.name
                if name.startswith(".") or detect.is_ignored(name):
                    continue
                if not prefix and name in gate.WRITABLE_TOP:
                    continue
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if _is_link_entry(st):
                    continue
                rel = f"{prefix}{name}"
                if stat.S_ISDIR(st.st_mode):
                    stack.append((e.path, rel + "/"))
                elif stat.S_ISREG(st.st_mode) and detect.material_type(pathlib.Path(name)):
                    found[rel] = (e.path, st)
        return found

    # ---------- 解析一份 ----------

    def _parse(self, root: str, rel: str, mtype: str, conv: Converter) -> Parsed:
        path = gate.resolve_read(root, rel, op="materials_read")
        if path.stat().st_size > MAX_BYTES:
            raise ParseError("too_large")
        with conv.session() as s:
            if mtype == "pdf":
                return pdf.parse(path)
            if mtype == "docx":
                return docx.parse(path)
            if mtype in ("doc", "wps"):
                if detect.is_ole(path) and detect.ole_encrypted(path):
                    raise ParseError("encrypted")
                if links.has_external_picture(path):
                    raise ParseError("external_link")  # 不交给 LibreOffice（Spec 14.3 ②a）
                return docx.parse(s.convert(path, "docx"), note=CONVERTED_NOTE[mtype])
            if mtype == "xlsx":
                return xlsx.parse(path, recalc=self._recalc(path, s))
            if mtype == "xls":
                if detect.is_ole(path) and detect.ole_encrypted(path):
                    raise ParseError("encrypted")
                converted = s.convert(path, "xlsx")
                return xlsx.parse(converted, recalc=self._recalc(converted, s), note=CONVERTED_NOTE["xls"])
            if mtype in ("csv", "md", "txt"):
                return text.parse(path)
            if mtype == "image":
                return image.parse(path)
        raise ParseError("corrupt")

    @staticmethod
    def _recalc(path: pathlib.Path, s):
        """有外链图片或对象的 xlsx 不交给 LibreOffice 重算（Calc 导入时会去取，设置拦不住；Spec 14.3 ②b）：
        返回 None，没有缓存值的单元格只写公式。"""
        if links.xlsx_has_external_rels(path):
            return None
        return lambda p: s.convert(p, "xlsx")

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
        index = self._load_index(root, case_id)
        by_key = {_key(m["rel_path"]): m for m in index["materials"]}
        found = self.walk(root)
        conv = Converter(gate.resolve_internal(root, TEMP_REL), lo_base=self.lo_base)
        added = changed = removed = failed = 0
        parsed_now: dict[str, Parsed | None] = {}
        now = now_iso()

        for rel, (abspath, st) in sorted(found.items()):
            entry = by_key.get(_key(rel))
            mt = mtime_iso(st)
            if entry and entry["status"] != "source_deleted" and entry["size"] == st.st_size and entry["mtime"] == mt:
                continue
            try:
                digest = sha256_file(abspath)
            except OSError:
                continue  # 读不了（被占用等）：下次再扫
            if entry and entry["status"] != "source_deleted" and entry["sha256"] == digest:
                entry["size"], entry["mtime"] = st.st_size, mt
                continue
            mtype = detect.material_type(pathlib.Path(rel))
            if entry is None:
                entry = {"material_id": f"M{index['next_seq']:04d}", "rel_path": rel, "name": "",
                         "imported_at": now}
                index["next_seq"] += 1
                index["materials"].append(entry)
                by_key[_key(rel)] = entry
                added += 1
            else:
                changed += 1
            entry.update(type=mtype, size=st.st_size, mtime=mt, sha256=digest, updated_at=now,
                         text_path=f"{TEXT_DIR}/{rel}.md", is_ocr="none")
            try:
                if _too_long(root, entry["text_path"]) or (
                        mtype in ("xlsx", "xls") and _too_long(root, f"{FORMULA_DIR}/{rel}.txt")):
                    raise ParseError("path_too_long")  # 文本写不下去：只让这一份失败，不中断整次扫描
                p = self._parse(root, rel, mtype, conv)
            except ParseError as e:
                p = None
                entry.update(status="failed", unit=_default_unit(mtype), unit_count=0, pages_need_ocr=[],
                             pages_mixed=[], note=None, error=e.message)
                failed += 1
                logs.event("materials", "parse", status="fail", case_id=case_id, error=e.reason)
            except ApiError:
                raise
            except Exception as e:  # noqa: BLE001 解析器报错一律按损坏处理，只记异常类名
                p = None
                entry.update(status="failed", unit=_default_unit(mtype), unit_count=0, pages_need_ocr=[],
                             pages_mixed=[], note=None, error=REASONS["corrupt"])
                failed += 1
                logs.event("materials", "parse", status="fail", case_id=case_id, error=type(e).__name__)
            else:
                entry.update(status="needs_ocr" if p.pages_need_ocr else "parsed", unit=p.unit,
                             unit_count=p.unit_count, pages_need_ocr=p.pages_need_ocr, pages_mixed=p.pages_mixed,
                             note=p.note, error=None)
            parsed_now[entry["material_id"]] = p

        seen = {_key(r) for r in found}
        for m in index["materials"]:
            if _key(m["rel_path"]) not in seen and m["status"] != "source_deleted":
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

        self._save_index(root, index)
        self._write_status(root, index)
        return {"added": added, "changed": changed, "removed": removed, "failed": failed,
                "review_needed": bool(added or changed or removed)}

    def _retitle(self, root: str, m: dict) -> None:
        p = gate.resolve_internal(root, m["text_path"], op="materials_text")
        if not p.is_file():
            return
        lines = p.read_text(encoding="utf-8").split("\n", 1)
        body = lines[1] if len(lines) > 1 else ""
        gate.write_bytes(root, m["text_path"], f"# {m['name']}\n{body}".encode("utf-8"), op="materials_text")

    def _write_status(self, root: str, index: dict) -> None:
        mats = index["materials"]
        count = {s: sum(1 for m in mats if m["status"] == s) for s in
                 ("parsed", "needs_ocr", "failed", "source_deleted")}
        lines = ["# 材料处理状态", "", f"更新时间：{now_iso()}", "",
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
        gate.write_bytes(root, STATUS_REL, "\n".join(lines).encode("utf-8"), op="materials_status")

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
        """原件变了而识别结果还是旧版本：case.db 里有该材料的识别任务，但 material_version 不是当前 sha256。"""
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
        return {mid for mid, ver in rows if mid in cur and cur[mid] != ver}

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
            p = os.path.normpath(src)
            try:
                st = os.lstat(p)
            except OSError:
                skipped.append({"path": src, "reason": "无法读取"})
                continue
            if _is_link_entry(st) or os.path.splitext(p)[1].lower() in SHORTCUT_EXT:
                skipped.append({"path": src, "reason": "链接或快捷方式"})
                continue
            real = os.path.realpath(p)
            if gate.is_within(root, real):
                rel = os.path.relpath(real, root).replace("\\", "/")
                top = rel.split("/")[0]
                if top == gate.WORK and stat.S_ISREG(st.st_mode):
                    # 工作区 下的临时文件（粘贴的截图、委托材料下载）：复制到目标后删除临时文件
                    self._import_file(root, p, target, os.path.basename(p), copied, skipped, unzip)
                    gate.delete_work_file(root, rel, op="import")
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
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    skipped.append({"path": e.path, "reason": "无法读取"})
                    continue
                if _is_link_entry(st) or os.path.splitext(e.name)[1].lower() in SHORTCUT_EXT:
                    skipped.append({"path": e.path, "reason": "链接或快捷方式"})
                elif stat.S_ISDIR(st.st_mode):
                    stack.append((e.path, _join(dest, e.name)))
                elif stat.S_ISREG(st.st_mode):
                    self._copy_one(root, e.path, _join(dest, e.name), copied, skipped)

    def _import_file(self, root: str, src: str, target: str, name: str, copied, skipped, unzip: bool) -> None:
        if unzip and name.lower().endswith(".zip"):
            self._import_zip(root, src, target, copied, skipped)
        else:
            self._copy_one(root, src, _join(target, name), copied, skipped)

    def _copy_one(self, root: str, src: str, dest_rel: str, copied, skipped, from_label: str | None = None) -> None:
        label = from_label or src
        try:
            size = os.path.getsize(src)
        except OSError:
            skipped.append({"path": label, "reason": "无法读取"})
            return
        if size > MAX_BYTES:
            skipped.append({"path": label, "reason": "超过大小上限"})
            return
        try:
            digest = sha256_file(src)
        except OSError:
            skipped.append({"path": label, "reason": "无法读取"})
            return
        stem, ext = os.path.splitext(dest_rel)
        n = 1
        while True:
            cand = dest_rel if n == 1 else f"{stem}({n}){ext}"
            try:
                existing = gate.resolve_read(root, cand, op="import")
            except ApiError:
                # 文件名是设备名（con.txt）或以 . 开头（.env）等闸门不收的名字：只跳过这一个，不中止整次导入
                skipped.append({"path": label, "reason": "无法读取"})
                return
            if os.path.lexists(existing):
                if os.path.isfile(existing) and not gate.is_link(existing) and sha256_file(existing) == digest:
                    skipped.append({"path": label, "reason": "同名同内容已存在"})
                    return
                n += 1
                continue
            try:
                gate.copy_original(root, cand, src, op="import")
            except FileExistsError:
                continue  # 并发下被别人抢先建了同名文件：重新比对
            except OSError:
                skipped.append({"path": label, "reason": "无法读取"})
                return
            copied.append({"from": label, "to": cand})
            return

    def _import_zip(self, root: str, src: str, target: str, copied, skipped) -> None:
        """ZIP 先解压到 工作区/临时/（拒绝越界、链接、超过 500 个文件），再按普通文件复制。"""
        try:
            zf = zipfile.ZipFile(src)
        except (zipfile.BadZipFile, OSError):
            skipped.append({"path": src, "reason": "无法读取"})
            return
        with zf:
            members = [i for i in zf.infolist() if not i.is_dir()]
            if len(members) > ZIP_MAX_FILES or any(_zip_bad(i) for i in zf.infolist()):
                skipped.append({"path": src, "reason": "无法读取"})
                return
            tops = {i.filename.replace("\\", "/").split("/")[0] for i in members}
            dest_base = "" if tops & STANDARD_TOPS else target
            work_rel = f"{TEMP_REL}/unzip-{uuid.uuid4().hex[:8]}"
            work = gate.mkdir_work(root, work_rel, op="import")
            try:
                for i, info in enumerate(members):
                    name = info.filename.replace("\\", "/")
                    label = src + os.sep + name.replace("/", os.sep)
                    if info.file_size > MAX_BYTES:
                        skipped.append({"path": label, "reason": "超过大小上限"})
                        continue
                    tmp = gate.write_bytes(root, f"{work_rel}/{i}", zf.read(info), op="import")
                    self._copy_one(root, str(tmp), _join(dest_base, name), copied, skipped, from_label=label)
            finally:
                shutil.rmtree(work, ignore_errors=True)


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


def _join(a: str, b: str) -> str:
    return f"{a}/{b}" if a else b


def _default_unit(mtype: str) -> str:
    return {"pdf": "page", "image": "page", "docx": "para", "doc": "para", "wps": "para", "xlsx": "cell",
            "xls": "cell"}.get(mtype, "line")
