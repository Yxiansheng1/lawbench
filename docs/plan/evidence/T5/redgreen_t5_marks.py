r"""T5 小项（注记 20261001-1221）红绿：材料原文里以【开头的行不当位置标记。复用 T3 的 redgreen.py。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T5\redgreen_t5_marks.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location(
    "redgreen_t3", pathlib.Path(__file__).resolve().parents[1] / "T3" / "redgreen.py")
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

R = "tests/test_t5_marks.py"
rg.TITLE = "T5 小项红绿：行首【…】"
rg.MUTATIONS = [
    ("只认我方写的标记（改回认所有行首【…】）", "case/texts.py", [
        ("    mark = _MARKS.get(unit)", '    mark = re.compile(r"^【([^】\\n]+)】\\n?", re.M)'),
    ], R),
    ("标记必须独占一行", "case/texts.py", [
        ('    "page": re.compile(r"^【(第[0-9]+页)】(?:\\n|$)", re.M),', '    "page": re.compile(r"^【(第[0-9]+页)】\\n?", re.M),'),
    ], f"{R} -k only_own_marks_split"),
    ("按材料的定位方式只认对应的一种", "case/texts.py", [
        ('    "line": re.compile(r"^【(第[0-9]+行)】(?:\\n|$)", re.M),', '    "line": re.compile(r"^【(第[0-9]+[页段行])】(?:\\n|$)", re.M),'),
    ], f"{R} -k only_own_marks_split"),
    ("正文里恰好是标记的整行写入时转义（注记 1354）", "case/materials.py", [
        ('    return _MARK_LINE.sub("\\u3000", body)', "    return body"),
    ], f"{R} -k 'line_equal_to_mark or render_escapes'"),
]

_run = rg.run


def _run_no_full(sel: str):
    if sel == "tests":
        return 0, "（本脚本不跑全量，见 T5\\pytest-行首标记.txt）"
    return _run(sel)


rg.run = _run_no_full

if __name__ == "__main__":
    sys.exit(rg.main())
