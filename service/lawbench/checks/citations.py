"""出处核对（由 wiki 测试的 check_citations.py 改成库函数；Spec 9.4；契约 $defs/problem、citation_check）。

输入一篇文本、材料集合（parse.MaterialSet）、成果类型 kind；输出 citation_check 和解析出的结构化出处。
只读材料文本与 index.json，不碰原件区；不写日志（调用方只记元数据）。

切分：逐行。行内每组相邻的出处（中间只隔空白和"；;、，,"）管它前面那段文字；表格行整行算一段；
引用块（> 开头）整行算一段，且整段按引语核。标题、表格分隔行、HTML 注释、代码块跳过。

七类（Spec 9.4）：
- A 疑似补全：所标位置原文是"8■,000.00""陈美■"这类识别不清的内容，文中写成了完整值。
- B 页码不对：值（金额、日期、引语）在所引材料里有，但不在所标位置。
- C 所引材料中找不到这个值。
- D 声明引用的材料里没有正文引用的材料：只在调用方给了 declared（wiki 头部 Raw 字段一类）时查；
  case_save_draft 不给、不查（裁决 1）。
- E 出处格式错误：不合契约正则、用【】写出处、材料名不存在、位置与材料的定位方式不合或超出范围。
- F 提示：含金额或日期但没带出处。
- G 评价性用语（引号内的原文不算）：excerpt 类必须修改；analysis、draft 类只提示（Spec 9.4 按成果类型）。

比较口径（裁决 3）：金额按数值比（60,000元 = 60000 = 6万元），日期按年月日比（原文只写月日时按月日比）；
文本先过 T9 的 normalize（全角半角、千分位、汉字间空白）。中文数字金额（"捌万元"）第一版不比对（裁决 4）。
〔推断〕〔未找到依据〕标注的那段不核 A、B、C。
"""
from __future__ import annotations

import json
import re
from decimal import Decimal

from ..search.normalize import normalize
from . import evidence
from .parse import Material, MaterialSet, find_cites, find_lenticular, loc_text, quote_spans

KINDS = ("excerpt", "analysis", "draft")
EXCERPT_MAX = 120

_DATE_RES = [
    re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"),
    re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日"),
    re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})(?!\d)"),
    re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})"),
    re.compile(r"(\d{4})年(\d{1,2})月"),
    re.compile(r"(?<![\d年])(\d{1,2})月(\d{1,2})日"),
    re.compile(r"(?<![\d年])(\d{1,2})月(?:初|中|底|份|下旬|上旬|中旬)"),
]
_NUM = re.compile(r"(\d+\.\d+|\d+)(万|亿|%)?")
_WRAPPED = re.compile(r"(?<=[\d,.，．])[ \t]*\r?\n[ \t]*(?=[\d,.，．])")
_OCR_NUM = re.compile(r"[\d■][\d,■]*■[\d,■]*(?:\.[\d■]+)?|[\d,]*\d■[\d,■.]*")
_OCR_NAME = re.compile(r"[一-鿿]*■[一-鿿]*")
_EVAL = re.compile(
    r"可信度|可信性|不可信|不可采信|中立性|佐证|足以证明|证明力|印证了|显然|明显(?:虚假|不实|矛盾)|"
    r"预谋|意在|企图|蓄意|说明其|表明其|证实其|可以认定|应当认定|构成犯罪|不构成|罪名成立|"
    r"从轻|从重|减轻处罚|量刑")
_SKIP_LINE = re.compile(r"^(#|<!--|\|[-:| ]+\|$)")
_FENCE = re.compile(r"^ {0,3}(```|~~~)")
_JOIN = " \t；;、，,"
_DOCNO = re.compile(r"〔[0-9]{4}〕第?[0-9]+号")


# ---------- 抽取值 ----------

def extract(text: str, source: bool = False) -> tuple[set, set]:
    """(dates, numbers)。date = (年或None, 月, 日或None)；number = 规范化的数值串（百分数前加 %）。

    数字中间的换行先去掉：PDF 取文字时可能在数字中间折行（criminal-01 起诉意见书第 4 页"12\\n6,500"）。
    只写年份的"1981年"记成"年1981"；source=True（材料原文一侧）时，原文里每个带年份的日期也记一个"年Y"，
    文中"1981年出生"就能核到原文的"1981年6月出生"。"""
    text = normalize(_WRAPPED.sub("", text))
    dates, spans = set(), []
    for i, rx in enumerate(_DATE_RES):
        for m in rx.finditer(text):
            if any(s <= m.start() < e for s, e in spans):
                continue
            g = [int(x) for x in m.groups()]
            if i <= 3:
                d = (g[0], g[1], g[2])
            elif i == 4:
                d = (g[0], g[1], None)
            elif i == 5:
                d = (None, g[0], g[1])
            else:
                d = (None, g[0], None)
            if not 1 <= d[1] <= 12 or (d[2] is not None and not 1 <= d[2] <= 31):
                continue
            spans.append((m.start(), m.end()))
            dates.add(d)
    masked = list(text)
    for s, e in spans:
        masked[s:e] = " " * (e - s)
    masked = "".join(masked)
    nums = set()
    for m in _NUM.finditer(masked):
        raw, unit = m.group(1), m.group(2)
        if "■" in masked[max(0, m.start() - 1):m.end() + 1]:
            continue                     # 识别不清的数不参与数值比对
        if m.start() and (masked[m.start() - 1].isdigit() or masked[m.start() - 1] == "."):
            continue
        if unit is None and "." not in raw and len(raw) < 4:
            continue                     # 小整数（页码、段号、人数）不查
        if unit is None and len(raw) == 4 and masked[m.end():m.end() + 1] == "年":
            nums.add(f"年{raw}")
            continue
        v = Decimal(raw) * {"万": 10000, "亿": 100000000}.get(unit, 1)   # Decimal：18 位证件号不丢尾数
        nums.add(("%" if unit == "%" else "") + format(v.normalize(), "f"))
    if source:
        nums |= {f"年{d[0]}" for d in dates if d[0] is not None}
    return dates, nums


