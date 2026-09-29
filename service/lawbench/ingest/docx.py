"""docx：lxml 直接读 document.xml（Spec 5.2）。

- 段 = 正文中非空段落的顺序号，从 1 开始；表格整体算一段，内部转成 md 表格。
- 修订：保留 w:ins / w:moveTo 的内容，去掉 w:del / w:moveFrom 的内容；有修订时 note 为"含修订，已按修订后文本"。
- 页眉页脚、脚注、尾注附在文末，另成一段。
"""
from __future__ import annotations

import pathlib
import zipfile

from lxml import etree

from . import Block, Parsed, ParseError
from .detect import is_ole, ole_encrypted

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
_P, _TBL, _SDT, _R, _T, _TAB, _BR, _CR = (f"{{{W}}}{t}" for t in ("p", "tbl", "sdt", "r", "t", "tab", "br", "cr"))
_SKIP = {f"{{{W}}}{t}" for t in ("del", "moveFrom", "delText", "instrText", "delInstrText")}
_REVISION = {f"{{{W}}}{t}" for t in ("ins", "del", "moveFrom", "moveTo")}
NOTE_REVISED = "含修订，已按修订后文本"


def _text(el) -> str:
    """段落或单元格内的文字；跳过已删除内容和域代码。"""
    out: list[str] = []

    def walk(node) -> None:
        for ch in node:
            tag = ch.tag
            if not isinstance(tag, str) or tag in _SKIP:
                continue
            if tag == _T:
                out.append(ch.text or "")
            elif tag == _TAB:
                out.append("\t")
            elif tag in (_BR, _CR):
                out.append(" ")
            elif tag == _P and out and node.tag != _P:
                out.append(" ")
                walk(ch)
            else:
                walk(ch)

    walk(el)
    return "".join(out)


def _cell(tc) -> str:
    paras = [_text(p).strip() for p in tc.iter(_P)]
    return "<br>".join(p for p in paras if p).replace("|", "\\|")


def _table(tbl) -> str:
    rows: list[list[str]] = []
    for tr in tbl.iterfind("w:tr", NS):
        rows.append([_cell(tc) for tc in tr.iterfind("w:tc", NS)])
    rows = [r for r in rows if r]
    if not any(c for r in rows for c in r):
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _body_items(body):
    """按文档顺序给出正文的段落和表格（内容控件 w:sdt 展开）。"""
    for ch in body:
        if ch.tag == _P:
            yield "p", ch
        elif ch.tag == _TBL:
            yield "tbl", ch
        elif ch.tag == _SDT:
            content = ch.find("w:sdtContent", NS)
            if content is not None:
                yield from _body_items(content)


def _parse_xml(data: bytes):
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    return etree.fromstring(data, parser)


def _extras(z: zipfile.ZipFile) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    names = sorted(z.namelist())
    for prefix, label in (("word/header", "页眉"), ("word/footer", "页脚")):
        for n in names:
            if n.startswith(prefix) and n.endswith(".xml"):
                root = _parse_xml(z.read(n))
                t = " ".join(s for s in (_text(p).strip() for p in root.iter(_P)) if s)
                if t and (label, t) not in seen:
                    seen.add((label, t))
                    lines.append(f"{label}：{t}")
    for part, label, tag in (("word/footnotes.xml", "脚注", "footnote"), ("word/endnotes.xml", "尾注", "endnote")):
        if part in names:
            root = _parse_xml(z.read(part))
            for note in root.iterfind(f"w:{tag}", NS):
                if note.get(f"{{{W}}}type") in ("separator", "continuationSeparator", "continuationNotice"):
                    continue
                t = " ".join(s for s in (_text(p).strip() for p in note.iter(_P)) if s)
                if t:
                    lines.append(f"{label}{note.get(f'{{{W}}}id')}：{t}")
    return lines


def parse(path: pathlib.Path, note: str | None = None) -> Parsed:
    if is_ole(path):
        raise ParseError("encrypted" if ole_encrypted(path) else "corrupt")
    try:
        with zipfile.ZipFile(path) as z:
            root = _parse_xml(z.read("word/document.xml"))
            extras = _extras(z)
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError, OSError):
        raise ParseError("corrupt")
    body = root.find("w:body", NS)
    if body is None:
        raise ParseError("corrupt")
    revised = any(isinstance(el.tag, str) and el.tag in _REVISION for el in root.iter())
    out = Parsed(unit="para", unit_count=0, count_word="段")
    for kind, el in _body_items(body):
        text = _text(el).strip() if kind == "p" else _table(el)
        if not text:
            continue
        out.blocks.append(Block(f"第{len(out.blocks) + 1}段", text))
    if extras:
        out.blocks.append(Block(f"第{len(out.blocks) + 1}段", "\n".join(extras)))
    out.unit_count = len(out.blocks)
    out.note = NOTE_REVISED if revised else note
    return out
