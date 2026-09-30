r"""T8 第二轮返修红绿（执行令 致B-ORCH-执行令-T8第二轮及T5第二轮返修-20260930-1318 第一节）。复用 T3 的 redgreen.py。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T8\redgreen_t8_round2.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location(
    "redgreen_t3", pathlib.Path(__file__).resolve().parents[1] / "T3" / "redgreen.py")
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

R = "tests/test_t8_rework2.py"
rg.TITLE = "T8 第二轮红绿验证"
rg.MUTATIONS = [
    ("F1·begin 先记 _begun、mark_abnormal 拿锁（两层一起去掉；只去一层时另一层仍守得住）", "case/task.py", [
        ("            self._begun[tid] = datetime.now().astimezone()\n            self._write(root, self.rel(tid, \"task.json\")",
         "            self._write(root, self.rel(tid, \"task.json\")"),
        ("            self._where[tid] = case_id\n        logs.event(\"task\", \"begin\"",
         "            self._where[tid] = case_id\n            self._begun[tid] = datetime.now().astimezone()\n"
         "        logs.event(\"task\", \"begin\""),
        ("        with self._lock:\n            return self._mark_abnormal(case_id)", "        return self._mark_abnormal(case_id)"),
    ], f"{R} -k f1_"),
    ("F2·save_draft 在任务锁里再核一次状态", "tools/drafts.py", [
        ('        if ctx.tasks.locate(tid)[2]["state"] != "running":\n            raise ApiError("TASK_NOT_FOUND", "not_running")\n',
         ""),
    ], f"{R} -k f2_"),
    ("F2·end 在任务锁里", "case/task.py", [
        ("        with self.task_lock(task_id):\n            return self._end(", "        if True:\n            return self._end("),
    ], f"{R} -k f2_save_draft_during_end"),
    ("F3·读 json 遇 PermissionError 重试", "contracts.py", [
        ('            return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))\n        except PermissionError:',
         '            return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))\n        except ZeroDivisionError:'),
    ], f"{R} -k f3_read_json_retries"),
    ("F4·表头放不下时不带列名表头", "tools/materials.py", [
        ("    if overhead + len(TRUNC_TAIL) + 1 > limit:", "    if False:"),
    ], f"{R} -k f4_"),
    ("F5·同一秒平局以后写的为准", "case/task.py", [
        (' or (\n                        t["created_at"] == best["created_at"] and t["task_id"] == self._latest.get(session_id))', ""),
    ], f"{R} -k f5_"),
]

_run = rg.run


def _run_no_full(sel: str):
    if sel == "tests":
        return 0, "（本脚本不跑全量，见 T5\\pytest-返修第二轮*.txt）"
    return _run(sel)


rg.run = _run_no_full

if __name__ == "__main__":
    sys.exit(rg.main())
