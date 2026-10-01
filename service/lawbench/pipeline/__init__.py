"""流水线（Spec 9.1；接口 /api/pipeline/run、/api/pipeline/{task_id}、/api/pipeline/{task_id}/cancel）。

本次只有案件 wiki（wiki_build、wiki_update）。一次运行 = 一个 P- 任务（工作区/任务/<编号>/），在后台线程里跑；
同一案件已有一次在跑时，再请求运行返回正在跑的那个任务编号（契约没有"正在运行"的错误码）。
状态先看本进程内存，没有（服务重启过、或已结束）再读 result.json。
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass

from .. import checks, logs
from ..case import gate
from ..errors import ApiError
from .llm import LLM, Cancelled
from .prompts import Prompts
from .runner import MINUTES, Budget, BudgetStop, Progress, Runner
from .steps import wiki

SKILL = "case-wiki-build"
RECORD = "运行记录.json"
STATUS_OF_RESULT = {"running": "running", "completed": "completed", "cancelled": "cancelled",
                    "budget_stopped": "budget_stopped", "failed": "failed", "output_limit": "failed",
                    "interrupted": "interrupted", "abnormal": "interrupted"}


def budget_calls(segments: int, articles: int) -> int:
    """Spec 9.1：调用次数上限 = 段数 × 3 + 篇数 × 3 + 10。"""
    return segments * 3 + articles * 3 + 10


@dataclass
class _Live:
    case_id: str
    progress: Progress
    cancel: threading.Event
    thread: threading.Thread | None = None


class Pipelines:
    def __init__(self, *, cases, tasks, materials, net, key_getter, skills_dirs, clock=time.monotonic):
        self.cases = cases
        self.tasks = tasks
        self.materials = materials
        self.net = net
        self.key_getter = key_getter
        self.skills_dirs = list(skills_dirs)
        self.clock = clock
        self._lock = threading.Lock()
        self._live: dict[str, _Live] = {}

    def run(self, d: dict) -> dict:
        case_id = d["case_id"]
        with self._lock:
            for tid, live in self._live.items():
                if live.case_id == case_id and live.progress.status == "running":
                    return {"task_id": tid}
        root = self.cases.root_of(case_id)
        index = self.materials.index(case_id)
        prompts = Prompts.load(self.skills_dirs, SKILL, wiki.REQUIRED_STEPS)
        mats, _ = wiki.load_materials(root, index)
        segments = sum(len(m.chunks) for m in mats if not m.table)
        articles = len(wiki.SECTIONS) + 1
        budget = {"model_calls": budget_calls(segments, articles), "tool_calls": 1, "minutes": MINUTES}
        tid, root = self.tasks.begin_pipeline(case_id, d["step"], SKILL, d["params"], budget)
        live = _Live(case_id, Progress(), threading.Event())
        with self._lock:
            self._live[tid] = live
        live.thread = threading.Thread(target=self._work, name=f"pipeline-{tid}", daemon=True,
                                       args=(tid, root, case_id, index, d, prompts, budget, live))
        live.thread.start()
        return {"task_id": tid}

    def _work(self, tid, root, case_id, index, d, prompts, budget, live: _Live) -> None:
        t0 = self.clock()
        llm = LLM(self.net, self.key_getter, live.cancel)
        mats = checks.MaterialSet.from_case(root, index)
        runner = Runner(llm=llm, prompts=prompts, params=d["params"], materials=mats, task_id=tid,
                        budget=Budget(budget["model_calls"], budget["minutes"], self.clock), progress=live.progress,
                        kind=checks.skill_kind(self.skills_dirs, SKILL))
        rule = wiki.load_filter(self.skills_dirs, SKILL)
        run = wiki.WikiRun(root=root, case_id=case_id, index=index, runner=runner, step=d["step"], rule=rule,
                           task_id=tid, tasks=self.tasks)
        status, error = "completed", None
        try:
            if d.get("use_prep"):
                from . import prep
                prep.attach(run, self.net, self.key_getter)
            run.run()
        except Cancelled:
            status = "cancelled"
        except BudgetStop:
            status = "budget_stopped"
        except ApiError as e:
            status, error = "failed", e.code
        except Exception as e:  # noqa: BLE001 流水线线程里任何异常都要收尾，不能让任务一直停在执行中
            status, error = "failed", type(e).__name__
        check, cites = None, []
        try:
            check, cites = run.final_check()
        except Exception as e:  # noqa: BLE001
            logs.event("pipeline", "final_check", status="fail", case_id=case_id, error=type(e).__name__)
        try:
            self._record(root, tid, runner, run, status, error, self.clock() - t0)
            self.tasks.end_pipeline(root, tid, status, model_calls=len(runner.calls), drafts=run.drafts,
                                    citation_check=check, citations=cites)
        finally:
            live.progress.status = status
            live.progress.current = None
            logs.event("pipeline", "run", status="ok" if status == "completed" else "fail", case_id=case_id,
                       duration_ms=(self.clock() - t0) * 1000, error=error or (None if status == "completed" else status))

    def _record(self, root, tid, runner: Runner, run, status, error, elapsed) -> None:
        """运行记录（任务目录里，只有元数据）：调用次数、耗时、最大输入、修改轮次。"""
        ins = [c["输入字数"] for c in runner.calls]
        data = {"状态": status, "错误": error, "模型调用次数": len(runner.calls), "总耗时秒": round(elapsed, 1),
                "单次最大输入字数": max(ins, default=0),
                "单次最大输入token": max([c["输入token"] or 0 for c in runner.calls], default=0),
                "输出被截断次数": sum(1 for c in runner.calls if c["结束原因"] == "length"),
                "预算": {"调用上限": runner.budget.max_calls, "分钟上限": runner.budget.minutes},
                "395": ({"提示": run.prep.note, **run.prep.stats} if run.prep else None),
                "修改记录": runner.fixes, "调用": runner.calls}
        gate.write_bytes(root, self.tasks.rel(tid, RECORD), json.dumps(data, ensure_ascii=False, indent=2).encode(),
                         op="pipeline")

    def status(self, task_id: str) -> dict:
        with self._lock:
            live = self._live.get(task_id)
        if live is not None:
            return live.progress.value()
        _, root, task = self.tasks.locate(task_id)
        if task["kind"] != "pipeline":
            raise ApiError("TASK_NOT_FOUND", "not_pipeline")
        res = self.tasks.result(root, task_id)
        return {"status": STATUS_OF_RESULT.get(res["status"], "failed"), "step_index": 0, "step_total": 0,
                "current": None, "queue_wait_ms": None}

    def cancel(self, task_id: str) -> dict:
        with self._lock:
            live = self._live.get(task_id)
        if live is None:
            _, _, task = self.tasks.locate(task_id)
            if task["kind"] != "pipeline":
                raise ApiError("TASK_NOT_FOUND", "not_pipeline")
            return {}
        live.cancel.set()
        return {}

    def wait(self, task_id: str, timeout: float | None = None) -> None:
        """测试与对照脚本用：等后台线程结束。"""
        with self._lock:
            live = self._live.get(task_id)
        if live is not None and live.thread is not None:
            live.thread.join(timeout)
