"""修订版 Word（Spec 12.2）：按修改清单用 lxml 直接改 OOXML，生成带修订和批注的 docx。

独立的库：输入原件 docx 的字节和修改清单，输出新 docx 的字节，不碰文件系统（将来要放到 395 时包一层接口即可）。

做法：
1. 每条先按 tools/edit_list._judge 判范围（与 case_save_edit_list 同一套规则、同一个段号数法）：表格、文本框、
   页眉页脚、跨越域代码或超链接、找不到、出现多次 → 不改，进"需人工修改"。
2. 范围内的：在该段里定位 find（按原文定位：本次已插入的文字不算、已删除的文字仍算），按字符位置拆 run，
   拆出的 run 都带原来的 w:rPr；被删的 run 包进 w:del、w:t 改 w:delText；新文字放进 w:ins 里的新 run，格式取
   相邻原 run。replace = del + ins；insert_after = find 之后 ins；delete = del。
3. 批注：commentRangeStart / commentRangeEnd 包住改动处，后跟批注引用；没有 comments.xml 时新建，并补关系文件和
   内容类型登记。
4. 原文已有修订（w:ins / w:del / w:moveFrom / w:moveTo）的整份拒绝（Revised）。
本次实际改动时还会遇到判范围时看不出的情况，也进"需人工修改"、不猜：与本清单前面某条改动的文字重叠；find 的
文字分属不同的上层结构（如一部分在内容控件里）。
"""
from __future__ import annotations

import copy
import io
import re
import zipfile
from datetime import datetime, timezone

from lxml import etree

from ..ingest import docx as dx
from ..tools import edit_list as el

W = dx.W
AUTHOR = "AI审查（待律师确认）"
INITIALS = "AI"
R_OVERLAP = "与本清单另一条修改的文字重叠"
R_STRUCTURE = "find 的文字分属不同的段内结构（如内容控件），无法安全修改"
R_BAD_CHAR = "修改文字或批注里有 Word 文件不能保存的控制字符"
R_IN_LINK = "插入点在超链接文字的末尾，插入的文字会成为链接的一部分"
_BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")

REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
COMMENTS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
COMMENTS_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def q(tag: str) -> str:
    return f"{{{W}}}{tag}"


_R, _RPR, _T, _DELTEXT = q("r"), q("rPr"), q("t"), q("delText")
_INS, _DEL = q("ins"), q("del")
_HYPERLINK = q("hyperlink")
_INSTR, _DELINSTR = q("instrText"), q("delInstrText")
_TEXTUAL = {dx._T: None, dx._TAB: "\t", dx._BR: " ", dx._CR: " "}   # 与 edit_list._para_chars 同口径：段内可见字符


class Revised(Exception):
    """原文已有修订痕迹：整份不生成。"""


# ---------------------------------------------------------------- 段内字符与 run

class _Slot:
    """段内一个可见字符：所在 run、run 里的子元素、子元素里的下标；touched = 在本次已删除的文字里。"""
    __slots__ = ("run", "child", "i", "touched")

    def __init__(self, run, child, i, touched):
        self.run, self.child, self.i, self.touched = run, child, i, touched


def _slots(p) -> list[_Slot]:
    """按原文的可见字符列出（edit_list._para_chars 同序）：跳过本次插入的 w:ins，本次删除的 w:del 里的字算在内。
    原文没有修订（已整份拒绝），所以段里的 w:ins / w:del 都是本次加的。"""
    out: list[_Slot] = []

    def walk(node, touched: bool) -> None:
        for ch in node:
            tag = ch.tag
            if not isinstance(tag, str):
                continue
            if tag == _INS:
                continue
            if tag == _DEL:
                walk(ch, True)
                continue
            if tag in dx._SKIP and tag != _DELTEXT:
                continue
            if tag == _R:
                for c in ch:
                    if c.tag in _TEXTUAL or c.tag == _DELTEXT:
                        n = len(c.text or "") if c.tag in (dx._T, _DELTEXT) else 1
                        out.extend(_Slot(ch, c, i, touched) for i in range(n))
                continue
            walk(ch, touched)

    walk(p, False)
    return out


def _split_run(run, child, i):
    """在 run 的 child 第 i 个字符之前切开：返回右半个 run（已插在原 run 之后）；切点在 run 开头时返回原 run。"""
    kids = [c for c in run if c.tag != _RPR]
    k = kids.index(child)
    if child.tag == dx._T and 0 < i < len(child.text or ""):
        tail = etree.Element(dx._T)
        tail.text = child.text[i:]
        tail.set(XML_SPACE, "preserve")
        child.text = child.text[:i]
        child.set(XML_SPACE, "preserve")
        child.addnext(tail)
        kids.insert(k + 1, tail)
        k += 1
    elif i != 0:                                   # 制表、换行是一个字符；i 只可能是 0
        raise AssertionError("bad split")
    if k == 0:
        return run
    right = etree.Element(_R, attrib=dict(run.attrib))
    rpr = run.find(_RPR)
    if rpr is not None:
        right.append(copy.deepcopy(rpr))
    for c in kids[k:]:
        right.append(c)                             # append 会把元素从原 run 里移走
    run.addnext(right)
    return right


