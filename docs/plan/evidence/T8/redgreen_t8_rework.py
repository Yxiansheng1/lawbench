r"""T8 返修红绿（执行令 致B-ORCH-执行令-T8返修-20260930-0201 与补充 0608）：逐条改坏即红、复原即绿。

复用 T3 的 redgreen.py 的 run()；结束时核对源码逐字节复原。
用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T8\redgreen_t8_rework.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_T3 = pathlib.Path(__file__).resolve().parents[1] / "T3" / "redgreen.py"
_spec = importlib.util.spec_from_file_location("redgreen_t3", _T3)
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

R = "tests/test_t8_rework.py"
MUTATIONS = [
    ("P1-1·截断的单元不记进 reads.json", "tools/materials.py", [
        ("    if not truncated:  # 截断的单元没读全", "    if True:  # 截断的单元没读全"),
    ], f"{R} -k p1_1_truncated"),
    ("P1-2·重开案件不把本进程 begin 过的任务标异常", "case/task.py", [
        ('            if t["state"] != "running" or t["task_id"] in self._begun:', '            if t["state"] != "running":'),
    ], f"{R} -k p1_2_reopen"),
    ("P1-3·progress 的读-改-写在任务锁里", "case/task.py", [
        ('        with self.task_lock(task_id):\n            case_id, root, task = self.locate(task_id)\n'
         '            if task["state"] == "pending":',
         '        with threading.Lock():\n            case_id, root, task = self.locate(task_id)\n'
         '            if task["state"] == "pending":'),
    ], f"{R} -k p1_3_progress"),
    ("P2-1·占位单元不算已读", "case/task.py", [
        ('            got -= {u.no for u in units if u.text.strip() == texts.PENDING_OCR}', "            pass"),
    ], f"{R} -k p2_1"),
    ("P2-2·已有版本不分大小写匹配", "tools/drafts.py", [
        ("re.escape(title.casefold())", "re.escape(title)"),
        ("pat.match(p.name.casefold())", "pat.match(p.name)"),
    ], f"{R} -k p2_2_case"),
    ("P2-2·取版本号和写文件在同一把锁里", "tools/drafts.py", [
        ("    with ctx.tasks.task_lock(tid):\n        folder =", "    with threading.Lock():\n        folder ="),
    ], f"{R} -k p2_2_concurrent"),
    ("P2-3·待确认.json 的读-改-写加锁", "tools/drafts.py", [
        ("    with _WIKI_LOCK:\n        return _suggest_wiki(ctx, a)", "    return _suggest_wiki(ctx, a)"),
    ], f"{R} -k p2_3"),
    ("P2-4·end 遇到已结束的任务直接返回", "case/task.py", [
        ('        if task["state"] == "finished":\n            return', '        if False:\n            return'),
    ], f"{R} -k p2_4"),
    ("P2-4·progress 在任务不是执行中时不写", "case/task.py", [
        ('            if task["state"] != "running":\n                return {}', '            if False:\n                return {}'),
    ], f"{R} -k p2_4"),
    ("P2-5·index() 不拿案件锁", "case/materials.py", [
        ('不加锁读到的一定是完整的旧版或新版。"""\n        root = self.cases.root_of(case_id)\n'
         '        return self._load_index(root, case_id)',
         '不加锁读到的一定是完整的旧版或新版。"""\n        root = self.cases.root_of(case_id)\n'
         '        with self._lock(case_id):\n            return self._load_index(root, case_id)'),
    ], f"{R} -k p2_5"),
    ("P2-6·_mkdirs 接住 FileExistsError", "case/gate.py", [
        ("            try:\n                os.mkdir(cur)\n            except FileExistsError:\n"
         "                pass  # 并发请求抢先建好了（T8 返修 P2-6）：照常做下面的复查",
         "            os.mkdir(cur)"),
    ], f"{R} -k p2_6_mkdirs_tolerates"),
    ("P2-7·新建任务单作废同一会话更早的待执行任务单", "case/task.py", [
        ('            self._void_pending(root, d["case_id"], d["session_id"])\n', ""),
    ], f"{R} -k 'p2_7_newer or p2_7_same_second or p2_7_voided'"),
    ("P2-7·目录里不只有 task.json 的不删", "case/task.py", [
        ('            if sorted(p.name for p in folder.iterdir()) != ["task.json"]:', "            if False:"),
    ], f"{R} -k p2_7_pending_with_extra"),
    ("P3-1·目录那几行计入预算", "case/context.py", [
        ("    while k > 0 and tokens.count(text) > budget:", "    while False:"),
    ], f"{R} -k p3_1"),
    ("P3-2·progress 对还没 begin 的任务报 TASK_NOT_FOUND", "case/task.py", [
        ('            if task["state"] == "pending":\n                raise ApiError("TASK_NOT_FOUND", "not_begun")',
         '            if False:\n                raise ApiError("TASK_NOT_FOUND", "not_begun")'),
    ], f"{R} -k p3_2"),
    ("P3-2·end 对还没 begin 的任务报 TASK_NOT_FOUND", "case/task.py", [
        ('        if task["state"] != "running":\n            raise ApiError("TASK_NOT_FOUND", "not_running")',
         '        if False:\n            raise ApiError("TASK_NOT_FOUND", "not_running")'),
    ], f"{R} -k p3_2"),
    ("P3-3·elapsed_s 从 begin 算起", "case/task.py", [
        ("elapsed_s=_elapsed(task, self._begun.get(task_id)))", "elapsed_s=_elapsed(task, None))"),
    ], f"{R} -k p3_3"),
    ("缺口 M6·覆盖计算裁掉超出范围的单元号", "case/task.py", [
        ("            got &= set(range(1, total + 1))\n", ""),
    ], f"{R} -k gap_coverage_clips"),
    ("缺口 M7·add_read 的锁", "case/task.py", [
        ('        with self._lock:\n            data = self._read(root, self.rel(task_id, "reads.json")',
         '        if True:\n            data = self._read(root, self.rel(task_id, "reads.json")'),
    ], f"{R} -k gap_add_read"),
    ("缺口 M8·单元超长时截断", "tools/materials.py", [
        ("    if truncated:  # 一个单元就超过上限", "    if False:  # 一个单元就超过上限"),
    ], f"{R} -k p1_1_truncated"),
]


