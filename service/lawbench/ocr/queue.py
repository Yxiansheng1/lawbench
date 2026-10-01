"""识别队列（Spec 第 7 节；契约 case_db.sql 的 ocr_jobs / ocr_pages，api/ocr_submit、ocr_list、ocr_cancel）。

- 任务和每一页的状态都记在所属案件的 case.db：提交时固定案件、材料版本（原件 sha256）和页；切换案件、
  关闭或重启软件后都能接着做。工作台服务启动时扫描"最近案件"里所有案件的未完成任务。
- 两个发送线程（每位律师同时 2 页）；每页在内存里渲染成 PNG 直接发 395，不写临时文件（render.py）。
- 结果写 工作区/材料/识别页/<材料编号>/<页号>.md 再标该页已完成；重发会覆盖同一个文件，写入幂等。
- 出错与中断按 Spec 7.3：连不上 → 全部暂停（等待 395 恢复），每 30 秒探测 /health，恢复后自动继续；
  503 → 按 Retry-After 等待后重试、不计失败；504 / 5xx → 该页最多 3 次；401 → 整个任务暂停；
  400 / 413 → 该页失败附原因；取消 → 未发送的页标已取消，正在发送的请求立即断开，已完成的页保留。
- 整份材料的页都结束（完成、失败或取消）后，把识别结果合并进材料文本、更新检索索引（merge.py）；
  "识别完成"在任务列表里体现为 status=done / partial_failed，由界面轮询后发系统通知（Spec 3.4 U-7）。
- 第一版不去水印（Spec 6.7）：dewatermark 请求照常受理，任务一律记 0，发给 395 的请求不带该参数。
- 日志只记元数据（动作、案件编号、耗时、错误类型），不记材料名和识别文本。
"""
from __future__ import annotations

import hashlib
import math
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

from .. import logs
from ..case import gate
from ..errors import ApiError
from ..search import fts as search_fts
from . import client395, merge, render

CONCURRENCY = 2
PROBE_SECONDS = 30.0
MAX_5XX = 3
PAGES_PER_MINUTE = 6          # G-5：并发 2 时约 6 页 / 分钟（docs/plan/evidence/T11/g5-g6.md）
UNFINISHED = ("queued", "running", "paused")
MSG_5XX = "395 处理出错，已重试 3 次"
MSG_RENDER = "原件无法读取这一页"
MSG_CHANGED = "原件已改动，请重新提交识别"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_job_id() -> str:
    return f"J-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(2)}"


@dataclass
class Job:
    job_id: str
    case_id: str
    root: str
    material_id: str
    version: str
    rel_path: str
    kind: str
    checked: bool = False                        # 本进程里是否已核过原件没改
    claimed: set = field(default_factory=set)     # 正在发送的页号


