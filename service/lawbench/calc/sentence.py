"""刑期计算（Spec 13.4；工具 case_calc_sentence，契约 tools/case_calc_sentence.schema.json）。

纯日期计算，不调用模型。规则表在本文件（RULES），每条带一句依据文字，返回在 basis / milestones[].basis 里；
文字由责任律师核对后定稿，未核对前每条末尾带"（待律师核实）"。规则表另抄一份在 docs\\plan\\evidence\\T24\\rules.md。

Spec 13.4 没写明、本卡的取法（T1 交付说明第 6 节 a–f；N4 待律师确认，未确认前照此计算）：
(a) 给了判决执行之日时，执行满二分之一的日期与止日一样扣折抵天数。
(b) 按天折半的"起止之间的总天数"含两端：起 至 (起 + 刑期 − 1 日)，节点 = 起 + ⌈总天数 / 2⌉ − 1 日。
(c) custody_days 是各段（含指定居所监视居住）日期并集的天数；折抵按各段的种类分别算比例再相加。
    同一天既在羁押段又在指定居所监视居住段时按羁押算（只算一次）。
(d) 加月只在"加完的日期不存在"时对齐到当月最后一天；原日期是月末的不追月末（2-28 加 1 个月为 3-28）。
(e) 无期徒刑不算起止、不算节点，折抵天数记 0。
(f) 没给判决执行之日、羁押连续时，起 = 羁押首日；羁押按 1 日折 1 日以外的比例折抵的（管制羁押 1 日折 2 日、
    指定居所监视居住 2 日折 1 日等），止日与节点再减"折抵天数 − 羁押天数"（为负即延后）。
    "连续"指各段的并集是一整段（后一段的起日不晚于前一段止日的次日，含首尾相接与重叠）。
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from ..errors import ApiError

PENDING = "（待律师核实）"
DETENTION = ("刑事拘留", "逮捕", "其他")      # 羁押
RESIDENCE = "指定居所监视居住"

# 规则表：每条 (依据文字)。文字末尾的"（待律师核实）"在律师核对定稿后去掉。
RULES = {
    "offset_管制_羁押": "管制判决执行以前先行羁押的，羁押一日折抵刑期二日" + PENDING,
    "offset_拘役_羁押": "拘役判决执行以前先行羁押的，羁押一日折抵刑期一日" + PENDING,
    "offset_有期徒刑_羁押": "有期徒刑判决执行以前先行羁押的，羁押一日折抵刑期一日" + PENDING,
    "offset_管制_指居": "指定居所监视居住的期限应当折抵刑期：被判处管制的，监视居住一日折抵刑期一日" + PENDING,
    "offset_拘役_指居": "指定居所监视居住的期限应当折抵刑期：被判处拘役的，监视居住二日折抵刑期一日" + PENDING,
    "offset_有期徒刑_指居": "指定居所监视居住的期限应当折抵刑期：被判处有期徒刑的，监视居住二日折抵刑期一日" + PENDING,
    "half_有期徒刑": "有期徒刑执行原判刑期二分之一以上可提请假释" + PENDING,
    "half_管制": "管制减刑以后实际执行的刑期不能少于原判刑期的二分之一" + PENDING,
    "half_拘役": "拘役减刑以后实际执行的刑期不能少于原判刑期的二分之一" + PENDING,
}
# 羁押 1 日折抵几日：(分子, 分母)
RATIO = {
    ("管制", "羁押"): (2, 1), ("拘役", "羁押"): (1, 1), ("有期徒刑", "羁押"): (1, 1),
    ("管制", "指居"): (1, 1), ("拘役", "指居"): (1, 2), ("有期徒刑", "指居"): (1, 2),
}

NOTE_LIFE = "无期徒刑的减刑、假释节点按实际执行年限计算，请律师判断"
NOTE_LIFE_OFFSET = "无期徒刑不计算折抵天数"
NOTE_GAP = "羁押期间不连续，请提供判决执行之日"
NOTE_NO_START = "没有判决执行之日，也没有先行羁押期间，无法计算刑期起止，请提供判决执行之日"
NOTE_BY_DAY = "刑期不是偶数个整月，执行满二分之一按天折半（起止之间含两端的总天数除以 2，向上取整）"
NOTE_REMAINDER = "指定居所监视居住有 {n} 日不足折抵刑期 1 日，不计"
NOTE_OTHER = "羁押种类为“其他”的期间按羁押折抵，请律师核实"
NOTE_OVERLAP = "各段羁押期间有重叠，重叠的日子只算一次"
NOTE_ADJUST = "没有判决执行之日，起日取羁押首日；因折抵比例不是 1 日折 1 日，止日与节点按折抵天数与羁押天数之差调整"
NOTE_SERVED = "折抵天数超过刑期，算出的止日早于起日，刑期可能已执行完毕，请律师核实"


def add_months(d: date, n: int) -> date:
    """按日历月加；加完的日期不存在时对齐到当月最后一天（取法 d）。"""
    y, m = divmod(d.month - 1 + n, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def add_term(d: date, years: int, months: int) -> date:
    """先加年、再加月（Spec 13.4）。"""
    return add_months(add_months(d, years * 12), months)


def _merge(spans: list[tuple[date, date]]) -> list[tuple[date, date]]:
    """日期段并集，按起日排序；首尾相接（后一段起日 = 前一段止日次日）的合成一段。"""
    out: list[list[date]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + timedelta(days=1):
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _days(spans: list[tuple[date, date]]) -> int:
    return sum((b - a).days + 1 for a, b in spans)


def calc(a: dict) -> dict:
    penalty = a["penalty"]
    years, months = a.get("years") or 0, a.get("months") or 0
    es = date.fromisoformat(a["execution_start"]) if a.get("execution_start") else None
    segs = []
    for c in a["custody"]:
        f, t = date.fromisoformat(c["from"]), date.fromisoformat(c["to"])
        if t < f:
            raise ApiError("INVALID_ARGUMENT", "custody_reversed")
        segs.append((f, t, c["kind"]))
    if penalty != "无期徒刑" and years * 12 + months == 0:
        raise ApiError("INVALID_ARGUMENT", "term_missing")

    basis: list[str] = []
    notes: list[str] = []
    union = _merge([(f, t) for f, t, _ in segs])
    custody_days = _days(union)
    if custody_days < sum((t - f).days + 1 for f, t, _ in segs):
        notes.append(NOTE_OVERLAP)
    if any(k == "其他" for _, _, k in segs):
        notes.append(NOTE_OTHER)

    if penalty == "无期徒刑":
        notes += [NOTE_LIFE, NOTE_LIFE_OFFSET]
        return {"start": None, "end": None, "offset_days": 0, "custody_days": custody_days, "milestones": [],
                "basis": basis, "notes": notes}

    # 折抵：羁押的日子与指定居所监视居住的日子分开数（同一天两种都有按羁押算），各按比例
    detention = _merge([(f, t) for f, t, k in segs if k in DETENTION])
    residence_all = _merge([(f, t) for f, t, k in segs if k == RESIDENCE])
    d_days = _days(detention)
    r_days = _days(_merge(residence_all + detention)) - d_days
    offset = 0
    for group, n in (("羁押", d_days), ("指居", r_days)):
        if n == 0:
            continue
        num, den = RATIO[(penalty, group)]
        offset += n * num // den
        basis.append(RULES[f"offset_{penalty}_{group}"])
        if n * num % den:
            notes.append(NOTE_REMAINDER.format(n=n * num % den))

    # 起止
    if es is not None:
        start, shift = es, offset
    elif union and len(union) == 1:
        start, shift = union[0][0], offset - custody_days
        if shift:
            notes.append(NOTE_ADJUST)
    else:
        notes.append(NOTE_GAP if union else NOTE_NO_START)
        return {"start": None, "end": None, "offset_days": offset, "custody_days": custody_days, "milestones": [],
                "basis": basis, "notes": notes}
    full_end = add_term(start, years, months) - timedelta(days=1)
    end = full_end - timedelta(days=shift)
    if end < start:
        notes.append(NOTE_SERVED)

    # 执行满二分之一：偶数个整月按月折半，否则按天折半（取法 a、b）
    total = years * 12 + months
    if total % 2 == 0:
        half = add_term(start, 0, total // 2) - timedelta(days=1)
    else:
        n = (full_end - start).days + 1
        half = start + timedelta(days=-(-n // 2) - 1)
        notes.append(NOTE_BY_DAY)
    half -= timedelta(days=shift)
    milestones = [{"name": "执行满二分之一", "date": half.isoformat(), "basis": RULES[f"half_{penalty}"]}]
    return {"start": start.isoformat(), "end": end.isoformat(), "offset_days": offset, "custody_days": custody_days,
            "milestones": milestones, "basis": basis, "notes": notes}
