"""case_save_edit_list（Spec 12.2；契约 tools/case_save_edit_list）。

按"范围外的情况"判定每条修改（不修改该条，放入需人工修改清单）：
- 目标段落在表格、文本框、页眉页脚中；
- find 跨越域代码或超链接；
- find 找不到或出现多次；
- 原文已有修订痕迹：整份不生成修订版，全部条目都算范围外。
段号与材料文本一致（ingest/docx.py 的数法：正文非空段落，表格整体算一段，页眉页脚另成最后一段）。
"""
from __future__ import annotations

import json
import zipfile

from lxml import etree

from .. import contracts
from ..case import gate
from ..errors import ApiError
from ..ingest import docx as dx
from . import ToolContext

W = dx.W
_HYPERLINK = f"{{{W}}}hyperlink"
_FLDSIMPLE = f"{{{W}}}fldSimple"
_FLDCHAR = f"{{{W}}}fldChar"
_TXBX = f"{{{W}}}txbxContent"

R_REVISED = "原文件含未处理的修订，请先接受或拒绝后再生成"
R_TABLE = "目标段落在表格中"
R_TEXTBOX = "目标段落在文本框中"
R_HEADER = "目标段落在页眉页脚中"
R_NOT_FOUND = "find 在该段中找不到"
R_MULTI = "find 在该段中出现多次"
R_CROSS = "find 跨越域代码或超链接"
R_NO_PARA = "没有这个段号"
R_NO_TEXT = "replace / insert_after 缺少新文字"
R_NOT_DOCX = "原件不是 docx，不能生成修订版"


def _para_chars(p) -> list[tuple[str, bool]]:
    """段落里的可见文字，逐字标记是否在超链接或域结果里（跳过已删除内容和域指令，同 docx._text）。"""
    out: list[tuple[str, bool]] = []
    depth = {"fld": 0}

    def walk(node, special: bool) -> None:
        for ch in node:
            tag = ch.tag
            if not isinstance(tag, str) or tag in dx._SKIP:
                continue
            if tag == _FLDCHAR:
                kind = ch.get(f"{{{W}}}fldCharType")
                if kind == "begin":
                    depth["fld"] += 1
                elif kind == "end" and depth["fld"]:
                    depth["fld"] -= 1
                continue
            inside = special or tag in (_HYPERLINK, _FLDSIMPLE) or depth["fld"] > 0
            if tag == dx._T:
                out.extend((c, inside) for c in (ch.text or ""))
            elif tag == dx._TAB:
                out.append(("\t", inside))
            elif tag in (dx._BR, dx._CR):
                out.append((" ", inside))
            else:
                walk(ch, inside)

    walk(p, False)
    return out


def _paragraphs(path) -> tuple[list, bool, bool]:
    """(按段号排列的正文元素列表, 是否含修订, 是否有页眉页脚段)。"""
    with zipfile.ZipFile(path) as z:
        root = dx._parse_xml(z.read("word/document.xml"))
        has_extras = bool(dx._extras(z))
    body = root.find("w:body", dx.NS)
    revised = any(isinstance(el.tag, str) and el.tag in dx._REVISION for el in root.iter())
    items = []
    for kind, el in dx._body_items(body):
        text = dx._text(el).strip() if kind == "p" else dx._table(el)
        if text:
            items.append((kind, el))
    return items, revised, has_extras


def _judge(edit: dict, items: list, has_extras: bool) -> str | None:
    if edit["action"] in ("replace", "insert_after") and not edit.get("text"):
        return R_NO_TEXT
    n = edit["para"]
    if has_extras and n == len(items) + 1:
        return R_HEADER
    if n > len(items):
        return R_NO_PARA
    kind, el = items[n - 1]
    if kind == "tbl":
        return R_TABLE
    if any(isinstance(x.tag, str) and x.tag == _TXBX for x in el.iter()):
        return R_TEXTBOX
    chars = _para_chars(el)
    full = "".join(c for c, _ in chars)
    # 材料文本里的段落去掉了首尾空白；find 按段内全文找
    count = full.count(edit["find"])
    if count == 0:
        return R_NOT_FOUND
    if count > 1:
        return R_MULTI
    pos = full.index(edit["find"])
    flags = {s for _, s in chars[pos:pos + len(edit["find"])]}
    if len(flags) > 1:
        return R_CROSS
    return None


def save_edit_list(ctx: ToolContext, a: dict) -> dict:
    m = ctx.material_by_name(a["name"])
    if m["type"] not in ("docx", "doc", "wps"):
        raise ApiError("INVALID_ARGUMENT", "not_word_material")
    ids = [e["id"] for e in a["edits"]]
    if len(ids) != len(set(ids)):
        raise ApiError("INVALID_ARGUMENT", "duplicate_edit_id")
    out: list[dict] = []
    if m["type"] != "docx":
        out = [{"id": e["id"], "reason": R_NOT_DOCX} for e in a["edits"]]
    else:
        src = gate.resolve_read(ctx.root, m["rel_path"], op="save_edit_list")
        try:
            items, revised, has_extras = _paragraphs(src)
        except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError, OSError):
            raise ApiError("MATERIAL_NOT_READY", "docx_unreadable")
        for e in a["edits"]:
            reason = R_REVISED if revised else _judge(e, items, has_extras)
            if reason:
                out.append({"id": e["id"], "reason": reason})
    safe = m["name"].replace("/", "_").replace("\\", "_")
    rel = ctx.tasks.rel(ctx.task["task_id"], f"修改清单/{safe}.json")
    contracts.validate("tools/case_save_edit_list.schema.json", "#/$defs/args", a)
    gate.write_bytes(ctx.root, rel, json.dumps(a, ensure_ascii=False, indent=2).encode("utf-8"), op="save_edit_list")
    return {"path": rel, "accepted": len(a["edits"]) - len(out), "out_of_scope": out}