def _isolate(p, start: int, end: int) -> list | None:
    """把原文 [start, end) 的字符拆成整 run，返回这些 run（文档顺序）；与已删除文字重叠返回 None。"""
    slots = _slots(p)
    if any(s.touched for s in slots[start:end]):
        return None
    if end < len(slots):
        s = slots[end]
        _split_run(s.run, s.child, s.i)
    s = _slots(p)[start]
    first = _split_run(s.run, s.child, s.i)
    slots = _slots(p)
    runs: list = []
    for s in slots[start:end]:
        if not runs or runs[-1] is not s.run:
            runs.append(s.run)
    assert runs[0] is first
    return runs


def _to_deleted(run) -> None:
    for c in run:
        if c.tag == dx._T:
            c.tag = _DELTEXT
            c.set(XML_SPACE, "preserve")
        elif c.tag == _INSTR:
            c.tag = _DELINSTR


def _new_run(like, text: str):
    r = etree.Element(_R)
    rpr = like.find(_RPR)
    if rpr is not None:
        r.append(copy.deepcopy(rpr))
    parts = text.split("\n")
    for n, part in enumerate(parts):
        if n:
            etree.SubElement(r, dx._BR)
        if part:
            t = etree.SubElement(r, dx._T)
            t.text = part
            t.set(XML_SPACE, "preserve")
    return r


class _Ids:
    def __init__(self, start: int):
        self.n = start

    def __call__(self) -> str:
        self.n += 1
        return str(self.n)


def _max_id(*roots) -> int:
    best = 0
    for root in roots:
        if root is None:
            continue
        for e in root.iter():
            v = e.get(q("id")) if isinstance(e.tag, str) else None
            if v is not None and v.lstrip("-").isdigit():
                best = max(best, int(v))
    return best


# ---------------------------------------------------------------- 一条修改

def _slot_text(slots: list[_Slot]) -> str:
    return "".join(s.child.text[s.i] if s.child.tag in (dx._T, _DELTEXT) else _TEXTUAL[s.child.tag]
                   for s in slots)


def _apply(p, edit: dict, original: str, rev_id, cmt_id: str, date: str) -> str | None:
    """在段落 p 里做这条修改；成功返回 None，做不了返回原因（段落恢复原样）。
    original：判范围时该段的原文（edit_list._para_chars）；按 run 数出来的原文与它不一致（如注音等少见结构）就不改。"""
    if _slot_text(_slots(p)) != original:
        return R_STRUCTURE
    find = edit["find"]
    start = original.index(find)          # 判范围时已核过恰好出现一次
    end = start + len(find)
    backup = copy.deepcopy(p)
    runs = _isolate(p, start, end)
    if runs is None:
        p.getparent().replace(p, backup)
        return R_OVERLAP
    parent = runs[0].getparent()
    if any(r.getparent() is not parent for r in runs):
        p.getparent().replace(p, backup)
        return R_STRUCTURE
    if edit["action"] == "insert_after" and parent.tag == _HYPERLINK and runs[-1].getnext() is None:
        p.getparent().replace(p, backup)                # 复核 NOTE-2：选"进需人工修改"，不猜放在链接里还是外
        return R_IN_LINK
    attrs = {q("author"): AUTHOR, q("date"): date}
    first, last = runs[0], runs[-1]
    anchor_start, anchor_end = first, last
    action = edit["action"]
    if action in ("replace", "delete"):
        d = etree.Element(_DEL, attrib={q("id"): rev_id(), **attrs})
        first.addprevious(d)
        for r in runs:
            _to_deleted(r)
            d.append(r)
        anchor_start = anchor_end = d
    if action in ("replace", "insert_after"):
        ins = etree.Element(_INS, attrib={q("id"): rev_id(), **attrs})
        ins.append(_new_run(last, edit["text"]))
        anchor_end.addnext(ins)
        anchor_end = ins
    cs = etree.Element(q("commentRangeStart"), attrib={q("id"): cmt_id})
    ce = etree.Element(q("commentRangeEnd"), attrib={q("id"): cmt_id})
    anchor_start.addprevious(cs)
    anchor_end.addnext(ce)
    ref = etree.Element(_R)
    etree.SubElement(ref, q("commentReference"), attrib={q("id"): cmt_id})
    ce.addnext(ref)
    return None


# ---------------------------------------------------------------- 批注与包

