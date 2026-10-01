r"""T10 第二轮复核小项（注记 20261001-1644）红绿。复用 T3 的 redgreen.py；只放本次新增的两类（全部 42 类见 redgreen_t10.py）。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T10\redgreen_t10_小项.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location(
    "redgreen_t3", pathlib.Path(__file__).resolve().parents[1] / "T3" / "redgreen.py")
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

R = "tests/test_checks.py"
rg.TITLE = "T10 第二轮复核小项红绿"
rg.MUTATIONS = [
    ("P3-c·只写年份：同处有阿拉伯数字年份就照常核", "checks/citations.py", [
        ('    if v.startswith("年"):', "    if False:"),
    ], f"{R} -k year_only_not_exempted"),
    ("SKILL.md 不是 UTF-8 时不抛", "checks/__init__.py", [
        ('.read_text(encoding="utf-8", errors="replace")', '.read_text(encoding="utf-8")'),
    ], f"{R} -k skill_md_not_utf8"),
]

_run = rg.run


def _run_no_full(sel: str):
    if sel == "tests":
        return 0, "（本脚本不跑全量，见 T3\\pytest-单行.txt）"
    return _run(sel)


rg.run = _run_no_full

if __name__ == "__main__":
    sys.exit(rg.main())
