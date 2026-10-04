"""任务单、读取记录、结果清单（Spec 4.1、9.2、20.3、20.8；契约 files/task、files/reads、files/result、
api/task_create、api/tasks_list、core/task_begin、core/progress、core/task_end）。

目录：<案件>/工作区/任务/<task_id>/ 下 task.json、reads.json、result.json、草稿/。
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import threading
from datetime import datetime

from .. import contracts, logs
from ..errors import ApiError
from . import gate, texts
from .registry import CaseRegistry

TASK_DIR = "工作区/任务"
DEFAULT_BUDGET = {"model_calls": 16, "tool_calls": 24, "minutes": 45}  # Spec 9.2（F-RUN-05；2026-10-04 N68 由 8 调为 16）
END_STATUS = {  # core/task_end 的 reason → result.json 的 status
    "completed": "completed", "aborted": "cancelled", "interrupted": "interrupted",
    "max-tokens": "output_limit", "budget": "budget_stopped", "error": "failed", "blocked": "failed",
}
IN_PROGRESS = "进行中.md"
OUTPUTS_REL = "成果/索引.json"
_VERSIONED = re.compile(r"^(?P<title>.+)-v(?P<n>\d+)\.(md|docx)$")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_task_id(kind: str = "T") -> str:
    return f"{kind}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(2)}"


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class TaskStore:
    def __init__(self, cases: CaseRegistry, settings, materials):
        self.cases = cases
        self.settings = settings
        self.materials = materials
        self._lock = threading.Lock()      # 建单、取单（begin）、作废、add_read
        self._where: dict[str, str] = {}  # task_id → case_id
        # 本进程 begin 过的任务 → begin 的时刻（P1-2：重开案件时不把它们当成上次硬退出留下的；P3-3：用时从这里算）
        self._begun: dict[str, datetime] = {}
        self._task_locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        # 分段读的进度（N31）：(任务, 材料, 版本, 单元号) → 从 0 起连续读到了第几个字
        self._parts: dict[tuple, int] = {}
        # 每个会话最新写入的选择（F5：同一秒内建两张时以后写的为准）
        self._latest: dict[str, str] = {}

    def task_lock(self, task_id: str) -> threading.Lock:
        """按任务的锁：result.json、草稿版本号的读-改-写都在这把锁里（P1-3、P2-2）。"""
        with self._guard:
            return self._task_locks.setdefault(task_id, threading.Lock())

    # ---------- 路径与读写 ----------

    @staticmethod
    def rel(task_id: str, name: str = "") -> str:
        if not re.fullmatch(r"[TP]-\d{14}-[0-9a-f]{4}", task_id):
            raise ApiError("TASK_NOT_FOUND", "bad_task_id")
        return f"{TASK_DIR}/{task_id}" + (f"/{name}" if name else "")

    def _write(self, root: str, rel: str, data: dict, schema: str) -> None:
        contracts.validate(schema, "", data)
        gate.write_bytes(root, rel, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"), op="task")

    @staticmethod
    def _read(root: str, rel: str, schema: str) -> dict:
        p = gate.resolve_internal(root, rel, op="task")
        data = contracts.read_json(p)
        contracts.validate(schema, "", data)
        return data

    def locate(self, task_id: str) -> tuple[str, str, dict]:
        """task_id → (case_id, root, task.json)。"""
        rel = self.rel(task_id, "task.json")
        cid = self._where.get(task_id)
        candidates = [cid] if cid else [c["case_id"] for c in self.cases.recent()]
        for case_id in candidates:
            try:
                root = self.cases.root_of(case_id)
            except ApiError:
                continue
            if gate.resolve_internal(root, rel, op="task").is_file():
                self._where[task_id] = case_id
                return case_id, root, self._read(root, rel, "files/task.schema.json")
        raise ApiError("TASK_NOT_FOUND", "task_not_found")

    # ---------- 参数与输入 ----------

    def default_params(self, skill: str | None) -> dict:
        """优先级：Skill 个人预设 > 全局默认（F-PARAM-03；任务单里律师选的参数在 /api/task 直接给出）。"""
        s = self.settings.get()
        p = copy.deepcopy(s["defaults"])
        if skill and skill in s["skill_presets"]:
            p.update(copy.deepcopy(s["skill_presets"][skill]))
        return p

    def input_refs(self, root: str, paths: list[str]) -> list[dict]:
        """界面选用的前序成果：只能是本案 工作区/任务/<任务>/草稿/ 或 成果/ 下的 md 文件。"""
        refs = []
        for i, rel in enumerate(paths, 1):
            parts = rel.split("/")
            ok = (len(parts) == 2 and parts[0] == "成果") or (
                len(parts) == 5 and parts[:2] == ["工作区", "任务"] and parts[3] == "草稿")
            if not ok or not rel.endswith(".md"):
                raise ApiError("INVALID_ARGUMENT", "input_not_output")
            p = gate.resolve_internal(root, rel, op="task_input")
            if not p.is_file():
                raise ApiError("INVALID_ARGUMENT", "input_missing")
            m = _VERSIONED.match(p.name)
            refs.append({"index": i, "title": m.group("title") if m else p.stem, "path": rel,
                         "version": int(m.group("n")) if m else None, "sha256": sha256_file(p)})
        return refs

    def read_input(self, root: str, ref: dict) -> str:
        """读选用的输入；选用后被改过（sha256 不一致）报 INPUT_CHANGED。路径来自界面、已在写任务单时校验过。"""
        p = gate.resolve_internal(root, ref["path"], op="task_input")
        if not p.is_file() or sha256_file(p) != ref["sha256"]:
            raise ApiError("INPUT_CHANGED", "input_changed")
        return p.read_text(encoding="utf-8")

    # ---------- /api/task、/api/tasks ----------

    def create(self, d: dict) -> dict:
        root = self.cases.root_of(d["case_id"])
        task_id = new_task_id("T")
        task = {"v": 1, "task_id": task_id, "case_id": d["case_id"], "kind": "agent", "session_id": d["session_id"],
                "entry": d["entry"], "skill": d["skill"], "step": None,
                "inputs": self.input_refs(root, d["inputs"]), "params": d["params"],
                "budget": copy.deepcopy(DEFAULT_BUDGET), "state": "pending", "created_at": now_iso()}
        with self._lock:
            self._void_pending(root, d["case_id"], d["session_id"])
            self._write(root, self.rel(task_id, "task.json"), task, "files/task.schema.json")
            self._where[task_id] = d["case_id"]
            self._latest[d["session_id"]] = task_id
        logs.event("task", "create", case_id=d["case_id"])
        return {"task_id": task_id}

    def outputs(self, case_id: str) -> dict:
        """GET /api/outputs（契约 1.2，N35⑥）：成果/索引.json 的内容；还没有成果时是空列表。"""
        root = self.cases.root_of(case_id)
        p = gate.resolve_internal(root, OUTPUTS_REL, op="outputs")
        if not p.is_file():
            return {"v": 1, "outputs": []}
        data = contracts.read_json(p)
        contracts.validate("files/outputs_index.schema.json", "", data)
        return data

    def current(self, session_id: str) -> dict:
        """GET /api/task/current（契约 1.2）：该会话当前的选择。会话属于哪个案件请求里没有，按最近打开的案件找。"""
        with self._lock:
            best = None
            for c in self.cases.recent():
                try:
                    root = self.cases.root_of(c["case_id"])
                    t = self._pending_for(root, session_id)
                except ApiError:
                    continue
                if t is not None and (best is None or t["created_at"] > best["created_at"]):
                    best = t
        if best is None:
            return {"selection": None}
        return {"selection": {"task_id": best["task_id"], "entry": best["entry"], "skill": best["skill"],
                              "inputs": [r["path"] for r in best["inputs"]], "params": best["params"],
                              "updated_at": best["created_at"]}}

    def list(self, case_id: str) -> dict:
        root = self.cases.root_of(case_id)
        base = gate.resolve_internal(root, TASK_DIR, op="task")
        out = []
        if base.is_dir():
            for d in sorted(base.iterdir(), key=lambda p: p.name, reverse=True):
                try:
                    task = self._read(root, self.rel(d.name, "task.json"), "files/task.schema.json")
                    res = self._read(root, self.rel(d.name, "result.json"), "files/result.schema.json")
                except (ApiError, FileNotFoundError, contracts.ContractError, ValueError):
                    continue  # 还没开始执行的任务单（没有 result.json）或损坏的记录不列出
                cc = res["citation_check"]
                out.append({"task_id": task["task_id"], "skill": task["skill"], "status": res["status"],
                            "drafts": res["drafts"], "citation_passed": cc["passed"] if cc else None,
                            "finished_at": res["finished_at"], "coverage": res["coverage"],
                            "citation_check": cc})
        return {"tasks": out}

    def _void_pending(self, root: str, case_id: str, session_id: str) -> None:
        """同一会话里更早的待执行任务单一律作废（执行令 0608，P2-7；调用方持 self._lock）。

        契约没有"已作废"状态，不改契约：把那张还没执行过的任务单目录删掉。删之前核对它确实是待执行、属于同一会话、
        目录里只有 task.json（没有草稿、读取记录、结果清单）；不满足就不删，记一条日志（只记任务编号和原因代号）。
        被删的不会留下 result.json，也就不会出现在 /api/tasks 里（注记 0805）。"""
        base = gate.resolve_internal(root, TASK_DIR, op="task")
        if not base.is_dir():
            return
        for d in base.iterdir():
            try:
                t = self._read(root, self.rel(d.name, "task.json"), "files/task.schema.json")
            except (ApiError, FileNotFoundError, contracts.ContractError, ValueError):
                continue
            if t["state"] != "pending" or t["session_id"] != session_id or t["kind"] != "agent":
                continue
            tid = t["task_id"]
            folder = gate.resolve_internal(root, self.rel(tid), op="task_void")
            if sorted(p.name for p in folder.iterdir()) != ["task.json"]:
                logs.event("task", "void", status="denied", case_id=case_id, error=f"NOT_EMPTY:{tid}")
                continue
            gate.delete_work_file(root, self.rel(tid, "task.json"), op="task_void")
            try:
                os.rmdir(folder)  # 空目录；闸门已核对它在 工作区/任务/ 下、不是链接
            except OSError as e:
                logs.event("task", "void", status="fail", case_id=case_id, error=f"{type(e).__name__}:{tid}")
            self._where.pop(tid, None)
            logs.event("task", "void", case_id=case_id)

    # ---------- /core/task/begin ----------

    def begin(self, session_id: str, cwd: str) -> dict:
        case_id, root = self.cases.find_by_root(cwd)
        with self._lock:
            # 契约 1.2（N37）：按该会话当前的选择（待执行的任务单）复制出一个新的执行中任务，
            # 选择本身不消耗、不删除；没有选择就按自由对话默认值新建
            sel = self._pending_for(root, session_id)
            tid = new_task_id("T")
            if sel is not None:
                task = copy.deepcopy(sel)
                task.update(task_id=tid, created_at=now_iso())
            else:
                task = {"v": 1, "task_id": tid, "case_id": case_id, "kind": "agent", "session_id": session_id,
                        "entry": None, "skill": None, "step": None, "inputs": [],
                        "params": self.default_params(None), "budget": copy.deepcopy(DEFAULT_BUDGET),
                        "created_at": now_iso()}
            task["state"] = "running"
            # 先记下"本进程 begin 过"，再写任何文件：重开案件的 mark_abnormal 不会在写到一半时把它当成遗留任务（F1）
            self._begun[tid] = datetime.now().astimezone()
            try:
                self._write(root, self.rel(tid, "task.json"), task, "files/task.schema.json")
                self._write(root, self.rel(tid, "result.json"), {
                    "v": 1, "task_id": tid, "status": "running",
                    "usage": {"model_calls": 0, "tool_calls": 0, "elapsed_s": 0}, "drafts": [],
                    "citation_check": None, "coverage": None, "citations": [], "finished_at": None},
                    "files/result.schema.json")
                self._write(root, self.rel(tid, "reads.json"), {"v": 1, "task_id": tid, "reads": []},
                            "files/reads.schema.json")
            except BaseException:
                # 写到一半失败：它不算"本进程正在执行"，重开案件时应按异常中断处理（T8 第三轮复核 P3）
                self._begun.pop(tid, None)
                raise
            self._where[tid] = case_id
        logs.event("task", "begin", case_id=case_id)
        return {"task_id": tid, "case_id": case_id, "skill": task["skill"], "params": task["params"],
                "budget": task["budget"]}

    def _pending_for(self, root: str, session_id: str) -> dict | None:
        base = gate.resolve_internal(root, TASK_DIR, op="task")
        if not base.is_dir():
            return None
        best = None
        for d in base.iterdir():
            try:
                t = self._read(root, self.rel(d.name, "task.json"), "files/task.schema.json")
            except (ApiError, FileNotFoundError, contracts.ContractError, ValueError):
                continue
            if t["state"] == "pending" and t["session_id"] == session_id and t["kind"] == "agent":
                if best is None or t["created_at"] > best["created_at"] or (
                        t["created_at"] == best["created_at"] and t["task_id"] == self._latest.get(session_id)):
                    best = t  # 同一秒平局：以本进程最后写入的为准（F5）
        return best

    # ---------- 打开案件：上次硬退出的任务标 abnormal ----------

    def mark_abnormal(self, case_id: str) -> int:
        """上次硬退出留下的执行中任务标"异常中断"。整个过程拿 self._lock：和 begin 互斥（F1）。"""
        with self._lock:
            return self._mark_abnormal(case_id)

    def _mark_abnormal(self, case_id: str) -> int:
        root = self.cases.root_of(case_id)
        base = gate.resolve_internal(root, TASK_DIR, op="task")
        n = 0
        if not base.is_dir():
            return 0
        for d in base.iterdir():
            try:
                t = self._read(root, self.rel(d.name, "task.json"), "files/task.schema.json")
            except (ApiError, FileNotFoundError, contracts.ContractError, ValueError):
                continue
            if t["state"] != "running" or t["task_id"] in self._begun:
                continue  # 本进程 begin 过的正在执行，不是上次硬退出留下的（P1-2）
            t["state"] = "abnormal"
            self._write(root, self.rel(t["task_id"], "task.json"), t, "files/task.schema.json")
            try:
                res = self._read(root, self.rel(t["task_id"], "result.json"), "files/result.schema.json")
                res["status"] = "abnormal"
                self._write(root, self.rel(t["task_id"], "result.json"), res, "files/result.schema.json")
            except (ApiError, FileNotFoundError, contracts.ContractError, ValueError):
                pass
            n += 1
        return n

    # ---------- 结果清单、读取记录 ----------

    def result(self, root: str, task_id: str) -> dict:
        return self._read(root, self.rel(task_id, "result.json"), "files/result.schema.json")

    def save_result(self, root: str, res: dict) -> None:
        self._write(root, self.rel(res["task_id"], "result.json"), res, "files/result.schema.json")

    # ---------- 流水线任务（T16；Spec 9.1"任务记录"） ----------

    def begin_pipeline(self, case_id: str, step: str, skill: str, params: dict, budget: dict) -> tuple[str, str]:
        """建一个 P- 任务并直接置为执行中；登记进 _begun，重开案件时不会被当成上次硬退出留下的。"""
        root = self.cases.root_of(case_id)
        tid = new_task_id("P")
        task = {"v": 1, "task_id": tid, "case_id": case_id, "kind": "pipeline", "session_id": None,
                "entry": skill, "skill": skill, "step": step, "inputs": [], "params": params, "budget": budget,
                "state": "running", "created_at": now_iso()}
        with self._lock:
            self._begun[tid] = datetime.now().astimezone()
            try:
                self._write(root, self.rel(tid, "task.json"), task, "files/task.schema.json")
                self._write(root, self.rel(tid, "result.json"), {
                    "v": 1, "task_id": tid, "status": "running",
                    "usage": {"model_calls": 0, "tool_calls": 0, "elapsed_s": 0}, "drafts": [],
                    "citation_check": None, "coverage": None, "citations": [], "finished_at": None},
                    "files/result.schema.json")
            except BaseException:
                self._begun.pop(tid, None)
                raise
            self._where[tid] = case_id
        logs.event("pipeline", "begin", case_id=case_id)
        return tid, root

    def end_pipeline(self, root: str, task_id: str, status: str, *, model_calls: int, drafts: list[dict],
                     citation_check: dict | None, citations: list[dict]) -> None:
        """流水线收尾：task.json 置为已结束，result.json 写状态、用量、草稿、核对结果。"""
        with self.task_lock(task_id):
            task = self._read(root, self.rel(task_id, "task.json"), "files/task.schema.json")
            task["state"] = "finished"
            self._write(root, self.rel(task_id, "task.json"), task, "files/task.schema.json")
            res = self.result(root, task_id)
            started = self._begun.get(task_id)
            elapsed = int((datetime.now().astimezone() - started).total_seconds()) if started else 0
            res.update(status=status, usage={"model_calls": model_calls, "tool_calls": 0, "elapsed_s": elapsed},
                       drafts=drafts, citation_check=citation_check, citations=citations, finished_at=now_iso())
            self.save_result(root, res)
        logs.event("pipeline", "end", status="ok" if status == "completed" else "fail", case_id=task["case_id"],
                   error=None if status == "completed" else status)

    def add_read(self, root: str, task_id: str, rec: dict) -> None:
        with self._lock:
            data = self._read(root, self.rel(task_id, "reads.json"), "files/reads.schema.json")
            data["reads"].append(rec)
            self._write(root, self.rel(task_id, "reads.json"), data, "files/reads.schema.json")

    def read_part(self, task_id: str, m: dict, no: int, start: int, end: int, length: int) -> bool:
        """记下读了单元的 [start, end)；从 0 起连续读到单元末尾时返回 True（只返回一次）。"""
        key = (task_id, m["material_id"], m["sha256"], no)
        with self._guard:
            got = self._parts.get(key, 0)
            if got < 0:
                return False           # 已经算读完、记过了
            if start <= got:
                got = max(got, end)
            if got >= length:
                self._parts[key] = -1
                return True
            self._parts[key] = got
            return False

    def coverage(self, root: str, case_id: str, task_id: str) -> dict:
        """按 reads.json 的实际读取记录计算，不采信模型自报（Spec 9.2）。只认当前版本（sha256）的读取。"""
        index = self.materials.index(case_id)
        reads = self._read(root, self.rel(task_id, "reads.json"), "files/reads.schema.json")["reads"]
        cov = {"total": 0, "fully_read": [], "partially_read": [], "not_read": [], "unreadable": []}
        for m in index["materials"]:
            if m["status"] == "source_deleted":
                continue
            cov["total"] += 1
            if m["status"] == "failed":
                cov["unreadable"].append({"name": m["name"], "reason": m["error"] or "无法处理"})
                continue
            try:
                units = texts.split_units(texts.read_text(root, m), m["unit"])
            except ApiError:
                cov["unreadable"].append({"name": m["name"], "reason": "材料文本不存在"})
                continue
            got: set[int] = set()
            for r in reads:
                if r["material_id"] == m["material_id"] and r["material_version"] == m["sha256"]:
                    got.update(range(r["from"], r["to"] + 1))
            total = texts.total_units(units)
            got &= set(range(1, total + 1))
            got -= {u.no for u in units if u.text.strip() == texts.PENDING_OCR}  # "本页需识别"的占位不算读过（P2-1）
            if total and len(got) >= total:
                cov["fully_read"].append(m["name"])
            elif got:
                cov["partially_read"].append({"name": m["name"], "read_units": len(got), "total_units": total})
            else:
                cov["not_read"].append(m["name"])
        return cov

    # ---------- /core/progress、/core/task/end ----------

    def progress(self, task_id: str, text: str, model_calls: int, tool_calls: int) -> dict:
        """还没 begin 的报 TASK_NOT_FOUND（P3-2）；已结束或异常中断的不写文件、不改用量（P2-4）。"""
        with self.task_lock(task_id):
            case_id, root, task = self.locate(task_id)
            if task["state"] == "pending":
                raise ApiError("TASK_NOT_FOUND", "not_begun")
            if task["state"] != "running":
                return {}
            gate.write_bytes(root, self.rel(task_id, f"草稿/{IN_PROGRESS}"), text.encode("utf-8"), op="task_progress")
            res = self.result(root, task_id)
            res["usage"].update(model_calls=model_calls, tool_calls=tool_calls,
                                elapsed_s=_elapsed(task, self._begun.get(task_id)))
            self.save_result(root, res)
        return {}

    def end(self, task_id: str, reason: str, model_calls: int, tool_calls: int, elapsed_s: int) -> dict:
        """已结束的直接返回已写的状态，不改写（P2-4）；还没 begin 的、已标异常中断的报 TASK_NOT_FOUND
        （契约的返回状态里没有"异常中断"）。"""
        with self.task_lock(task_id):
            return self._end(task_id, reason, model_calls, tool_calls, elapsed_s)

    def _end(self, task_id: str, reason: str, model_calls: int, tool_calls: int, elapsed_s: int) -> dict:
        case_id, root, task = self.locate(task_id)
        if task["state"] == "finished":
            return {"status": self.result(root, task_id)["status"]}
        if task["state"] != "running":
            raise ApiError("TASK_NOT_FOUND", "not_running")
        status = END_STATUS[reason]
        res = self.result(root, task_id)
        res.update(status=status, finished_at=now_iso())
        res["usage"] = {"model_calls": model_calls, "tool_calls": tool_calls, "elapsed_s": elapsed_s}
        res["coverage"] = self.coverage(root, case_id, task_id)
        if not res["drafts"]:
            # 没存过正式草稿：进行中.md 改名为 未完成-<时间>.md（F-RUN-04），由程序保存，不依赖模型
            src = gate.resolve_internal(root, self.rel(task_id, f"草稿/{IN_PROGRESS}"), op="task_end")
            if src.is_file():
                name = f"未完成-{datetime.now().strftime('%Y%m%d%H%M%S')}.md"
                gate.write_bytes(root, self.rel(task_id, f"草稿/{name}"), src.read_bytes(), op="task_end")
                gate.delete_work_file(root, self.rel(task_id, f"草稿/{IN_PROGRESS}"), op="task_end")
        else:
            # 存过正式草稿：进度文件不再保留（T14 派修）；save_draft 时已删过，这里清掉之后 progress 又写出来的
            gate.delete_work_file(root, self.rel(task_id, f"草稿/{IN_PROGRESS}"), op="task_end")
        self.save_result(root, res)
        task["state"] = "finished"
        self._write(root, self.rel(task_id, "task.json"), task, "files/task.schema.json")
        logs.event("task", "end", case_id=case_id, status="ok" if status == "completed" else "fail",
                   error=None if status == "completed" else status)
        return {"status": status}


def _elapsed(task: dict, begun: datetime | None) -> int:
    """从 begin 算起（P3-3）；本进程没记下 begin 时刻的（不会发生在执行中的任务上）退回建单时间。"""
    try:
        start = begun or datetime.fromisoformat(task["created_at"])
        return max(0, int((datetime.now().astimezone() - start).total_seconds()))
    except ValueError:
        return 0
