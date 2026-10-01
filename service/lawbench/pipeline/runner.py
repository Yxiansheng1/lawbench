"""流水线通用框架（Spec 9.1、D6；参照 wiki 测试的 run_pipeline_v2.py）。

每个步骤 = 取输入 → 拼提示词 → 调 6000D（流式）→ 清理输出 → 核对出处（T10 的 checks 库）→ 不通过时只把有问题的
句子交回"修改"步骤（最多 2 轮；改完内容没变化就停止）→ 由调用方写入草稿。

- 核对：逐行用 checks.check_text 核，A、B、C、D、E、G 类里 must_fix 的算"有问题"（成果类型按 Skill 的 kind，
  案件 wiki 是 excerpt，G 也必须改）；F 只是提示。
- 修改：有问题的句子编上序号、附问题说明与相关原文（所引位置、说明里"实际在"的位置），要回"序号. 改好的句子"，
  按序号逐句换回原文；没换上的保留原句。
- 预算（Spec 9.1）：调用次数上限由调用方按"段数 × 3 + 篇数 × 3 + 10"给；时间上限 45 分钟，排队时间不算。
  到上限抛 BudgetStop，调用方保存已完成的部分。
- 取消：Event 置位后，在途请求在读流的下一行关闭，排队的不再发出，抛 Cancelled。
- 并行度 2（Spec 8.5）。
- 运行记录只有元数据（步骤、对象、耗时、token、结束原因）；服务日志更少，只记案件编号、耗时（Spec 20.8）。
"""
from __future__ import annotations

import concurrent.futures as cf
import re
import threading
import time
from dataclasses import dataclass, field

from .. import checks
from ..checks.parse import Material, find_cites
from .llm import LLM, Cancelled
from .prompts import Prompts

MAX_FIX = 2
PARALLEL = 2
MINUTES = 45
MUST = set("ABCDEG")
SOURCE_LIMIT = 8
SOURCE_CHARS = 3000
_FIX_LINE = re.compile(r"^\s*(\d+)\s*[.．、]\s*(.*)$")


class BudgetStop(Exception):
    """调用次数或时间到了上限。"""


@dataclass
class Budget:
    max_calls: int
    minutes: int = MINUTES
    clock: object = time.monotonic
    calls: int = 0
    queue_s: float = 0.0
    started: float = field(default=0.0)

    def __post_init__(self):
        self.started = self.clock()
        self._lock = threading.Lock()

    def take(self) -> None:
        with self._lock:
            if self.calls >= self.max_calls:
                raise BudgetStop("calls")
            if self.clock() - self.started - self.queue_s > self.minutes * 60:
                raise BudgetStop("minutes")
            self.calls += 1

    def queued(self, ms: int | None) -> None:
        if ms:
            with self._lock:
                self.queue_s += ms / 1000


@dataclass
class Progress:
    status: str = "running"
    step_index: int = 0
    step_total: int = 0
    current: str | None = None
    queue_wait_ms: int | None = None

    def value(self) -> dict:
        return {"status": self.status, "step_index": self.step_index, "step_total": self.step_total,
                "current": self.current, "queue_wait_ms": self.queue_wait_ms}


@dataclass
class Checked:
    text: str
    problems: list[dict]          # 修改后仍然有的 must_fix 问题（每条带所在行）
    rounds: int


def clean_output(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text)
    lines = text.splitlines()
    while lines and lines[0].startswith("# "):
        lines.pop(0)
    return "\n".join(lines).strip()


def _same(a: str, b: str) -> bool:
    return re.sub(r"\s+", "", a or "") == re.sub(r"\s+", "", b or "")


