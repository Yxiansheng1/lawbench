r"""T5 第四轮红绿：copy_original 的临时文件独占新建（注记 2219 第 2 节）。复用 T3 的 redgreen.py。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T5\redgreen_round4.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_T3 = pathlib.Path(__file__).resolve().parents[1] / "T3" / "redgreen.py"
_spec = importlib.util.spec_from_file_location("redgreen_t3", _T3)
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

rg.MUTATIONS = [
    ("copy_original·临时名撞上时换名重试，不覆盖别人的临时文件（去掉 O_EXCL）", "case/gate.py", [
        ('    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)',
         '    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)'),
    ], "tests/test_t5_gate.py -k collision"),
]

if __name__ == "__main__":
    sys.exit(rg.main())
