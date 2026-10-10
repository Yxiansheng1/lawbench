"""case_list_materials、case_read_material（case_search 在 tools/search.py，T9）。"""
from __future__ import annotations

import dataclasses
from datetime import datetime

from ..case import texts
from ..errors import ApiError
from . import ToolContext

MAX_CHARS = 8000


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


TRUNC_TAIL = "\n…（本单元没读完，用 offset 接着读）"


def read_material(ctx: ToolContext, a: dict) -> dict:
    """offset（契约 1.2，N31）：单元本身超过 max_chars 时分段读同一单元，返回 next_offset；只有整个单元都读到了
    才记进 reads.json（P1-1）——分段读时按"从 0 起连续读到了第几个字"累计，读到单元末尾才算读完。"""
    if "more_names" in a:
        return _read_many(ctx, a)
    m = ctx.material_by_name(a["name"])
    units = _units_of(ctx, m)
    start = a.get("start", 1)
    offset = a.get("offset", 0)
    limit = a.get("max_chars", MAX_CHARS)
    rest = [u for u in units if u.no >= start]
    if not rest:
        raise ApiError("INVALID_ARGUMENT", "start_out_of_range")
    first = rest[0]
    nxt = next((u.no for u in rest[1:]), None)
    if offset or len(texts.render([first], m["unit"])) > limit:
        return _read_part(ctx, m, first, offset, limit, nxt)
    picked: list[texts.Unit] = []
    for u in rest:
        if picked and len(texts.render(picked + [u], m["unit"])) > limit:
            break
        picked.append(u)
    text = texts.render(picked, m["unit"])
    nxt = next((u.no for u in rest if u.no > picked[-1].no), None)
    _record(ctx, m, picked[0].no, picked[-1].no)
    return {"name": m["name"], "material_id": m["material_id"], "unit": m["unit"], "start": picked[0].no,
            "end": picked[-1].no, "text": text, "has_more": nxt is not None, "next_start": nxt, "next_offset": None}


SEP = "【材料：{name}】"


def _read_many(ctx: ToolContext, a: dict) -> dict:
    """一次读几份（契约 1.4 more_names）：name 和 more_names 各从头读，按顺序接起来，各份前面一行【材料：<材料名>】，
    合计不超过 max_chars。第一份照单份的规矩（读不了、不存在照常报错）；后面的放不下、读不了、不存在都不让整次失败，
    在 parts 里写明。只把整单元读到的记进 reads.json。"""
    if "start" in a or "offset" in a or a["name"] in a["more_names"]:
        raise ApiError("INVALID_ARGUMENT", "more_names_with_start")
    limit = a.get("max_chars", MAX_CHARS)
    first = ctx.material_by_name(a["name"])
    head = SEP.format(name=first["name"]) + "\n"
    r = read_material(ctx, {"name": a["name"], "max_chars": max(500, limit - len(head))})
    texts_out = [head + r["text"]]
    parts = [{"name": r["name"], "material_id": r["material_id"], "unit": r["unit"], "read": True, "start": r["start"],
              "end": r["end"], "has_more": r["has_more"], "next_start": r["next_start"], "error": None}]
    used = len(texts_out[0])
    for name in a["more_names"]:
        skip = {"name": name, "material_id": None, "unit": None, "read": False, "start": None, "end": None,
                "has_more": False, "next_start": None}
        try:
            m = ctx.material_by_name(name)
            units = _units_of(ctx, m)
        except ApiError as e:
            parts.append({**skip, "error": "没有这份材料" if e.code == "MATERIAL_NOT_FOUND" else "还不能读取（待识别或处理失败）"})
            continue
        skip.update(material_id=m["material_id"], unit=m["unit"])
        head = "\n\n" + SEP.format(name=m["name"]) + "\n"
        picked: list[texts.Unit] = []
        for u in units:
            if used + len(head) + len(texts.render(picked + [u], m["unit"])) > limit:
                break
            picked.append(u)
        if not picked:
            parts.append({**skip, "has_more": True, "next_start": units[0].no, "error": "放不下，请单独读这份"})
            continue
        body = head + texts.render(picked, m["unit"])
        texts_out.append(body)
        used += len(body)
        nxt = next((u.no for u in units if u.no > picked[-1].no), None)
        _record(ctx, m, picked[0].no, picked[-1].no)
        parts.append({**skip, "read": True, "start": picked[0].no, "end": picked[-1].no, "has_more": nxt is not None,
                      "next_start": nxt, "error": None})
    return {**r, "text": "".join(texts_out), "parts": parts}


def _record(ctx: ToolContext, m: dict, frm: int, to: int) -> None:
    ctx.tasks.add_read(ctx.root, ctx.task["task_id"], {
        "material_id": m["material_id"], "material_version": m["sha256"], "unit": m["unit"],
        "from": frm, "to": to, "at": datetime.now().astimezone().isoformat(timespec="seconds")})


def _read_part(ctx: ToolContext, m: dict, u: texts.Unit, offset: int, limit: int, nxt: int | None) -> dict:
    """读一个单元的一段：[offset, offset + 能放下的字数)。"""
    if offset > len(u.text) or (offset and offset == len(u.text)):
        raise ApiError("INVALID_ARGUMENT", "offset_out_of_range")
    overhead = len(texts.render([dataclasses.replace(u, text="x")], m["unit"])) - 1  # 位置标记、表头
    if overhead + len(TRUNC_TAIL) + 1 > limit:  # 表头本身就放不下（很宽的表格）：不带列名表头（F4）
        u = dataclasses.replace(u, header="")
        overhead = len(texts.render([dataclasses.replace(u, text="x")], m["unit"])) - 1
    room = max(1, limit - overhead - len(TRUNC_TAIL))
    end = min(len(u.text), offset + room)
    text = texts.render([dataclasses.replace(u, text=u.text[offset:end])], m["unit"])
    more = end < len(u.text)
    if more:
        text += TRUNC_TAIL
    if ctx.tasks.read_part(ctx.task["task_id"], m, u.no, offset, end, len(u.text)):
        _record(ctx, m, u.no, u.no)   # 这个单元从头到尾都读到了
    return {"name": m["name"], "material_id": m["material_id"], "unit": m["unit"], "start": u.no, "end": u.no,
            "text": text, "has_more": more or nxt is not None, "next_start": u.no if more else nxt,
            "next_offset": end if more else None}