def _date_match(w, r) -> bool:
    if w[1] != r[1]:
        return False
    if w[2] is not None and (r[2] is None or w[2] != r[2]):
        return False
    return not (w[0] is not None and r[0] is not None and w[0] != r[0])


def _has(values: tuple[set, set], kind: str, v) -> bool:
    dates, nums = values
    if kind == "num":
        return v in nums
    return any(_date_match(v, r) for r in dates)


def _fmt(kind: str, v) -> str:
    if kind == "num":
        return v
    y, m, d = v
    return (f"{y}年" if y else "") + f"{m}月" + (f"{d}日" if d else "")


def _ocr_num_matches(token: str, value: str) -> bool:
    t = re.sub(r"\.[0■]+$", "", token.replace(",", ""))
    v = value.split(".")[0] if value.replace(".", "").isdigit() else ""
    return bool(v) and len(t) == len(v) and all(a == b or a == "■" for a, b in zip(t, v))


# ---------- 切分 ----------

def _segments(line: str, cites: list) -> list[tuple[str, list]]:
    """一行 → [(事实文字, [出处])]。"""
    if line.lstrip().startswith("|"):
        rest = line
        for c in reversed(cites):
            rest = rest[:c.start] + " " + rest[c.end:]
        return [(rest, cites)]
    out, last, i = [], 0, 0
    while i < len(cites):
        group = [cites[i]]
        while i + 1 < len(cites) and not line[group[-1].end:cites[i + 1].start].strip(_JOIN):
            i += 1
            group.append(cites[i])
        out.append((line[last:group[0].start], group))
        last = group[-1].end
        i += 1
    tail = line[last:]
    if tail.strip(_JOIN + "。."):
        out.append((tail, []))
    return out


# ---------- 核对 ----------

class _Report:
    def __init__(self, kind: str):
        self.kind = kind
        self.problems: list[dict] = []
        self._seen: set = set()

    def add(self, cls: str, excerpt: str, citation: str | None, message: str) -> None:
        if cls == "F" or (cls == "G" and self.kind != "excerpt"):
            severity = "hint"
        else:
            severity = "must_fix"
        p = {"class": cls, "severity": severity, "excerpt": excerpt.strip()[:EXCERPT_MAX],
             "citation": citation, "message": message}
        key = (cls, p["excerpt"], citation, message)
        if key not in self._seen:
            self._seen.add(key)
            self.problems.append(p)


def check_text(text: str, materials: MaterialSet, kind: str = "analysis",
               declared: list[str] | None = None) -> tuple[dict, list[dict]]:
    """返回 (citation_check, citations)。citations 为结构化出处（契约 $defs/citation），按（材料编号、位置）去重。"""
    if kind not in KINDS:
        kind = "analysis"
    rep = _Report(kind)
    citations: dict[tuple, dict] = {}
    n_items = 0
    values_cache: dict[tuple, tuple] = {}
    in_fence = False

    def values_at(m: Material, loc: dict) -> tuple[set, set]:
        key = (m.name, json.dumps(loc, sort_keys=True))
        if key not in values_cache:
            values_cache[key] = extract(m.text_at(loc), source=True)
        return values_cache[key]

    for line in text.splitlines():
        s = line.strip()
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or not s or _SKIP_LINE.match(s):
            continue
        blockquote = s.startswith(">")
        body = s.lstrip(">").strip() if blockquote else line
        cites = find_cites(body)
        for raw in find_lenticular(body):
            rep.add("E", s, raw, f"出处要用六角括号〔〕，{raw} 用了【】（【】只用于占位和标签）")
        # G：评价性用语（出处、引号内的原文不算）
        bare = body
        for c in reversed(cites):
            bare = bare[:c.start] + " " * (c.end - c.start) + bare[c.end:]
        for a, b in reversed(quote_spans(bare)):
            bare = bare[:a] + " " * (b - a) + bare[b:]
        if "待律师核实" not in bare or _EVAL.search(bare.replace("待律师核实", "")):
            for m in _EVAL.finditer(bare):
                msg = (f"评价性用语“{m.group(0)}”：摘录类成果要忠实原文，删除或改为转述原文" if kind == "excerpt"
                       else f"评价性用语“{m.group(0)}”：判断性的句子请标明是分析意见并带出处")
                rep.add("G", s, None, msg)
        for fact, group in _segments(body, cites):
            _check_fact(rep, fact, group, materials, declared, blockquote and len(cites) == len(group),
                        values_at, citations)
            n_items += sum(len(c.items) for c in group if c.ok)
    must = sum(p["severity"] == "must_fix" for p in rep.problems)
    check = {"passed": must == 0, "problems": rep.problems,
             "stats": {"citations": n_items, "must_fix": must, "hints": len(rep.problems) - must}}
    return check, list(citations.values())