class OcrQueue:
    def __init__(self, cases, materials, net, key_getter, *, concurrency: int = CONCURRENCY,
                 probe_seconds: float = PROBE_SECONDS):
        self.cases = cases
        self.materials = materials
        self.net = net
        self.key_getter = key_getter
        self.concurrency = concurrency
        self.probe_seconds = probe_seconds
        self._jobs: dict[str, Job] = {}
        self._senders: dict[tuple[str, int], client395.PageSender] = {}
        self._cv = threading.Condition()
        self._stop = threading.Event()
        self._prep_down = threading.Event()
        self._threads: list[threading.Thread] = []
        materials.after_render = merge.remerge_after_scan    # T5 重新生成文本后把识别结果合并回去

    # ================================================================ 启停

    def start(self) -> None:
        """服务启动时调用：恢复所有最近案件里的未完成任务，起发送线程。"""
        if self._threads:
            return
        self._stop.clear()
        try:
            recent = self.cases.recent()
        except Exception as e:  # noqa: BLE001 注册表读不了：服务照常起来，识别队列先空着（新提交照常受理）
            logs.event("ocr", "resume", status="fail", error=type(e).__name__)
            recent = []
        for c in recent:
            if c.get("exists"):
                try:
                    self._resume_case(c["case_id"], c["root"])
                except Exception as e:  # noqa: BLE001 某个案件的 case.db 坏了：跳过它，不影响其他案件
                    logs.event("ocr", "resume_case", status="fail", case_id=c["case_id"], error=type(e).__name__)
        for i in range(self.concurrency):
            t = threading.Thread(target=self._worker, name=f"ocr-{i}", daemon=True)
            t.start()
            self._threads.append(t)
        t = threading.Thread(target=self._prober, name="ocr-probe", daemon=True)
        t.start()
        self._threads.append(t)

    def stop(self) -> None:
        """服务退出时调用：正在发送的页作废（断开、回到待发送），未完成的任务标"已暂停（退出软件）"。"""
        self._stop.set()
        with self._cv:
            senders = list(self._senders.values())
            self._cv.notify_all()
        for s in senders:
            s.cancel()
        for t in self._threads:
            t.join(timeout=10)
        self._threads = []
        for job in list(self._jobs.values()):
            try:
                with merge.connect(job.root) as con:
                    con.execute("UPDATE ocr_pages SET status = 'pending' WHERE job_id = ? AND status = 'sending'",
                                (job.job_id,))
                    con.execute("UPDATE ocr_jobs SET status = 'paused', pause_reason = 'app_exit', updated_at = ? "
                                "WHERE job_id = ? AND status IN ('queued', 'running', 'paused')", (now(), job.job_id))
            except Exception as e:  # noqa: BLE001
                logs.event("ocr", "stop", status="fail", case_id=job.case_id, error=type(e).__name__)
        self._jobs.clear()

    def _resume_case(self, case_id: str, root: str) -> None:
        index = self.materials.index(case_id)
        by_id = {m["material_id"]: m for m in index["materials"]}
        with merge.connect(root) as con:
            rows = con.execute(f"SELECT job_id, material_id, material_version FROM ocr_jobs WHERE status IN "
                               f"({','.join('?' * len(UNFINISHED))})", UNFINISHED).fetchall()
            for job_id, mid, ver in rows:
                # 上次运行中断时"发送中"的页重新发送（Spec 7.2 表）
                con.execute("UPDATE ocr_pages SET status = 'pending' WHERE job_id = ? AND status = 'sending'",
                            (job_id,))
                con.execute("UPDATE ocr_jobs SET status = 'queued', pause_reason = NULL, updated_at = ? "
                            "WHERE job_id = ?", (now(), job_id))
        for job_id, mid, ver in rows:
            m = by_id.get(mid)
            if m is None:
                self._finish_pages(root, job_id, "failed", MSG_CHANGED)
                self._finalize(case_id, root, job_id, mid)
                continue
            self._jobs[job_id] = Job(job_id, case_id, root, mid, ver, m["rel_path"], m["type"])
        if rows:
            logs.event("ocr", "resume", case_id=case_id)

    # ================================================================ 接口

    def submit(self, d: dict) -> dict:
        case_id = d["case_id"]
        root = self.cases.root_of(case_id)
        index = self.materials.index(case_id)
        m = next((x for x in index["materials"] if x["material_id"] == d["material_id"]), None)
        if m is None:
            raise ApiError("MATERIAL_NOT_FOUND")
        if m["type"] not in merge.OCR_TYPES or m["status"] in ("failed", "source_deleted") or m["unit"] != "page":
            raise ApiError("INVALID_ARGUMENT", "material_not_ocrable")
        pages = sorted(set(d["pages"]))
        if pages[-1] > m["unit_count"]:
            raise ApiError("INVALID_ARGUMENT", "page_out_of_range")
        job_id = new_job_id()
        t = now()
        with merge.connect(root) as con:
            # 第一版不去水印：dewatermark 一律记 0（Spec 6.7）
            con.execute("INSERT INTO ocr_jobs (job_id, material_id, material_version, dewatermark, status, "
                        "pause_reason, total, done, failed, created_at, updated_at) "
                        "VALUES (?, ?, ?, 0, 'queued', NULL, ?, 0, 0, ?, ?)",
                        (job_id, m["material_id"], m["sha256"], len(pages), t, t))
            con.executemany("INSERT INTO ocr_pages (job_id, page_no, status, attempts) VALUES (?, ?, 'pending', 0)",
                            [(job_id, p) for p in pages])
        with self._cv:
            self._jobs[job_id] = Job(job_id, case_id, root, m["material_id"], m["sha256"], m["rel_path"], m["type"])
            self._cv.notify_all()
        self._apply(case_id, root, m["material_id"])                  # 材料状态改"识别中"
        logs.event("ocr", "submit", case_id=case_id)
        return {"job_id": job_id, "pages": len(pages),
                "estimated_minutes": max(1, math.ceil(len(pages) / PAGES_PER_MINUTE))}

    def list(self, case_id: str) -> dict:
        root = self.cases.root_of(case_id)
        names = {m["material_id"]: m["name"] for m in self.materials.index(case_id)["materials"]}
        with merge.connect(root) as con:
            rows = con.execute("SELECT job_id, material_id, status, pause_reason, total, done, failed, created_at "
                               "FROM ocr_jobs ORDER BY created_at DESC, job_id DESC").fetchall()
        return {"jobs": [{"job_id": r[0], "material_id": r[1], "name": names.get(r[1], ""), "status": r[2],
                          "pause_reason": r[3], "total": r[4], "done": r[5], "failed": r[6], "created_at": r[7]}
                         for r in rows]}

    def cancel(self, job_id: str) -> dict:
        found = self._locate(job_id)
        if found is None:
            raise ApiError("TASK_NOT_FOUND", "ocr_job")
        case_id, root, mid, status = found
        if status not in UNFINISHED:
            return {"job_id": job_id, "status": status}
        with self._cv:
            self._jobs.pop(job_id, None)
            senders = [s for (j, _p), s in self._senders.items() if j == job_id]
        for s in senders:                                              # 正在发送的请求立即断开
            s.cancel()
        with merge.connect(root) as con:
            con.execute("UPDATE ocr_pages SET status = 'cancelled' WHERE job_id = ? AND status IN "
                        "('pending', 'sending')", (job_id,))
            con.execute("UPDATE ocr_jobs SET status = 'cancelled', pause_reason = NULL, updated_at = ? "
                        "WHERE job_id = ?", (now(), job_id))
        self._apply(case_id, root, mid)                                # 已完成的页保留并合并
        logs.event("ocr", "cancel", case_id=case_id)
        return {"job_id": job_id, "status": "cancelled"}

    def _locate(self, job_id: str):
        job = self._jobs.get(job_id)
        candidates = [(job.case_id, job.root)] if job else \
            [(c["case_id"], c["root"]) for c in self.cases.recent() if c.get("exists")]
        for case_id, root in candidates:
            try:
                with merge.connect(root) as con:
                    row = con.execute("SELECT material_id, status FROM ocr_jobs WHERE job_id = ?",
                                      (job_id,)).fetchone()
            except Exception:  # noqa: BLE001
                continue
            if row:
                return case_id, root, row[0], row[1]
        return None

    # ================================================================ 发送线程

    def _next(self):
        """挑下一页：按任务提交顺序，跳过暂停中的任务和已被另一个线程领走的页。返回 (Job, 页号) 或 None。"""
        for job in sorted(self._jobs.values(), key=lambda j: j.job_id):
            with merge.connect(job.root) as con:
                st = con.execute("SELECT status FROM ocr_jobs WHERE job_id = ?", (job.job_id,)).fetchone()
                if st is None or st[0] not in ("queued", "running"):
                    continue
                for (page_no,) in con.execute("SELECT page_no FROM ocr_pages WHERE job_id = ? AND status = 'pending' "
                                              "ORDER BY page_no", (job.job_id,)):
                    if page_no not in job.claimed:
                        return job, page_no
        return None

    def _worker(self) -> None:
        while not self._stop.is_set():
            with self._cv:
                picked = None if self._prep_down.is_set() else self._safe_next()
                if picked is None:
                    self._cv.wait(timeout=1.0)
                    continue
                job, page_no = picked
                job.claimed.add(page_no)
                sender = client395.PageSender(self.net, self.key_getter)
                self._senders[(job.job_id, page_no)] = sender
            try:
                self._process(job, page_no, sender)
            except Exception as e:  # noqa: BLE001 意外错误：该页回到待发送，记日志，不让线程退出
                logs.event("ocr", "page", status="fail", case_id=job.case_id, error=type(e).__name__)
                self._set_page(job.root, job.job_id, page_no, "pending")
                time.sleep(1.0)
            finally:
                with self._cv:
                    job.claimed.discard(page_no)
                    self._senders.pop((job.job_id, page_no), None)
                    self._cv.notify_all()

    def _safe_next(self):
        try:
            return self._next()
        except Exception as e:  # noqa: BLE001 case.db 暂时锁住等：下一轮再挑
            logs.event("ocr", "next", status="fail", error=type(e).__name__)
            return None

    def _process(self, job: Job, page_no: int, sender: client395.PageSender) -> None:
        if not job.checked and not self._original_unchanged(job):
            self._finish_pages(job.root, job.job_id, "failed", MSG_CHANGED)
            self._finalize(job.case_id, job.root, job.job_id, job.material_id)
            return
        job.checked = True
        with merge.connect(job.root) as con:
            cur = con.execute("UPDATE ocr_pages SET status = 'sending' WHERE job_id = ? AND page_no = ? "
                              "AND status = 'pending'", (job.job_id, page_no))
            if cur.rowcount == 0:                                     # 刚被取消
                return
            con.execute("UPDATE ocr_jobs SET status = 'running', updated_at = ? WHERE job_id = ? AND status = 'queued'",
                        (now(), job.job_id))
        try:
            png = render.render_png(gate.resolve_read(job.root, job.rel_path, op="ocr_render"), job.kind, page_no)
        except (render.RenderError, ApiError, OSError):
            self._page_failed(job, page_no, MSG_RENDER)
            return
        while True:
            try:
                result = sender.send(png)                             # 只在内存里，不落盘
                break
            except client395.Busy as b:                               # 503：等待后重试，不计失败
                if self._wait(b.retry_after, sender):
                    return self._abandon(job, page_no)
            except client395.Cancelled:
                return self._abandon(job, page_no)
            except client395.Offline:
                self._set_page(job.root, job.job_id, page_no, "pending")
                self._pause_all("prep_down")
                return
            except client395.KeyInvalid:
                self._set_page(job.root, job.job_id, page_no, "pending")
                self._pause(job, "key_invalid")
                return
            except client395.PageRejected as r:
                self._page_failed(job, page_no, r.reason)
                return
            except client395.ServerError:
                with merge.connect(job.root) as con:
                    attempts = con.execute("UPDATE ocr_pages SET attempts = attempts + 1 WHERE job_id = ? AND "
                                           "page_no = ? RETURNING attempts", (job.job_id, page_no)).fetchone()[0]
                if attempts >= MAX_5XX:
                    self._page_failed(job, page_no, MSG_5XX)
                    return
        rel = merge.result_rel(job.material_id, page_no)
        gate.write_bytes(job.root, rel, (result["markdown"].rstrip("\n") + "\n").encode("utf-8"), op="ocr_result")
        with merge.connect(job.root) as con:
            cur = con.execute("UPDATE ocr_pages SET status = 'done', result_path = ?, error = NULL WHERE job_id = ? "
                              "AND page_no = ? AND status = 'sending'", (rel, job.job_id, page_no))
            if cur.rowcount:
                con.execute("UPDATE ocr_jobs SET done = done + 1, updated_at = ? WHERE job_id = ?",
                            (now(), job.job_id))
        self._maybe_finish(job)

    def _abandon(self, job: Job, page_no: int) -> None:
        """取消或退出：这一页作废。取消时 cancel() 已把它标为已取消；退出时回到待发送。"""
        with merge.connect(job.root) as con:
            con.execute("UPDATE ocr_pages SET status = 'pending' WHERE job_id = ? AND page_no = ? AND status = 'sending'",
                        (job.job_id, page_no))

    def _wait(self, seconds: float, sender: client395.PageSender) -> bool:
        """等 seconds 秒；期间被取消或服务退出返回 True。"""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self._stop.is_set() or sender._cancelled.is_set():
                return True
            time.sleep(min(0.2, end - time.monotonic()) if end > time.monotonic() else 0)
        return False

    def _original_unchanged(self, job: Job) -> bool:
        try:
            path = gate.resolve_read(job.root, job.rel_path, op="ocr_render")
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            return h.hexdigest() == job.version
        except (ApiError, OSError):
            return False

    # ================================================================ 状态

    def _set_page(self, root: str, job_id: str, page_no: int, status: str) -> None:
        with merge.connect(root) as con:
            con.execute("UPDATE ocr_pages SET status = ? WHERE job_id = ? AND page_no = ? AND status = 'sending'",
                        (status, job_id, page_no))

    def _page_failed(self, job: Job, page_no: int, reason: str) -> None:
        with merge.connect(job.root) as con:
            cur = con.execute("UPDATE ocr_pages SET status = 'failed', error = ? WHERE job_id = ? AND page_no = ? "
                              "AND status = 'sending'", (reason, job.job_id, page_no))
            if cur.rowcount:
                con.execute("UPDATE ocr_jobs SET failed = failed + 1, updated_at = ? WHERE job_id = ?",
                            (now(), job.job_id))
        self._maybe_finish(job)

    def _finish_pages(self, root: str, job_id: str, status: str, reason: str) -> None:
        with merge.connect(root) as con:
            n = con.execute("UPDATE ocr_pages SET status = ?, error = ? WHERE job_id = ? AND status IN "
                            "('pending', 'sending')", (status, reason, job_id)).rowcount
            con.execute("UPDATE ocr_jobs SET failed = failed + ?, updated_at = ? WHERE job_id = ?", (n, now(), job_id))

    def _maybe_finish(self, job: Job) -> None:
        with merge.connect(job.root) as con:
            left = con.execute("SELECT COUNT(*) FROM ocr_pages WHERE job_id = ? AND status IN ('pending', 'sending')",
                               (job.job_id,)).fetchone()[0]
        if left == 0:
            self._finalize(job.case_id, job.root, job.job_id, job.material_id)

    def _finalize(self, case_id: str, root: str, job_id: str, material_id: str) -> None:
        with merge.connect(root) as con:
            row = con.execute("SELECT status, failed FROM ocr_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None or row[0] not in UNFINISHED:
            return
        final = "partial_failed" if row[1] else "done"
        with self._cv:
            self._jobs.pop(job_id, None)
        others = self._other_active(root, material_id, job_id)
        self._apply(case_id, root, material_id, active=others)         # 先合并文本，再标完成
        with merge.connect(root) as con:
            con.execute("UPDATE ocr_jobs SET status = ?, pause_reason = NULL, updated_at = ? WHERE job_id = ? "
                        "AND status IN ('queued', 'running', 'paused')", (final, now(), job_id))
        logs.event("ocr", "job_" + final, case_id=case_id)          # 界面轮询任务列表见到 done 后发系统通知

    def _pause(self, job: Job, reason: str) -> None:
        with merge.connect(job.root) as con:
            con.execute("UPDATE ocr_jobs SET status = 'paused', pause_reason = ?, updated_at = ? WHERE job_id = ? "
                        "AND status IN ('queued', 'running')", (reason, now(), job.job_id))
        logs.event("ocr", "pause", status="fail", case_id=job.case_id, error=reason)

    def _pause_all(self, reason: str) -> None:
        """395 连不上：所有进行中的任务都暂停（等待 395 恢复），由探测线程每 30 秒试一次。"""
        self._prep_down.set()
        for job in list(self._jobs.values()):
            self._pause(job, reason)

    def _prober(self) -> None:
        while not self._stop.wait(timeout=self.probe_seconds if self._prep_down.is_set() else 1.0):
            if not self._prep_down.is_set():
                continue
            try:
                self.net.select("prep", force=True)
            except ApiError:
                continue
            self._prep_down.clear()
            for job in list(self._jobs.values()):
                try:
                    with merge.connect(job.root) as con:
                        con.execute("UPDATE ocr_jobs SET status = 'queued', pause_reason = NULL, updated_at = ? "
                                    "WHERE job_id = ? AND status = 'paused' AND pause_reason IN ('prep_down', 'offline')",
                                    (now(), job.job_id))
                except Exception as e:  # noqa: BLE001
                    logs.event("ocr", "resume", status="fail", case_id=job.case_id, error=type(e).__name__)
            logs.event("ocr", "prep_back")
            with self._cv:
                self._cv.notify_all()

    @staticmethod
    def _other_active(root: str, material_id: str, job_id: str) -> bool:
        with merge.connect(root) as con:
            return con.execute("SELECT 1 FROM ocr_jobs WHERE material_id = ? AND job_id != ? AND status IN "
                               "('queued', 'running', 'paused') LIMIT 1", (material_id, job_id)).fetchone() is not None

    def _apply(self, case_id: str, root: str, material_id: str, active: bool | None = None) -> None:
        """把识别结果合并进材料文本、改 index 条目（持材料锁），再更新检索索引。"""
        try:
            with self.materials._lock(case_id):
                index = self.materials._load_index(root, case_id)
                entry = next((m for m in index["materials"] if m["material_id"] == material_id), None)
                if entry is None or not merge.merge_entry(root, entry, active=active):
                    return
                self.materials._save_index(root, index)
            search_fts.refresh_after_scan(root, case_id, index)
        except Exception as e:  # noqa: BLE001 合并失败不影响任务状态；下次扫描或下个任务完成时会再合并
            logs.event("ocr", "merge", status="fail", case_id=case_id, error=type(e).__name__)
