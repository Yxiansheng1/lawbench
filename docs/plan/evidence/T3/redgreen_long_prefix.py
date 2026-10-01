r"""T3 小项（执行令 20261001-2301 第 1 条）红绿：realpath 带回 \\?\ 前缀时的归一。复用 T3 的 redgreen.py。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T3\redgreen_long_prefix.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location("redgreen_t3", pathlib.Path(__file__).with_name("redgreen.py"))
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

G = "case/gate.py"
T = "tests/test_gate.py"
rg.TITLE = "T3 小项·\\\\?\\ 前缀归一 红绿验证"
rg.MUTATIONS = [
    ("_real_top 先归一再算 relpath", G, [
        ("    rel = _relpath(_plain(os.path.realpath(path)), _plain(root), op)",
         "    rel = _relpath(os.path.realpath(path), root, op)")], f"{T} -k long_prefix"),
    ("is_within 先归一再比", G, [("    t = _norm(_plain(target))", "    t = _norm(target)")],
     f"{T} -k 'long_prefix or plain_only'"),
    ("盘符路径的前缀归一", G, [
        (r'''    if p.startswith("\\\\?\\") and _DRIVE.match(p[4:]) and p[6:7] == "\\":
        return p[4:]
''', "")], f"{T} -k 'long_prefix or plain_only'"),
    ("不放宽：\\\\?\\Volume 等写法不归一", G, [
        (r'''    if p.startswith("\\\\?\\") and _DRIVE.match(p[4:]) and p[6:7] == "\\":''',
         r'''    if p.startswith("\\\\?\\"):''')], f"{T} -k 'plain_only or volume_prefix'"),
]

if __name__ == "__main__":
    sys.exit(rg.main())
