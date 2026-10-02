"""识别队列（Spec 第 7 节；契约 case_db.sql 的 ocr_jobs / ocr_pages，api/ocr_submit、ocr_list、ocr_cancel）。

- 任务和每一页的状态都记在所属案件的 case.db：提交时固定案件、材料版本（原件 sha256）和页；切换案件、
  关闭或重启软件后都能接着做。工作台服务启动时扫描"最近案件"里所有案件的未完成任务。
- 两个发送线程（每位律师同时 2 页）；每页在内存里渲染成 PNG 直接发 395，不写临时文件（render.py）。
- 结果写 工作区/材料/识别页/<材料编号>/<页号>.md 再标该页已完成；重发会覆盖同一个文件，写入幂等。
- 出错与中断按 Spec 7.3：连不上 → 全部暂停（等待 395 恢复），每 30 秒探测 /health，恢复后自动继续；
  503 → 按 Retry-After 等待后重试、不计失败；504 / 5xx → 该页最多 3 次；401 → 整个任务暂停，Key 换了
  （探测线程每 30 秒读一次凭据管理器，与出 401 时的 Key 不同）或设置保存后自动恢复；
  400 / 413 → 该页失败附原因；取消 → 未发送的页标已取消，正在发送的请求立即断开，已完成的页保留。
- 整份材料的页都结束（完成、失败或取消）后，把识别结果合并进材料文本、更新检索索引（merge.py）；
  "识别完成"在任务列表里体现为 status=done / partial_failed，由界面轮询后发系统通知（Spec 3.4 U-7）。
- 第一版不去水印（Spec 6.7）：dewatermark 请求照常受理，任务一律记 0，发给 395 的请求不带该参数。
- 日志只记元数据（动作、案件编号、耗时、错误类型），不记材料名和识别文本。
"""
from __future__ import annotations

