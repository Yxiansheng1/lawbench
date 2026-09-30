r"""契约 1.2 带来的改动的红绿（T3、T5、T8 三张卡一起跑）：逐条改坏即红、复原即绿。复用 redgreen.py 的 run()。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T3\redgreen_contract12.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location("redgreen_t3", pathlib.Path(__file__).with_name("redgreen.py"))
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

T5 = "tests/test_t5_contract12.py"
T8 = "tests/test_t8_rework.py"
rg.TITLE = "契约 1.2 红绿验证（T3、T5、T8）"
rg.MUTATIONS = [
    ("T3 N35②·新补进来的分组里的胶囊标 new", "capsules.py", [
        ('dict(it, hidden=True, new=True) for it in g["items"]', 'dict(it, hidden=True) for it in g["items"]'),
    ], "tests/test_api_case.py -k capsules_new_default_merged_hidden"),
    ("T3 N35②·已有分组里新补的胶囊标 new", "capsules.py", [
        ("dict(copy.deepcopy(it), hidden=True, new=True)", "dict(copy.deepcopy(it), hidden=True)"),
    ], "tests/test_api_case.py -k capsules_new_default_merged_hidden"),
    ("T5 X11/N26·index.json 重建后按 material_ids 拿回原编号", "case/materials.py", [
        ("mid = ids.reuse(rel, digest, used) if digest else None", "mid = None"),
    ], "tests/test_t5_rework.py -k x11_ids"),
    ("T5 X11/N26·分配编号时写 material_ids", "case/materials.py", [
        ('                ids.record(mid, rel, digest or "0" * 64, now, index["next_seq"])\n', ""),
    ], "tests/test_t5_rework.py -k x11_ids"),
    ("T5 X13·单元格按显示值写", "ingest/xlsx.py", [
        ('            t = _display(wv[key]) if key in wv else ""', '            t = _fmt(wv[key].value) if key in wv else ""'),
    ], f"{T5} -k x13_xlsx_written"),
    ("T5 X13·格式版本变了原件没变也重解析", "case/materials.py", [
        ('            refresh = live and stale_format and entry["type"] in REFORMAT_TYPES and entry["status"] != "failed"',
         "            refresh = False"),
    ], f"{T5} -k x13_format_version"),
    ("T5 N21·有外链没重算的 note", "ingest/xlsx.py", [
        ("        note = blocked_note  # 有外链", "        pass  # 有外链"),
    ], f"{T5} -k n21_external"),
    ("T5 N28·整份待识别的 Source 行", "case/materials.py", [
        ('        kind = "待识别"  # 整份都是扫描件', '        pass  # 整份都是扫描件'),
    ], f"{T5} -k n28"),
    ("T8 N31·分段读到单元末尾才记已读", "tools/materials.py", [
        ('    if ctx.tasks.read_part(ctx.task["task_id"], m, u.no, offset, end, len(u.text)):',
         "    if True:"),
    ], f"{T8} -k 'p1_1_long_unit or p1_1_skipping'"),
    ("T8 N31·分段读要从 0 起连续", "case/task.py", [
        ("            if start <= got:\n                got = max(got, end)", "            got = max(got, end)"),
    ], f"{T8} -k p1_1_skipping"),
    ("T8 N37·begin 复制选择，不消耗", "case/task.py", [
        ("                task.update(task_id=tid, created_at=now_iso())", '                tid = task["task_id"]'),
    ], f"{T8} -k p2_7_selection_not_consumed"),
    ("T8 N37·新选择顶掉旧的", "case/task.py", [
        ('            self._void_pending(root, d["case_id"], d["session_id"])\n', ""),
    ], f"{T8} -k 'p2_7_selection_not_consumed or p2_7_same_second or p2_7_voided'"),
    ("T8 N37·/api/task/current 返回当前选择", "case/task.py", [
        ('        if best is None:\n            return {"selection": None}', '        if True:\n            return {"selection": None}'),
    ], f"{T8} -k p2_7_task_current"),
    ("T8 N35①·tasks_list 带 coverage", "case/task.py", [
        ('"finished_at": res["finished_at"], "coverage": res["coverage"],', '"finished_at": res["finished_at"], "coverage": None,'),
    ], f"{T8} -k n35_tasks_list"),
    ("T8 N35⑥·/api/outputs 返回 成果/索引.json", "case/task.py", [
        ('        if not p.is_file():\n            return {"v": 1, "outputs": []}',
         '        if True:\n            return {"v": 1, "outputs": []}'),
    ], f"{T8} -k n35_outputs_empty_and_filled"),
]

_run = rg.run


def _run_no_full(sel: str):
    """结尾那次"复原后全量"不在这里跑：随后深、短路径各跑一次全量，见 T5\\pytest-返修第一轮*.txt。"""
    if sel == "tests":
        return 0, "（本脚本不跑全量，见 T5\\pytest-返修第一轮*.txt）"
    return _run(sel)


rg.run = _run_no_full

if __name__ == "__main__":
    sys.exit(rg.main())
