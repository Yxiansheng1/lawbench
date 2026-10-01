r"""T10 小项（执行令 20261001-2301 第 2 条）红绿：识别不清的人名紧挨别的汉字时，A 类仍认得出。复用 T3 的 redgreen.py。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T10\redgreen_t10_紧挨.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location(
    "redgreen_t3", pathlib.Path(__file__).resolve().parents[1] / "T3" / "redgreen.py")
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

C = "checks/citations.py"
T = "tests/test_checks.py"
rg.TITLE = "T10 小项·人名紧挨汉字 红绿验证"
rg.MUTATIONS = [
    ("整串之外再取 3–4 字子串", C, [("    if len(whole) > max(_NAME_LENS):", "    if False:")],
     f"{T} -k 'name_next_to_other_chars or name_windows'"),
    ("不取 2 字子串（长度只取 4、3，且至少 2 个认得出的字）", C, [
        ("_NAME_LENS = (4, 3)", "_NAME_LENS = (4, 3, 2)"),
        ('len(w) - w.count("■") >= 2', 'len(w) - w.count("■") >= 1')],
     f"{T} -k 'name_windows or name_next_to_other_chars_copied'"),
    ("原来的整串比对仍在", C, [("    out = [whole]\n", "    out = []\n")], f"{T} -k 'a_filled_in or name_windows'"),
]

if __name__ == "__main__":
    sys.exit(rg.main())