def _comment(cid: str, text: str, date: str):
    c = etree.Element(q("comment"), attrib={q("id"): cid, q("author"): AUTHOR, q("date"): date,
                                            q("initials"): INITIALS})
    for n, line in enumerate(text.split("\n")):
        p = etree.SubElement(c, q("p"))
        if n == 0:
            etree.SubElement(etree.SubElement(p, _R), q("annotationRef"))
        r = etree.SubElement(p, _R)
        t = etree.SubElement(r, _T)
        t.text = line
        t.set(XML_SPACE, "preserve")
    return c


def _xml(root) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _doc_rels_name() -> str:
    return "word/_rels/document.xml.rels"


def _comments_part(z: zipfile.ZipFile) -> str | None:
    """document.xml 关系里登记的批注部件（不一定叫 word/comments.xml）。"""
    if _doc_rels_name() not in z.namelist():
        return None
    rels = dx._parse_xml(z.read(_doc_rels_name()))
    for r in rels:
        if r.get("Type") == COMMENTS_REL and r.get("TargetMode") != "External":
            target = r.get("Target", "")
            name = target.lstrip("/") if target.startswith("/") else "word/" + target
            if name in z.namelist():
                return name
    return None


def generate(data: bytes, edits: list[dict], now: datetime | None = None) -> tuple[bytes, list[int], list[dict]]:
    """返回 (新 docx 字节, 已生成修订的条目 id, 需人工修改 [{id, reason}])。原文含修订抛 Revised。"""
    date = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = [e["id"] for e in edits]
    if len(ids) != len(set(ids)):                       # 后一条会盖掉前一条的判定（T15 复核 P3-3）
        raise ValueError("duplicate_edit_id")
    zin = zipfile.ZipFile(io.BytesIO(data))
    root = dx._parse_xml(zin.read("word/document.xml"))
    if el.has_revisions(zin):                           # 正文、页眉页脚、脚注、格式修订都算（P2-2）
        raise Revised()
    body = root.find("w:body", dx.NS)
    items = [(k, e) for k, e in dx._body_items(body)
             if (dx._text(e).strip() if k == "p" else dx._table(e))]
    has_extras = bool(dx._extras(zin))
    cname = _comments_part(zin)
    comments = dx._parse_xml(zin.read(cname)) if cname else etree.Element(q("comments"), nsmap={"w": W})
    rev_id = _Ids(_max_id(root))
    cmt_next = _Ids(max(_max_id(comments), -1))

    # 先全部按原文判范围、记下各段原文（之后的改动不影响段号，也不影响后面条目的判定）
    reasons = {e["id"]: el._judge(e, items, has_extras) for e in edits}
    original = {e["para"]: "".join(c for c, _ in el._para_chars(items[e["para"] - 1][1]))
                for e in edits if reasons[e["id"]] is None}
    applied: list[int] = []
    manual: list[dict] = []
    for e in edits:
        reason = reasons[e["id"]]
        if reason is None and (_BAD_XML.search(e.get("text") or "") or _BAD_XML.search(e["comment"])):
            reason = R_BAD_CHAR                             # 写不进 XML 的控制字符：不改、不猜（P3-2）
        if reason is None:
            p = items[e["para"] - 1][1]
            cid = cmt_next()
            reason = _apply(p, e, original[e["para"]], rev_id, cid, date)
            if reason is None:
                comments.append(_comment(cid, e["comment"], date))
                applied.append(e["id"])
                continue
            cmt_next.n -= 1
            items = [(k, x) for k, x in dx._body_items(body)
                     if (dx._text(x).strip() if k == "p" else dx._table(x))]   # 回滚时换了段落元素
        manual.append({"id": e["id"], "reason": reason})

    out = {"word/document.xml": _xml(root)}
    if applied:
        if cname is None:
            cname = "word/comments.xml"
            rels = dx._parse_xml(zin.read(_doc_rels_name()))
            used = {r.get("Id") for r in rels}
            n = 1
            while f"rId{n}" in used:
                n += 1
            etree.SubElement(rels, f"{{{REL_NS}}}Relationship",
                             attrib={"Id": f"rId{n}", "Type": COMMENTS_REL, "Target": "comments.xml"})
            out[_doc_rels_name()] = _xml(rels)
            ct = dx._parse_xml(zin.read("[Content_Types].xml"))
            if not any(o.get("PartName") == "/word/comments.xml" for o in ct):
                etree.SubElement(ct, f"{{{CT_NS}}}Override",
                                 attrib={"PartName": "/word/comments.xml", "ContentType": COMMENTS_CT})
            out["[Content_Types].xml"] = _xml(ct)
        out[cname] = _xml(comments)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            payload = out.pop(info.filename, None)
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = info.external_attr
            zout.writestr(zi, payload if payload is not None else zin.read(info.filename))
        for name, payload in out.items():          # 新建的 comments.xml
            zout.writestr(name, payload)
    return buf.getvalue(), applied, manual