class Runner:
    def __init__(self, *, llm: LLM, prompts: Prompts, params: dict, materials: checks.MaterialSet, task_id: str,
                 budget: Budget, progress: Progress, kind: str = "excerpt", parallel: int = PARALLEL):
        self.llm = llm
        self.prompts = prompts
        self.params = params
        self.materials = materials
        self.task_id = task_id
        self.budget = budget
        self.progress = progress
        self.kind = kind
        self.parallel = parallel
        self.calls: list[dict] = []
        self.fixes: list[dict] = []
        self._lock = threading.Lock()

    # ---------- 调用 ----------

    def call(self, system: str, user: str, step: str, obj: str) -> str:
        if self.llm.cancel.is_set():
            raise Cancelled()
        self.budget.take()
        reply = self.llm.chat(system, user, self.params, self.task_id)
        self.budget.queued(reply.queue_wait_ms)
        with self._lock:
            self.progress.queue_wait_ms = reply.queue_wait_ms
            self.calls.append({"步骤": step, "对象": obj, "耗时秒": round(reply.elapsed_s, 1),
                               "输入字数": len(system) + len(user), "输入token": reply.prompt_tokens,
                               "输出token": reply.completion_tokens, "结束原因": reply.finish_reason,
                               "排队毫秒": reply.queue_wait_ms})
        return clean_output(reply.text)

    def map(self, fn, items: list) -> list:
        """并行度 2 跑 fn(item)；任何一个抛 Cancelled / BudgetStop 就让其余的不再发出，并把异常抛给调用方。"""
        out: list = [None] * len(items)
        first_stop: list[BaseException] = []
        with cf.ThreadPoolExecutor(max_workers=self.parallel) as ex:
            futs = {ex.submit(self._guarded, fn, it, first_stop): i for i, it in enumerate(items)}
            for f in cf.as_completed(futs):
                out[futs[f]] = f.result()
        if first_stop:
            exc = first_stop[0]
            exc.partial = out          # 已完成的结果交给调用方保存（Spec 9.1：到达上限时保存已完成的部分）
            raise exc
        return out

    def _guarded(self, fn, item, first_stop: list):
        if first_stop:
            return None
        try:
            return fn(item)
        except (Cancelled, BudgetStop) as e:
            with self._lock:
                if not first_stop:
                    first_stop.append(e)
            return None

    # ---------- 写一步并核对、修改 ----------

    def write_checked(self, step: str, user: str, obj: str, *, expand=None, sources: str = "") -> Checked:
        """调一次 step，核对，有问题只把问题句交回"修改"（最多 2 轮）。expand：把模型输出转成核对用的写法
        （摘要步骤里出处只写位置，程序补材料名）。sources：修改时附上的本步原文（摘要步骤的原文段）。"""
        text = self.call(self.prompts.system(step), user, step, obj)
        text = expand(text) if expand else text
        rounds = 0
        for rnd in range(MAX_FIX):
            bad = self.problem_lines(text)
            if not bad:
                break
            with self._lock:
                self.fixes.append({"对象": obj, "轮次": rnd + 1, "问题": [p["class"] + " " + p["message"]
                                                                       for _, _, ps in bad for p in ps]})
            req = self.fix_request(bad, sources)
            reply = self.call(self.prompts.system("修改", extra=step), req, step + "修改", obj)
            new = self.apply_fixes(text, bad, reply, expand)
            rounds += 1
            if _same(new, text):
                break
            text = new
        remaining = [dict(p, line=line) for _, line, ps in self.problem_lines(text) for p in ps]
        return Checked(text, remaining, rounds)

    def problem_lines(self, text: str) -> list[tuple[int, str, list[dict]]]:
        out = []
        for i, line in enumerate(text.splitlines()):
            if not line.strip():
                continue
            check, _ = checks.check_text(line, self.materials, self.kind)
            ps = [p for p in check["problems"] if p["severity"] == "must_fix" and p["class"] in MUST]
            if ps:
                out.append((i, line, ps))
        return out

    def fix_request(self, bad: list, sources: str) -> str:
        lines = ["【有问题的句子】"]
        for n, (_, line, ps) in enumerate(bad, 1):
            lines.append(f"{n}. {line}")
            lines += [f"   问题 {p['class']}：{p['message']}" for p in ps]
        lines.append("\n【相关原文】")
        lines.append(self.related_sources(bad) or "（无）")
        if sources:
            lines.append("\n【本步原文】\n" + sources)
        lines.append("\n【可用的材料名】\n" + "、".join(sorted(self.materials.names())))
        return "\n".join(lines)

    def related_sources(self, bad: list) -> str:
        """问题句所引的位置、问题说明里"实际在"的位置，各取原文。"""
        seen: list[tuple[str, str]] = []
        names = sorted(self.materials.names(), key=len, reverse=True)
        for _, line, ps in bad:
            for c in find_cites(line):
                for it in c.items:
                    seen.append((it.name, it.text()))
            for p in ps:
                for name in names:
                    for m in re.finditer(re.escape(name) + r" (第[0-9]+[页段行]|[^ 、，,]+![A-Z]+[0-9]+)", p["message"]):
                        seen.append((name, f"{name} {m.group(1)}"))
        out, done = [], set()
        for name, label in seen:
            if label in done or len(out) >= SOURCE_LIMIT:
                continue
            done.add(label)
            m: Material | None = self.materials.get(name)
            if m is None or m.units is None:
                continue
            cites = find_cites(f"〔{label}〕")
            if not cites or not cites[0].items:
                continue
            body = m.text_at(cites[0].items[0].loc)
            if body:
                out.append(f"=== {label} ===\n{body[:SOURCE_CHARS]}")
        return "\n\n".join(out)

    @staticmethod
    def apply_fixes(text: str, bad: list, reply: str, expand=None) -> str:
        got: dict[int, str] = {}
        for line in reply.splitlines():
            m = _FIX_LINE.match(line)
            if m and m.group(2).strip():
                got[int(m.group(1))] = m.group(2).rstrip()
        lines = text.splitlines()
        for n, (i, old, _) in enumerate(bad, 1):
            if n in got:
                new = got[n]
                if old.lstrip().startswith(("- ", "|")) and not new.lstrip().startswith(("- ", "|")):
                    new = old[:len(old) - len(old.lstrip())] + old.lstrip()[:2] + new   # 补回列表或表格的行首
                lines[i] = expand(new) if expand else new
        return "\n".join(lines)
