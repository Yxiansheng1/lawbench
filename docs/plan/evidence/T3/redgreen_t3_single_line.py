r"""T3 小项（执行令 20261001-1246）红绿：带 pattern 的字符串字段拒绝换行和控制字符。复用 redgreen.py。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T3\redgreen_t3_single_line.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location("redgreen_t3", pathlib.Path(__file__).resolve().parent / "redgreen.py")
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

R = "tests/test_t3_single_line.py"
rg.TITLE = "T3 小项红绿：字符串字段不收换行"
rg.MUTATIONS = [
    ("校验器用带单行检查的那个", "contracts.py", [
        ("    return _Validator({", "    return Draft202012Validator({"),
    ], R),
    ("控制字符整段都算（不只换行）", "contracts.py", [
        ('_CONTROL = re.compile(r"[\\x00-\\x1f\\x7f-\\x9f]")', '_CONTROL = re.compile(r"[\\n]")'),
    ], R),
]

_run = rg.run


def _run_no_full(sel: str):
    if sel == "tests":
        return 0, "（本脚本不跑全量，见 T3\\pytest-单行.txt）"
    return _run(sel)


rg.run = _run_no_full

if __name__ == "__main__":
    sys.exit(rg.main())