def main() -> int:
    originals = {p: p.read_bytes() for p in rg.PKG.rglob("*.py")}
    bad = 0
    print(f"T8 返修红绿验证：{len(MUTATIONS)} 类防护\n")
    try:
        for i, (label, rel, reps, sel) in enumerate(MUTATIONS, 1):
            f = rg.PKG / rel
            mutated = f.read_text(encoding="utf-8")
            for old, new in reps:
                n = mutated.count(old)
                if n != 1:
                    raise SystemExit(f"[{i}] {label}：原文命中 {n} 次（应为 1），脚本需要更新")
                mutated = mutated.replace(old, new)
            try:
                f.write_text(mutated, encoding="utf-8")
                rc_red, sum_red = rg.run(sel)
            finally:
                f.write_bytes(originals[f])
            rc_green, sum_green = rg.run(sel)
            ok = rc_red != 0 and rc_green == 0
            bad += not ok
            print(f"[{i:02d}] {label}\n  改坏 {rel} → {'红' if rc_red else '绿（未变红！）'}：{sum_red}\n"
                  f"  复原 → {'绿' if rc_green == 0 else '红（复原后未变绿！）'}：{sum_green}\n", flush=True)
    finally:
        for p, data in originals.items():
            if p.read_bytes() != data:
                p.write_bytes(data)
                print(f"[复原] {p}")
    same = all(p.read_bytes() == d for p, d in originals.items())
    print(f"源码与开始时逐字节一致：{'是' if same else '否'}")
    print(f"\n结论：{len(MUTATIONS) - bad}/{len(MUTATIONS)} 类防护 改坏即红、复原即绿")
    return 1 if bad or not same else 0


if __name__ == "__main__":
    sys.exit(main())
