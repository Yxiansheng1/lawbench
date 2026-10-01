r"""T24 刑期计算红绿：逐条改坏即红、复原即绿。复用 T3 的 redgreen.py。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T24\redgreen_t24.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location(
    "redgreen_t3", pathlib.Path(__file__).resolve().parents[1] / "T3" / "redgreen.py")
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

R = "tests/test_sentence.py"
S = "calc/sentence.py"
rg.TITLE = "T24 红绿验证"
rg.MUTATIONS = [
    ("管制羁押 1 日折 2 日", S, [('("管制", "羁押"): (2, 1)', '("管制", "羁押"): (1, 1)')], R),
    ("指定居所监视居住：有期徒刑 2 日折 1 日", S, [('("有期徒刑", "指居"): (1, 2)', '("有期徒刑", "指居"): (1, 1)')], R),
    ("不足 1 日的部分写进 notes", S, [
        ("            notes.append(NOTE_REMAINDER.format(n=n * num % den))\n", "            pass\n")], R),
    ("羁押重叠只算一次", S, [("    custody_days = _days(union)\n",
                              "    custody_days = sum((t - f).days + 1 for f, t, _ in segs)\n")], R),
    ("首尾相接视为连续", S, [("        if out and a <= out[-1][1] + timedelta(days=1):",
                              "        if out and a <= out[-1][1]:")], R),
    ("羁押不连续又没给执行之日：不算起止并提示", S, [
        ("        notes.append(NOTE_GAP if union else NOTE_NO_START)", "        notes.append(NOTE_NO_START)")], R),
    ("给了执行之日：止日扣折抵", S, [("        start, shift = es, offset", "        start, shift = es, 0")], R),
    ("加月对齐到当月最后一天", S, [("min(d.day, calendar.monthrange(year, month)[1])", "min(d.day, 28)")], R),
    ("先加年、再加月", S, [("    return add_months(add_months(d, years * 12), months)",
                             "    return add_months(d, years * 12 + months)")], R),
    ("偶数个整月按月折半", S, [("    if total % 2 == 0:", "    if False:")], R),
    ("按天折半向上取整", S, [("        half = start + timedelta(days=-(-n // 2) - 1)",
                              "        half = start + timedelta(days=n // 2 - 1)")], R),
    ("节点同样扣折抵（取法 a）", S, [("    half -= timedelta(days=shift)\n", "")], R),
    ("取法 f：连续羁押、比例不是 1:1 时调整", S, [
        ("        start, shift = union[0][0], offset - custody_days", "        start, shift = union[0][0], 0")], R),
    ("取法 c：同一天按羁押算", S, [("    r_days = _days(_merge(residence_all + detention)) - d_days",
                                   "    r_days = _days(residence_all)")], R),
    ("无期徒刑不算起止", S, [('    if penalty == "无期徒刑":\n        notes += [NOTE_LIFE, NOTE_LIFE_OFFSET]',
                               '    if False:\n        notes += [NOTE_LIFE, NOTE_LIFE_OFFSET]')], R),
    ("羁押段起止写反报参数错误", S, [('            raise ApiError("INVALID_ARGUMENT", "custody_reversed")', "            pass")], R),
    ("没有刑期报参数错误", S, [('        raise ApiError("INVALID_ARGUMENT", "term_missing")', "        pass")], R),
    ("折抵超过刑期提示", S, [("        notes.append(NOTE_SERVED)", "        pass")], R),
    ("工具接入 /core/tool", "tools/__init__.py", [
        ('        "case_calc_sentence": sentence.calc_sentence,  # T24\n', "")], R),
]

_run = rg.run


def _run_no_full(sel: str):
    if sel == "tests":
        return 0, "（本脚本不跑全量，见 T24\\pytest.txt）"
    return _run(sel)


rg.run = _run_no_full

if __name__ == "__main__":
    sys.exit(rg.main())
