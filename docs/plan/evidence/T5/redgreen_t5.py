"""T5 对路径闸门改动的红绿验证：复用 T3 的 redgreen.py，只换改坏清单。

用法（在 service\\ 目录）：.venv\\Scripts\\python ..\\docs\\plan\\evidence\\T5\\redgreen_t5.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_T3 = pathlib.Path(__file__).resolve().parents[1] / "T3" / "redgreen.py"
_spec = importlib.util.spec_from_file_location("redgreen_t3", _T3)
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

SEL = "tests/test_t5_gate.py tests/test_materials_api.py"
rg.MUTATIONS = [
    ("T5 闸门·copy_original 从不覆盖（先查已存在 + rename 不覆盖一起去掉）", "case/gate.py", [
        ("    if os.path.lexists(path):\n        raise FileExistsError(rel)\n", ""),
        ("        os.rename(tmp, path)  # Windows 上目标已存在时 rename 失败，不会覆盖",
         "        os.replace(tmp, path)"),
    ], SEL),
    ("T5 闸门·copy_original 只能写原件区（不能写 工作区、成果、以 . 开头，不能越界）", "case/gate.py", [
        ('    """原件区新建文件（仅 /api/materials/import）：复制，从不覆盖。目标已存在抛 FileExistsError。"""\n'
         "    parts = check_ai_rel(rel, op)\n",
         '    """原件区新建文件（仅 /api/materials/import）：复制，从不覆盖。目标已存在抛 FileExistsError。"""\n'
         "    parts = [p for p in rel.replace(chr(92), '/').split('/') if p]\n"),
    ], SEL),
    ("T5 闸门·delete_work_file 只能删 工作区/ 下的文件", "case/gate.py", [
        ("    if parts[0] != WORK:\n        raise _deny(op, \"delete_outside_work\")\n", ""),
        ("    if _real_top(root, path, op) != WORK.casefold():\n        raise _deny(op, \"delete_outside_work\")\n", ""),
    ], SEL),
]

if __name__ == "__main__":
    sys.exit(rg.main())