def _check_fact(rep: _Report, fact: str, group: list, materials: MaterialSet, declared, blockquote: bool,
                values_at, citations: dict) -> None:
    excerpt = fact.strip() or (group[0].raw if group else "")
    dates, nums = extract(_DOCNO.sub(" ", fact))      # 公文文号（〔2026〕417号）不是要核的数值
    facts = [("date", d) for d in sorted(dates, key=str)] + [("num", n) for n in sorted(nums)]
    if not group:
        if facts:
            rep.add("F", excerpt, None, "含金额或日期但没有出处，确认是否需要补出处")
        return
    inferred = False
    targets: list[tuple[Material, dict]] = []
    for c in group:
        if not c.ok:
            rep.add("E", excerpt, c.raw, f"出处格式不对：{c.raw}。写法为〔材料名 第N页〕〔材料名 工作表!B12〕等，"
                                         "每处都写材料名，多处用顿号分隔")
            continue
        if c.fixed:
            inferred = True
            continue
        for it in c.items:
            m = materials.get(it.name)
            if m is None:
                rep.add("E", excerpt, c.raw, f"没有叫“{it.name}”的材料，材料名以 case_list_materials 返回的为准")
                continue
            bad = m.check_loc(it.loc)
            if bad:
                rep.add("E", excerpt, c.raw, f"出处位置不对：{it.text()}，{bad}")
                continue
            if declared is not None and it.name not in declared:
                rep.add("D", excerpt, c.raw, f"正文引用了“{it.name}”，但声明引用的材料里没有它")
            key = (m.material_id, json.dumps(it.loc, sort_keys=True))
            citations.setdefault(key, {"material_id": m.material_id, "material_version": m.sha256,
                                       "name": m.name, "loc": it.loc})
            targets.append((m, it.loc))
    targets = [(m, loc) for m, loc in targets if m.units is not None]
    if not targets:
        return
    cite_text = "".join(c.raw for c in group)
    # A：疑似补全
    plain = normalize(fact)
    for m, loc in targets:
        orig = normalize(m.text_at(loc))
        for tok in set(_OCR_NUM.findall(orig)):
            if tok in plain:
                continue
            for k, v in facts:
                if k == "num" and _ocr_num_matches(tok, v):
                    rep.add("A", excerpt, cite_text, f"原文 {m.name} {loc_label(loc)} 是“{tok}”（识别不清），"
                                                     f"文中写成了 {v}；照抄原文并保留 ■")
        for tok in {x for x in _OCR_NAME.findall(orig) if len(x) >= 2}:
            if tok in plain:
                continue
            g = re.search(re.escape(tok).replace("■", "[一-鿿]"), plain)
            if g and g.group(0) != tok and g.group(0) not in orig:
                rep.add("A", excerpt, cite_text, f"原文 {m.name} {loc_label(loc)} 是“{tok}”（识别不清），"
                                                 f"文中写成了“{g.group(0)}”；照抄原文并保留 ■")
    if inferred:
        return
    # B / C：金额、日期
    for k, v in facts:
        if any(_has(values_at(m, loc), k, v) for m, loc in targets):
            continue
        elsewhere = _elsewhere(targets, lambda p: _has(extract(p.text, source=True), k, v))
        _b_or_c(rep, excerpt, cite_text, _fmt(k, v), targets, elsewhere)
    # B / C：引语
    for q in evidence.quotes_in(fact, blockquote):
        found, elsewhere = evidence.locate(q, targets)
        if not found:
            _b_or_c(rep, excerpt, cite_text, f"引语“{q[:30]}{'…' if len(q) > 30 else ''}”", targets, elsewhere)


def loc_label(loc: dict) -> str:
    return loc_text(loc)


def _elsewhere(targets, pred) -> list[str]:
    out, seen = [], set()
    for m, _ in targets:
        if m.name in seen:
            continue
        seen.add(m.name)
        out += [f"{m.name} {p.label}" for p in m.places if pred(p)]
    return out


def _b_or_c(rep: _Report, excerpt: str, cite_text: str, what: str, targets, elsewhere: list[str]) -> None:
    cited = "、".join(f"{m.name} {loc_label(loc)}" for m, loc in targets)
    if elsewhere:
        shown = "、".join(elsewhere[:5]) + ("等" if len(elsewhere) > 5 else "")
        rep.add("B", excerpt, cite_text, f"{what} 标的是 {cited}，实际在 {shown}")
    else:
        rep.add("C", excerpt, cite_text, f"{what} 在所引材料（{cited}）中找不到")