import hashlib
import math
import os
import sqlite3
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
MSG_WRITE = "识别结果写不进案件文件夹（磁盘已满或没有写权限）"
MAX_WRITE_FAIL = 3
LOCKED_BACKOFF_S = 5.0        # case.db 被占：这个任务 5 秒后再挑，不挡别的案件
ERROR_BACKOFF_S = 30.0


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
    skip_until: float = 0.0                       # 案件暂时打不开（case.db 被占等）：到这个时刻前不挑它
    finalizing: bool = False                      # 某个发送线程正在给它补收尾


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
        self._bad_key: str | None = None        # 出 401 / 没有 Key 时那把 Key 的指纹；Key 换了就恢复 key_invalid 的任务
        self._key_resume_asked = False          # 保存了设置、等探测线程恢复 key_invalid 的任务
        self._prep_resume_left = False          # 395 恢复后有任务没放回排队（库被占），下个探测周期再放
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

    def resume_case(self, case_id: str) -> None:
        """打开案件时调用（案件文件夹在移动盘上、拔掉又插回等）：把该案件里未完成、内存里还没有的任务接着做。"""
        if not self._threads:
            return
        try:
            self._resume_case(case_id, self.cases.root_of(case_id))
        except Exception as e:  # noqa: BLE001 打不开：不影响打开案件本身
            logs.event("ocr", "resume_case", status="fail", case_id=case_id, error=type(e).__name__)
        with self._cv:
            self._cv.notify_all()

    def _resume_case(self, case_id: str, root: str) -> None:
        index = self.materials.index(case_id)
        by_id = {m["material_id"]: m for m in index["materials"]}
        with merge.connect(root) as con:
            rows = [r for r in con.execute(f"SELECT job_id, material_id, material_version FROM ocr_jobs WHERE "
                                           f"status IN ({','.join('?' * len(UNFINISHED))})", UNFINISHED).fetchall()
                    if r[0] not in self._jobs]                             # 正在做的不动
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
        # 395 正连不上时提交的任务直接记"等待 395 恢复"，与已有任务一样由探测线程放回（T12 复核 NOTE 2）
        status, reason = ("paused", "prep_down") if self._prep_down.is_set() else ("queued", None)
        with merge.connect(root) as con:
            # 第一版不去水印：dewatermark 一律记 0（Spec 6.7）
            con.execute("INSERT INTO ocr_jobs (job_id, material_id, material_version, dewatermark, status, "
                        "pause_reason, total, done, failed, created_at, updated_at) "
                        "VALUES (?, ?, ?, 0, ?, ?, ?, 0, 0, ?, ?)",
                        (job_id, m["material_id"], m["sha256"], status, reason, len(pages), t, t))
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
        """挑下一页：按任务提交顺序，跳过暂停中的任务、已被另一个线程领走的页、暂时打不开的案件。
        每个任务单独兜住：一个案件出问题（文件夹没了、case.db 被占或坏了）不挡别的案件（T12 复核 P2-2）。
        持 _cv 调用，job.claimed 就是真正在途的页：库里"发送中"却不在 claimed 的页是写库失败留下的孤页，
        改回待发送；没有待发、没有在途、任务还没结束的（收尾时写库失败）返回 (job, None) 让发送线程收尾
        （T12 第二轮复核 P2-A）。"""
        t = time.monotonic()
        for job in sorted(self._jobs.values(), key=lambda j: j.job_id):
            if job.skip_until > t or job.finalizing:
                continue
            if not os.path.isdir(job.root):                           # 文件夹被移走、移动盘拔了：先放下，重开案件时再接
                self._jobs.pop(job.job_id, None)
                logs.event("ocr", "case_gone", status="fail", case_id=job.case_id)
                continue
            try:
                with merge.connect(job.root, timeout=0.5) as con:
                    st = con.execute("SELECT status FROM ocr_jobs WHERE job_id = ?", (job.job_id,)).fetchone()
                    if st is None or st[0] not in UNFINISHED:          # 已结束（收尾时被 case_open 放回内存的）：出内存
                        self._jobs.pop(job.job_id, None)
                        continue
                    if st[0] not in ("queued", "running"):
                        continue
                    rows = con.execute("SELECT page_no, status FROM ocr_pages WHERE job_id = ? AND "
                                       "status IN ('pending', 'sending') ORDER BY page_no", (job.job_id,)).fetchall()
                    orphans = [p for p, s in rows if s == "sending" and p not in job.claimed]
                    if orphans:
                        con.executemany("UPDATE ocr_pages SET status = 'pending' WHERE job_id = ? AND page_no = ? "
                                        "AND status = 'sending'", [(job.job_id, p) for p in orphans])
                        logs.event("ocr", "orphan_reset", case_id=job.case_id)
                    for page_no, s in rows:
                        if (s == "pending" or page_no in orphans) and page_no not in job.claimed:
                            return job, page_no
                    if not rows and not job.claimed:
                        job.finalizing = True
                        return job, None
            except sqlite3.OperationalError as e:                     # 多半是被占（database is locked）
                job.skip_until = t + LOCKED_BACKOFF_S
                logs.event("ocr", "next", status="fail", case_id=job.case_id, error=type(e).__name__)
            except Exception as e:  # noqa: BLE001
                job.skip_until = t + ERROR_BACKOFF_S
                logs.event("ocr", "next", status="fail", case_id=job.case_id, error=type(e).__name__)
        return None

    def _worker(self) -> None:
        while not self._stop.is_set():
            with self._cv:
                picked = None if self._prep_down.is_set() else self._safe_next()
                if picked is None:
                    self._cv.wait(timeout=1.0)
                    continue
                job, page_no = picked
                if page_no is not None:
                    job.claimed.add(page_no)
                    sender = client395.PageSender(self.net, self.key_getter)
                    self._senders[(job.job_id, page_no)] = sender
            if page_no is None:                                       # 页都结束了而任务没收尾：补一次收尾
                self._finish_stuck(job)
                continue
            try:
                self._process(job, page_no, sender)
            except Exception as e:  # noqa: BLE001 意外错误：该页回到待发送，记日志，不让线程退出（T12 复核 P2-1）
                logs.event("ocr", "page", status="fail", case_id=job.case_id, error=type(e).__name__)
                job.skip_until = time.monotonic() + LOCKED_BACKOFF_S
                try:
                    self._set_page(job.root, job.job_id, page_no, "pending", timeout=1.0)
                except Exception as e2:  # noqa: BLE001 case.db 还是写不了：留在"发送中"，退避期过后 _next 把它改回待发送
                    logs.event("ocr", "page_reset", status="fail", case_id=job.case_id, error=type(e2).__name__)
            finally:
                with self._cv:
                    job.claimed.discard(page_no)
                    self._senders.pop((job.job_id, page_no), None)
                    self._cv.notify_all()

    def _finish_stuck(self, job: Job) -> None:
        try:
            self._finalize(job.case_id, job.root, job.job_id, job.material_id)
        except Exception as e:  # noqa: BLE001 还是写不了库：退避后 _next 再发现、再试
            job.skip_until = time.monotonic() + LOCKED_BACKOFF_S
            logs.event("ocr", "finalize", status="fail", case_id=job.case_id, error=type(e).__name__)
        finally:
            job.finalizing = False

    def _safe_next(self):
        try:
            return self._next()
        except Exception as e:  # noqa: BLE001 case.db 暂时锁住等：下一轮再挑
            logs.event("ocr", "next", status="fail", error=type(e).__name__)
            return None

    def _process(self, job: Job, page_no: int, sender: client395.PageSender) -> None:
        if not os.path.isdir(job.root):                               # 发送前案件文件夹没了
            with self._cv:
                self._jobs.pop(job.job_id, None)
            logs.event("ocr", "case_gone", status="fail", case_id=job.case_id)
            return
        if not job.checked and not self._original_unchanged(job):
            self._finish_pages(job.root, job.job_id, "failed", MSG_CHANGED)
            self._finalize(job.case_id, job.root, job.job_id, job.material_id)
            return
        job.checked = True
        with merge.connect(job.root, timeout=1.0) as con:              # 被占就很快放弃、这个任务退避，不卡住发送线程
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
                self._bad_key = self._key_fp() or ""
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
        try:
            gate.write_bytes(job.root, rel, (result["markdown"].rstrip("\n") + "\n").encode("utf-8"), op="ocr_result")
        except (OSError, ApiError) as e:                              # 盘满、没有写权限：计次，3 次后该页失败，不无限重发
            logs.event("ocr", "write_result", status="fail", case_id=job.case_id, error=type(e).__name__)
            with merge.connect(job.root) as con:
                n = con.execute("UPDATE ocr_pages SET attempts = attempts + 1 WHERE job_id = ? AND page_no = ? "
                                "RETURNING attempts", (job.job_id, page_no)).fetchone()[0]
            if n >= MAX_WRITE_FAIL:
                self._page_failed(job, page_no, MSG_WRITE)
            else:
                self._set_page(job.root, job.job_id, page_no, "pending")
            return
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

    def _set_page(self, root: str, job_id: str, page_no: int, status: str, timeout: float = 10) -> None:
        with merge.connect(root, timeout=timeout) as con:
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
        # 收尾期间任务留在内存、标 finalizing（别的发送线程不再挑它收尾，case_open 也不会再放一份进来）；
        # 标完成写成了才移出内存——中途写库失败时任务还在内存，退避后 _next 发现它"没有待发、没有在途"再收尾
        # （T12 第三轮复核：原来先移出内存，之后写库失败就只能靠 case_open 或重启救回）
        with self._cv:
            job = self._jobs.get(job_id)
            if job is not None:
                job.finalizing = True
        try:
            others = self._other_active(root, material_id, job_id)
            self._apply(case_id, root, material_id, active=others)     # 先合并文本，再标完成
            with merge.connect(root) as con:
                con.execute("UPDATE ocr_jobs SET status = ?, pause_reason = NULL, updated_at = ? WHERE job_id = ? "
                            "AND status IN ('queued', 'running', 'paused')", (final, now(), job_id))
            with self._cv:
                self._jobs.pop(job_id, None)
        finally:
            if job is not None:
                job.finalizing = False
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
        """每秒醒一次；395 连不上时每 probe_seconds 探测一次 /health，有任务因 Key 暂停时每 probe_seconds 读一次 Key。"""
        last_prep = last_key = 0.0
        while not self._stop.wait(timeout=1.0):
            t = time.monotonic()
            if (self._prep_down.is_set() or self._prep_resume_left) and t - last_prep >= self.probe_seconds:
                last_prep = t
                self._probe_prep()
            if self._key_resume_asked:                                # 保存了设置：在这里动库，不卡保存设置的请求
                self._key_resume_asked = False
                self._resume_key_now("settings")
            if self._bad_key is not None and t - last_key >= self.probe_seconds:
                last_key = t
                fp = self._key_fp()
                if fp is not None and fp != self._bad_key:
                    self._resume_key_now("key_changed")

    def _probe_prep(self) -> None:
        try:
            self.net.select("prep", force=True)
        except ApiError:
            return
        self._prep_down.clear()
        # 有案件的库这次写不进去（被占）：它的任务还停在"等待 395 恢复"，下个探测周期再放一次
        self._prep_resume_left = not self._resume_where("pause_reason IN ('prep_down', 'offline')")
        logs.event("ocr", "prep_back")

    def resume_key_invalid(self) -> None:
        """律师保存了设置（Key 可能换了）：有任务因 Key 暂停时，请探测线程（1 秒内）把它们放回排队。
        请求线程里不动 case.db（T12 第二轮复核 P3-A：两个案件 case.db 被占时保存设置曾要 21 秒）。"""
        if self._bad_key is not None:
            self._key_resume_asked = True

    def _resume_key_now(self, why: str) -> None:
        """因 Key 暂停的任务回到排队；若 Key 仍无效，发一页后会再次暂停。有案件的库这次写不进去时，
        下一个探测周期再试（_bad_key 记成空串，任何真实指纹都与它不同）。"""
        self._bad_key = None
        if not self._resume_where("pause_reason = 'key_invalid'"):
            self._bad_key = ""
        logs.event("ocr", "key_resume", error=why)

    def _resume_where(self, cond: str) -> bool:
        """返回是否每个任务都写成了。库超时 1 秒：被占的案件跳过，不拖住其他案件。"""
        ok = True
        for job in list(self._jobs.values()):
            try:
                with merge.connect(job.root, timeout=1.0) as con:
                    con.execute("UPDATE ocr_jobs SET status = 'queued', pause_reason = NULL, updated_at = ? "
                                f"WHERE job_id = ? AND status = 'paused' AND {cond}", (now(), job.job_id))
            except Exception as e:  # noqa: BLE001
                ok = False
                logs.event("ocr", "resume", status="fail", case_id=job.case_id, error=type(e).__name__)
        with self._cv:
            self._cv.notify_all()
        return ok

    def _key_fp(self) -> str | None:
        """当前 Key 的指纹（只在内存里比较，不记日志）；读凭据管理器出错返回 None（不当作"换了"）。"""
        try:
            key = self.key_getter() or ""
        except Exception:  # noqa: BLE001
            return None
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

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
