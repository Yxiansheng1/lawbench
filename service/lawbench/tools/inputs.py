"""case_read_input、case_read_wiki。"""
from __future__ import annotations

from datetime import datetime

from ..case import context, gate
from ..errors import ApiError
from . import ToolContext

MAX_CHARS = 8000
WIKI_SECTIONS = {"概览", "当事人", "时间线", "材料清单", "争议焦点"}


def _page_lines(lines: list[str], start: int, limit: int) -> tuple[str, int, bool]:
    """从第 start 行起取整行，不超过 limit 字；返回 (文本, 结束行号, 是否还有)。"""
    out: list[str] = []
    size = 0
    end = start - 1
    for i in range(start - 1, len(lines)):
        add = len(lines[i]) + (1 if out else 0)
        if out and size + add > limit:
            break
        out.append(lines[i])
        size += add
        end = i + 1
    text = "\n".join(out)
    if len(text) > limit:
        tail = "\n…（本行过长，已截断）"
        text = text[:limit - len(tail)] + tail
    return text, end, end < len(lines)


def read_input(ctx: ToolContext, a: dict) -> dict:
    refs = ctx.task["inputs"]
    if not 1 <= a["index"] <= len(refs):
        raise ApiError("INVALID_ARGUMENT", "input_index")
    ref = refs[a["index"] - 1]
    lines = ctx.tasks.read_input(ctx.root, ref).split("\n")
    start = a.get("start", 1)
    if start > len(lines):
        raise ApiError("INVALID_ARGUMENT", "start_out_of_range")
    text, end, more = _page_lines(lines, start, a.get("max_chars", MAX_CHARS))
    return {"index": ref["index"], "title": ref["title"], "start": start, "end": end, "text": text,
            "has_more": more, "next_start": end + 1 if more else None}


def read_wiki(ctx: ToolContext, a: dict) -> dict:
    section = a["section"]
    index = ctx.index()
    card = context.load_card(ctx.root)
    stale = bool(context.changed_since_card(card, index))
    if section == "卡片":
        text = context.build_l0(ctx.root, index)
        return {"section": section, "text": text[:MAX_CHARS], "updated_at": card["generated_at"] if card else None,
                "stale": stale}
    if section == "材料摘要":
        if not a.get("name"):
            raise ApiError("INVALID_ARGUMENT", "name_required")
        rel = f"工作区/wiki/材料/{ctx.material_by_name(a['name'])['material_id']}.md"
    elif section in WIKI_SECTIONS:
        rel = f"工作区/wiki/案件/{section}.md"
    else:  # 契约的枚举已拦住，这里防御
        raise ApiError("INVALID_ARGUMENT", "section")
    p = gate.resolve_internal(ctx.root, rel, op="read_wiki")  # 路径由服务端按固定规则拼出
    if not p.is_file():
        return {"section": section, "text": "还没有生成 wiki（这一节不存在）。", "updated_at": None, "stale": stale}
    text = p.read_text(encoding="utf-8")
    if len(text) > MAX_CHARS:
        tail = "\n…（本节过长，已截断）"
        text = text[:MAX_CHARS - len(tail)] + tail
    updated = datetime.fromtimestamp(p.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    return {"section": section, "text": text, "updated_at": updated, "stale": stale}
