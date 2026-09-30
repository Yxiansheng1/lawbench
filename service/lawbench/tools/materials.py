"""case_list_materials、case_read_material、case_search。"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from ..case import texts
from ..errors import ApiError
from . import ToolContext

MAX_CHARS = 8000
SNIPPET = 40
UNIT_WORD = {"page": "页", "para": "段", "line": "行"}


# ---------- case_list_materials ----------

def list_materials(ctx: ToolContext, a: dict) -> dict:
    index = ctx.index()
    stale = ctx.materials.stale_ocr(ctx.root, index)
    rows = [{"material_id": m["material_id"], "name": m["name"], "type": m["type"], "status": m["status"],
             "unit": m["unit"], "unit_count": m["unit_count"], "is_ocr": m["is_ocr"],
             "stale_ocr": m["material_id"] in stale, "error": m["error"]} for m in index["materials"]]
    return {"materials": rows, "total": len(rows)}


# ---------- case_read_material ----------

def _units_of(ctx: ToolContext, m: dict) -> list[texts.Unit]:
    if m["status"] == "failed":
        raise ApiError("MATERIAL_NOT_READY", "failed")
    units = texts.split_units(texts.read_text(ctx.root, m), m["unit"])
    if not units or not texts.readable(units):
        raise ApiError("MATERIAL_NOT_READY", "needs_ocr")
    return units


def read_material(ctx: ToolContext, a: dict) -> dict:
    m = ctx.material_by_name(a["name"])
    units = _units_of(ctx, m)
    start = a.get("start", 1)
    limit = a.get("max_chars", MAX_CHARS)
    rest = [u for u in units if u.no >= start]
    if not rest:
        raise ApiError("INVALID_ARGUMENT", "start_out_of_range")
    picked: list[texts.Unit] = []
    for u in rest:
        if picked and len(texts.render(picked + [u], m["unit"])) > limit:
            break
        picked.append(u)
    text = texts.render(picked, m["unit"])
    truncated = len(text) > limit
    if truncated:  # 一个单元就超过上限：截断，下次从下一个单元读
        tail = "\n…（本单元过长，已截断）"
        text = text[:limit - len(tail)] + tail
    nxt = next((u.no for u in rest if u.no > picked[-1].no), None)
    if not truncated:  # 截断的单元没读全，不记进 reads.json，材料归入"没读全"（P1-1；读余下部分要改契约，N31）
        ctx.tasks.add_read(ctx.root, ctx.task["task_id"], {
            "material_id": m["material_id"], "material_version": m["sha256"], "unit": m["unit"],
            "from": picked[0].no, "to": picked[-1].no,
            "at": datetime.now().astimezone().isoformat(timespec="seconds")})
    return {"name": m["name"], "material_id": m["material_id"], "unit": m["unit"], "start": picked[0].no,
            "end": picked[-1].no, "text": text, "has_more": nxt is not None, "next_start": nxt}


# ---------- case_search（本卡为逐单元扫描的临时实现；T9 换成 FTS5 与查询扩展） ----------

def normalize(s: str) -> str:
    """全角转半角、去掉数字中的千分位逗号、统一空白（Spec 第 11 节）。"""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"(?<=\d),(?=\d{3})", "", s)
    return re.sub(r"\s+", " ", s)


def _col_letter(i: int) -> str:
    out = ""
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def _citation(m: dict, u: texts.Unit, qn: str) -> str:
    if m["unit"] == "cell":
        cells = [c.strip() for c in u.text.strip().strip("|").split("|")]
        col = next((i for i, c in enumerate(cells[1:], 1) if qn in normalize(c)), 1)
        return f"〔{m['name']} {u.sheet}!{_col_letter(col)}{u.row}〕"
    return f"〔{m['name']} 第{u.no}{UNIT_WORD[m['unit']]}〕"


def search(ctx: ToolContext, a: dict) -> dict:
    qn = normalize(a["query"]).strip()
    if not qn:
        raise ApiError("INVALID_ARGUMENT", "empty_query")
    max_hits = a.get("max_hits", 20)
    hits: list[dict] = []
    total = 0
    for m in ctx.index()["materials"]:
        if m["status"] == "failed":
            continue
        try:
            units = texts.split_units(texts.read_text(ctx.root, m), m["unit"])
        except ApiError:
            continue
        for u in units:
            tn = normalize(u.text)
            pos = tn.find(qn)
            if pos < 0:
                continue
            total += 1
            if len(hits) < max_hits:
                snippet = tn[max(0, pos - SNIPPET):pos + len(qn) + SNIPPET]
                hits.append({"name": m["name"], "material_id": m["material_id"], "citation": _citation(m, u, qn),
                             "snippet": snippet, "is_ocr": u.is_ocr, "match": "exact"})
    return {"hits": hits, "total": total, "truncated": total > len(hits)}
