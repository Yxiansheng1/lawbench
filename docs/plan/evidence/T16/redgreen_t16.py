r"""T16 流水线与案件 wiki 红绿：逐条改坏即红、复原即绿。复用 T3 的 redgreen.py。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T16\redgreen_t16.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location(
    "redgreen_t3", pathlib.Path(__file__).resolve().parents[1] / "T3" / "redgreen.py")
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

R = "tests/test_pipeline.py"
W = "pipeline/steps/wiki.py"
rg.TITLE = "T16 红绿验证"
rg.MUTATIONS = [
    ("律师修改块放回原位置", W, [("            if blocks:\n                text = put_lawyer_blocks(text, blocks)\n",
                                   "            pass\n")], f"{R} -k lawyer_blocks_kept"),
    ("更新只重跑变化材料", W, [('        if self.step == "wiki_update" and card is not None:', "        if False:")],
     f"{R} -k update_reruns_only_changed"),
    ("全新生成重跑全部材料", W, [("            redo = list(mats)\n", "            redo = []\n")],
     f"{R} -k build_reruns_everything"),
    ("表格类材料由程序筛选、不经模型", W, [("        mat.table = is_table(mat)", "        mat.table = False")],
     f"{R} -k table_material"),
    ("摘要里的出处补上材料名", W, [("expand=lambda t: expand_short(t, m.name)", "expand=None")], f"{R} -k test_build"),
    ("卡片出处不合格的丢掉", W, [("cites = [c for c in given if pat.match(c) and self._cite_ok(c, text)]",
                                 "cites = [c for c in given if pat.match(c)]")], f"{R} -k test_build"),
    ("卡片出处和条目文字一起核（不只看格式）", W, [('        return not any(p["class"] in "ABCDE" and p["severity"] == "must_fix"',
                                              '        return not any(p["class"] in "E" and p["severity"] == "must_fix"')],
     f"{R} -k test_build"),
    ("到预算时保存已完成的部分", "pipeline/runner.py", [("            exc.partial = out", "            exc.partial = None")],
     f"{R} -k budget_stop"),
    ("调用次数上限", "pipeline/runner.py", [("            if self.calls >= self.max_calls:", "            if False:")],
     f"{R} -k budget_stop"),
    ("修改只交问题句", "pipeline/runner.py", [
        ("            req = self.fix_request(bad, sources)",
         "            req = self.fix_request([(i, ln, []) for i, ln in enumerate(text.splitlines())], sources)")],
     f"{R} -k fix_round"),
    ("修改结果按序号换回原句", "pipeline/runner.py", [("                lines[i] = expand(new) if expand else new", "                pass")],
     f"{R} -k fix_parser"),
    ("取消", "pipeline/__init__.py", [("        live.cancel.set()\n        return {}", "        return {}")], f"{R} -k cancel"),
    ("服务重启后状态读 result.json", "pipeline/__init__.py", [
        ('        return {"status": STATUS_OF_RESULT.get(res["status"], "failed"),', '        return {"status": "failed",')],
     f"{R} -k status_after_restart"),
    ("同一案件在跑时不另起一次", "pipeline/__init__.py", [
        ('                if live.case_id == case_id and live.progress.status == "running":', "                if False:")],
     f"{R} -k second_run"),
    ('"高"发 xhigh', "pipeline/llm.py", [('EFFORT = {"低": "low", "中": "medium", "高": "xhigh"}',
                                         'EFFORT = {"低": "low", "中": "medium", "高": "high"}')], f"{R} -k request_shape"),
    ("401 报 KEY_INVALID", "pipeline/llm.py", [("    if r.status_code in (401, 403):", "    if False:")],
     f"{R} -k 'key_invalid or http_error'"),
    ("采纳与驳回分开记", "wiki/suggestions.py", [('        s["status"] = "accepted" if accept else "rejected"',
                                               '        s["status"] = "accepted"')], f"{R} -k wiki_suggestions"),
    ("失败材料照抄导入时的原因", W, [('            skipped.append((m, m.get("error") or "无法处理"))',
                                     '            skipped.append((m, "无法处理"))')], f"{R} -k failed_reason"),
    ("程序统计行的出处合并成范围", W, [('"、".join(f"{m.name} {p}" for p in _ranges(places)[:20])',
                                      '"、".join(f"{m.name} {p}" for p in places[:20])')], f"{R} -k table_summary_cites"),
    ("9B·核对不过超 20% 整体跳过", "pipeline/prep.py", [("        if n and bad / n > FAIL_RATIO:", "        if False:")],
     f"{R} -k prep_skipped"),
    ("9B·字段要在所标位置原样找到", "pipeline/prep.py", [
        ('                        if no is None or no not in nos or not _found(m, unit, no, f["value"]):',
         "                        if False:")], f"{R} -k prep_skipped"),
    ("9B·395 不可用整体跳过", "pipeline/prep.py", [('            raise Unavailable(f"http_{r.status_code}")',
                                               '            return {"task": "fields", "result": [], "elapsed_ms": 0}')],
     f"{R} -k prep_skipped"),
    ("9B·表格类材料不送", "pipeline/prep.py", [("                if m.table or unit not in WORD:",
                                             "                if unit not in WORD:")], f"{R} -k prep_skips_table"),
    ("9B·通过的字段交给摘要步骤", W, [("        if refs:\n", "        if False:\n")], f"{R} -k prep_good"),
    ("卡片被截断时精简重试一次", W, [("        if not data:\n            # 输出被截断或不是 JSON",
                                      "        if False:\n            # 输出被截断或不是 JSON")],
     f"{R} -k card_truncated_once"),
    ("卡片还是不行：不写空卡片、记失败", W, [("        if not data:\n            # 还是不行",
                                          "        if False:\n            # 还是不行")],
     f"{R} -k card_truncated_twice"),
    ("修改轮用完后程序兜底", "pipeline/runner.py", [("        text = self.settle(text, obj)\n", "")], f"{R} -k settle_b_moves"),
    ("兜底·A 类插注原文写法、不动出处", "pipeline/runner.py", [
        ("                        new = new.replace(cite, note + cite, 1) if cite and cite in new else new.rstrip() + note",
         "                        pass")], f"{R} -k settle_per_class"),
    ("兜底·C 类只改有问题的那组出处", "pipeline/runner.py", [
        ('                    new = new.replace(p["citation"], "〔未找到依据〕", 1)', "                    pass")],
     f"{R} -k settle_per_class"),
    ("兜底·还不过时整句改标未找到依据", "pipeline/runner.py", [
        ('                new = _replace_cites(line, "〔未找到依据〕")\n                if new == line:',
         "                new = line\n                if new == line:")], f"{R} -k settle_unfixable"),
    ("原件已删除的材料清单注明", W, [('"原件已删除（保留材料文本）" if m.meta["status"] == "source_deleted" else ""', '""')],
     f"{R} -k deleted_originals"),
]

_run = rg.run


def _run_no_full(sel: str):
    if sel == "tests":
        return 0, "（本脚本不跑全量，见 T16\\pytest.txt）"
    return _run(sel)


rg.run = _run_no_full

if __name__ == "__main__":
    sys.exit(rg.main())
