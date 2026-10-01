"""把识别结果合并进材料文本（Spec 7.2 第 4 条、5.3；formats.md 第 2 节）。

识别结果单独存在 工作区/材料/识别页/<材料编号>/<页号>.md，是唯一的主本；材料文本里的识别页由它合并而来，
所以材料文本被重新生成（格式版本升级、环境类原因重试，T5 第二轮复核 B 发现）后可以再合并一次，不会丢。

合并规则：
- 只用与原件当前 sha256 相同的任务的已完成页；同一页有多次结果时取最近提交的任务。
- 该页块整体换成 "> 识别所得" 加识别文本（无论原来是"（本页需识别）"占位还是图文混排页提取的文字）。
- Source 行的类型：每页都是识别所得 → 识别所得；有一部分 → 部分识别；没有 → 文字版（整份待识别仍写"待识别"）。
- index.json：is_ocr 同上；pages_need_ocr 改为仍是占位的页；status：有进行中的任务 → ocr_running，
  需识别的页都有结果 → parsed，有结果但还有页没识别（含失败）→ partial，一页结果都没有 → needs_ocr。
"""
from __future__ import annotations

import contextlib
import re
import sqlite3
from datetime import datetime

from .. import logs
from ..case import gate, texts

RESULT_DIR = "工作区/材料/识别页"
OCR_TYPES = ("pdf", "image")
ACTIVE = ("queued", "running", "paused")
_PAGE_MARK = re.compile(r"^【第(\d+)页】\n?", re.M)
_SOURCE = re.compile(r"^(> Source: .*（)(文字版|部分识别|识别所得|待识别)(，)", re.M)
OCR_HEAD = "> 识别所得"


def result_rel(material_id: str, page_no: int) -> str:
    return f"{RESULT_DIR}/{material_id}/{page_no}.md"


@contextlib.contextmanager
def connect(root: str):
    """case.db 连接：正常结束提交、出错回滚，最后一定关闭（不留文件句柄，Windows 上才删得掉案件文件夹）。"""
    db = gate.resolve_internal(root, "工作区/case.db", op="ocr_db")
    con = sqlite3.connect(str(db), timeout=10)
    try:
        with con:
            yield con
    finally:
        con.close()


def ocr_results(root: str, material_id: str, sha256: str) -> dict[int, str]:
    """{页号: 识别文本}：只取与原件当前版本一致的任务里已完成的页，同页取最近的任务。"""
    with connect(root) as con:
        rows = con.execute(
            "SELECT p.page_no, p.result_path FROM ocr_pages p JOIN ocr_jobs j ON p.job_id = j.job_id "
            "WHERE j.material_id = ? AND j.material_version = ? AND p.status = 'done' "
            "ORDER BY j.created_at, j.job_id", (material_id, sha256)).fetchall()
    out: dict[int, str] = {}
    for page_no, _rel in rows:
        path = gate.resolve_internal(root, result_rel(material_id, page_no), op="ocr_result")
        if path.is_file():
            out[int(page_no)] = path.read_text(encoding="utf-8")
    return out


def has_active_job(root: str, material_id: str, sha256: str) -> bool:
    with connect(root) as con:
        return con.execute(
            f"SELECT 1 FROM ocr_jobs WHERE material_id = ? AND material_version = ? AND status IN "
            f"({','.join('?' * len(ACTIVE))}) LIMIT 1", (material_id, sha256, *ACTIVE)).fetchone() is not None


def merge_text(text: str, results: dict[int, str]) -> tuple[str, dict]:
    """返回（新文本，统计）。统计：pages 总页数、ocr 识别所得的页、pending 仍是占位的页。"""
    parts = _PAGE_MARK.split(text)
    head, rest = parts[0], parts[1:]
    blocks: list[tuple[int, str]] = [(int(rest[i]), rest[i + 1]) for i in range(0, len(rest), 2)]
    out_blocks: list[str] = []
    ocr_pages, pending = [], []
    for no, body in blocks:
        body = body.rstrip("\n")
        if no in results:
            body = OCR_HEAD + "\n" + results[no].strip("\n")
        if body.startswith(OCR_HEAD):
            ocr_pages.append(no)
        elif body.strip() == texts.PENDING_OCR:
            pending.append(no)
        out_blocks.append(f"【第{no}页】\n{body}" if body else f"【第{no}页】")
    total = len(blocks)
    if total and len(ocr_pages) == total:
        kind = "识别所得"
    elif ocr_pages:
        kind = "部分识别"
    elif total and len(pending) == total:
        kind = "待识别"
    else:
        kind = "文字版"
    head = _SOURCE.sub(lambda m: m.group(1) + kind + m.group(3), head, count=1)
    new = head.rstrip("\n") + "\n\n" + "\n\n".join(out_blocks) + "\n" if out_blocks else text
    return new, {"pages": total, "ocr": ocr_pages, "pending": pending}


def merge_entry(root: str, entry: dict, active: bool | None = None) -> bool:
    """把识别结果合并进这份材料的文本、改它的 index 条目（就地改 entry）。调用方持有该案件材料锁、负责保存 index。
    没有可合并的结果、且没有进行中的任务时不动。返回是否改过。"""
    if entry.get("type") not in OCR_TYPES or entry.get("status") in ("failed", "source_deleted"):
        return False
    results = ocr_results(root, entry["material_id"], entry["sha256"])
    if active is None:                       # 任务收尾时调用方传 False：先合并、再把任务标完成，列表上见到"完成"时文本已就绪
        active = has_active_job(root, entry["material_id"], entry["sha256"])
    if not results and not active:
        return False
    rel = texts.text_rel(entry)
    path = gate.resolve_internal(root, rel, op="ocr_merge")
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    new, st = merge_text(text, results)
    if new != text:
        gate.write_bytes(root, rel, new.encode("utf-8"), op="ocr_merge")
    if st["pages"] and len(st["ocr"]) == st["pages"]:
        entry["is_ocr"] = "full"
    elif st["ocr"]:
        entry["is_ocr"] = "partial"
    else:
        entry["is_ocr"] = "none"
    entry["pages_need_ocr"] = st["pending"]
    if active:
        entry["status"] = "ocr_running"
    elif not st["pending"]:
        entry["status"] = "parsed"
    elif st["ocr"]:
        entry["status"] = "partial"
    else:
        entry["status"] = "needs_ocr"
    entry["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    return True


def remerge_after_scan(root: str, index: dict, material_ids) -> None:
    """Materials._scan 重新生成文本后调用（已持锁）：把已有的识别结果合并回去（T5 第二轮复核 B 的那条）。"""
    wanted = set(material_ids)
    for m in index["materials"]:
        if m["material_id"] in wanted:
            try:
                merge_entry(root, m)
            except Exception as e:  # noqa: BLE001 合并失败不让扫描失败；文本保持解析结果，下次完成任务时再合并
                logs.event("ocr", "remerge", status="fail", error=type(e).__name__)
