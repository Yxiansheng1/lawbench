r"""T5 第三轮小修红绿（执行令 致B-ORCH-执行令-T5第三轮小修-20260930-1559）。复用 T3 的 redgreen.py。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T5\redgreen_round3_fix.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location(
    "redgreen_t3", pathlib.Path(__file__).resolve().parents[1] / "T3" / "redgreen.py")
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

R = "tests/test_t5_rework3.py"
rg.TITLE = "T5 第三轮小修红绿验证"
rg.MUTATIONS = [
    ("P2-1·15 位以上的整数按 15 位有效数字", "ingest/xlsx.py", [
        ("    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:",
         "    if isinstance(v, float) and v.is_integer():"),
    ], f"{R} -k p2_1"),
    ("P3-1·扫描时按 index.json 回填 material_ids", "case/materials.py", [
        ("        ids.backfill(index)  # 升级前已有的材料", "        pass  # 升级前已有的材料"),
    ], f"{R} -k p3_1"),
    ("P3-2·按 workbook 关系文件定位工作表部件", "ingest/xlsx.py", [
        ("        parts = {n for n in names if _SHEET_PART.match(n)} | (_sheet_targets(z) & names)",
         "        parts = {n for n in names if _SHEET_PART.match(n)}"),
    ], f"{R} -k p3_2_sheet_part_located"),
]

_run = rg.run


def _run_no_full(sel: str):
    if sel == "tests":
        return 0, "（本脚本不跑全量，见 T5\\pytest-返修第三轮*.txt）"
    return _run(sel)


rg.run = _run_no_full

if __name__ == "__main__":
    sys.exit(rg.main())
