"""识别队列（T12；Spec 第 7 节）：对一个假 395 跑正常完成、中断续做、395 停机恢复、取消、401、503 / 5xx / 400，
以及发送过程中系统临时目录无新增文件、请求里不带 dewatermark。"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
import tempfile
import threading
import time

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient

from lawbench.app import create_app
from lawbench.case import gate
from lawbench.config import REPO_ROOT, Config
from lawbench.ocr import render

from conftest import ServerThread, closed_port, servers
from test_api_case import fail, ok

TOKEN = "o" * 40
KEY = "sk-test-ocr-key"
PDF = REPO_ROOT / "tests" / "fixtures" / "criminal-01" / "讯问笔录.pdf"
JPG = REPO_ROOT / "tests" / "fixtures" / "criminal-01" / "转账截图.jpg"


def expected_md(png: bytes) -> str:
    return f"识别文本 {hashlib.sha256(png).hexdigest()[:12]}"


class Fake395:
    """假 395：/health 和 /v1/ocr/page。每个请求记查询参数、Key、图片哈希；script 里的状态码依次先返回。"""

    def __init__(self):
        self.up = True
        self.calls: list[dict] = []
        self.script: list[tuple[int, dict]] = []
        self.hold = threading.Event()          # 设了 block 时，请求等到 hold 被 set 才返回
        self.block = False
        self.arrived = threading.Event()
        self.lock = threading.Lock()
        self.markdown: str | None = None       # 设了就固定返回这段识别文本

        async def health(request: Request):
            return JSONResponse({"status": "ok"}) if self.up else Response(status_code=503)

        async def page(request: Request):
            body = await request.body()
            sha = hashlib.sha256(body).hexdigest()
            with self.lock:
                self.calls.append({"query": dict(request.query_params), "auth": request.headers.get("authorization"),
                                   "sha": sha, "ctype": request.headers.get("content-type"), "t": time.monotonic()})
                step = self.script.pop(0) if self.script else None
            self.arrived.set()
            if self.block:
                import anyio
                await anyio.to_thread.run_sync(lambda: self.hold.wait(20))
            if step:
                code, headers = step
                return JSONResponse({"error": {"code": "X", "message": "x"}}, status_code=code, headers=headers)
            md = self.markdown if self.markdown is not None else f"识别文本 {sha[:12]}"
            return JSONResponse({"markdown": md, "unclear": 0, "elapsed_ms": 1,
                                 "backend": "fake", "image_png_base64": None})

        self.app = Starlette(routes=[Route("/health", health), Route("/v1/ocr/page", page, methods=["POST"])])

    def page_shas(self) -> list[str]:
        with self.lock:
            return [c["sha"] for c in self.calls]


class Env:
    def __init__(self, tmp: pathlib.Path, prep_url: str, files: dict[str, pathlib.Path], key: str | None = KEY):
        self.appdata = pathlib.Path(tempfile.mkdtemp(prefix="lbocr-"))
        getter = key if callable(key) else (lambda: key)
        self.app = create_app(Config(token=TOKEN, appdata=self.appdata), key_getter=getter)
        self.st = self.app.state.lb
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.client.headers["Authorization"] = f"Bearer {TOKEN}"
        s = ok(self.client.get("/api/settings"), "settings")
        s["servers"] = servers("http://127.0.0.1:9/v1", None, prep_url, None)   # 不给所外地址：测试不碰真实网络
        ok(self.client.put("/api/settings", json=s), "settings")
        self.root = tmp / "张某甲诈骗案"
        for rel, src in files.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, self.root / rel)
        self.case_id = ok(self.client.post("/api/case/open", json={"path": str(self.root)}), "case_open")["case_id"]
        ok(self.client.post("/api/materials/scan", json={"case_id": self.case_id}), "materials_scan")
        self.st.ocr.probe_seconds = 0.3

    def material(self, name: str) -> dict:
        return next(m for m in self.st.materials.index(self.case_id)["materials"] if m["name"] == name)

    def submit(self, mid: str, pages: list[int], dewatermark: bool = False) -> dict:
        return ok(self.client.post("/api/ocr/jobs", json={"case_id": self.case_id, "material_id": mid,
                                                          "pages": pages, "dewatermark": dewatermark}), "ocr_submit")

    def jobs(self) -> list[dict]:
        return ok(self.client.get("/api/ocr/jobs", params={"case_id": self.case_id}), "ocr_list")["jobs"]

    def wait(self, job_id: str, statuses: tuple, timeout: float = 30) -> dict:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            j = next(x for x in self.jobs() if x["job_id"] == job_id)
            if j["status"] in statuses:
                return j
            time.sleep(0.1)
        raise AssertionError(f"任务没到 {statuses}：{j}")

    def pages(self, job_id: str) -> dict[int, tuple]:
        con = sqlite3.connect(str(self.root / "工作区" / "case.db"))
        try:
            return {r[0]: r[1:] for r in con.execute(
                "SELECT page_no, status, attempts, error, result_path FROM ocr_pages WHERE job_id = ?", (job_id,))}
        finally:
            con.close()

    def text(self, m: dict) -> str:
        return (self.root / "工作区" / "材料" / "文本" / f"{m['rel_path']}.md").read_text(encoding="utf-8")

    def close(self):
        self.st.ocr.stop()
        self.client.close()
        shutil.rmtree(self.appdata, ignore_errors=True)


@pytest.fixture
def fake():
    f = Fake395()
    with ServerThread(f.app) as srv:
        f.url = srv.url
        yield f
        f.hold.set()


@pytest.fixture
def env(tmp_path, fake):
    e = Env(tmp_path, fake.url, {"卷一/讯问笔录.pdf": PDF, "卷一/转账截图.jpg": JPG})
    yield e
    e.close()


def rendered(path: pathlib.Path, kind: str, n: int) -> list[bytes]:
    return [render.render_png(path, kind, i) for i in range(1, n + 1)]


# ---------------------------------------------------------------- 1. 正常完成

def test_normal_completion_merges_text_and_index(env, fake):
    m = env.material("讯问笔录")
    assert m["pages_need_ocr"] == [1, 2, 3] and m["is_ocr"] == "none"
    env.st.ocr.start()
    v = env.submit(m["material_id"], [1, 2, 3], dewatermark=True)
    assert v["pages"] == 3 and v["estimated_minutes"] >= 1
    j = env.wait(v["job_id"], ("done",))
    assert (j["total"], j["done"], j["failed"], j["pause_reason"], j["name"]) == (3, 3, 0, None, "讯问笔录")
    pngs = rendered(PDF, "pdf", 3)
    for i, png in enumerate(pngs, 1):                                  # 每页结果落在自己的页号下
        f = env.root / "工作区" / "材料" / "识别页" / m["material_id"] / f"{i}.md"
        assert f.read_text(encoding="utf-8").strip() == expected_md(png)
    text = env.text(m)
    for i, png in enumerate(pngs, 1):
        assert f"【第{i}页】\n> 识别所得\n{expected_md(png)}" in text
    assert "（识别所得，3页）" in text and "（本页需识别）" not in text
    m2 = env.material("讯问笔录")
    assert (m2["is_ocr"], m2["status"], m2["pages_need_ocr"]) == ("full", "parsed", [])
    # 第一版不去水印：请求里没有 dewatermark，任务记 0；Key 走 Bearer；图片是 PNG
    assert all(c["query"] == {} and c["auth"] == f"Bearer {KEY}" and c["ctype"] == "image/png" for c in fake.calls)
    con = sqlite3.connect(str(env.root / "工作区" / "case.db"))
    assert con.execute("SELECT dewatermark FROM ocr_jobs").fetchone()[0] == 0
    con.close()


def test_image_material(env, fake):
    m = env.material("转账截图")
    env.st.ocr.start()
    v = env.submit(m["material_id"], [1])
    env.wait(v["job_id"], ("done",))
    assert "> 识别所得" in env.text(m) and env.material("转账截图")["is_ocr"] == "full"


def test_submit_validation(env):
    m = env.material("讯问笔录")
    fail(env.client.post("/api/ocr/jobs", json={"case_id": env.case_id, "material_id": m["material_id"],
                                                 "pages": [4], "dewatermark": False}), "ocr_submit", "INVALID_ARGUMENT")
    fail(env.client.post("/api/ocr/jobs", json={"case_id": env.case_id, "material_id": "M0999",
                                                 "pages": [1], "dewatermark": False}), "ocr_submit", "MATERIAL_NOT_FOUND")
    fail(env.client.post("/api/ocr/jobs/J-20261001000000-abcd/cancel"), "ocr_cancel", "TASK_NOT_FOUND")


# ---------------------------------------------------------------- 2. 中途退出 / 杀掉后再启动

def test_resume_after_app_exit_without_resending_done_pages(env, fake):
    m = env.material("讯问笔录")
    fake.block = True                                                  # 第一页发出后卡住
    env.st.ocr.start()
    v = env.submit(m["material_id"], [1, 2, 3])
    assert fake.arrived.wait(10)
    env.st.ocr.stop()                                                  # 退出软件：正在发送的页作废
    j = next(x for x in env.jobs() if x["job_id"] == v["job_id"])
    assert (j["status"], j["pause_reason"]) == ("paused", "app_exit")
    assert all(p[0] in ("pending", "done") for p in env.pages(v["job_id"]).values())
    fake.block = False
    fake.hold.set()
    env.st.ocr.start()                                                 # 重新打开：从未完成的页继续
    env.wait(v["job_id"], ("done",))
    pngs = rendered(PDF, "pdf", 3)
    shas = fake.page_shas()
    for png in pngs:
        assert hashlib.sha256(png).hexdigest() in shas
    # 退出时在途的页（最多 concurrency 页）作废后重发一次；任何一页最多发两次，没有页被重复写成两份结果
    assert len(shas) <= 3 + env.st.ocr.concurrency
    assert all(shas.count(h) <= 2 for h in set(shas))


def test_resume_after_hard_kill_state(env, fake):
    """模拟硬退出：任务停在 running、某页停在 sending、某页已完成。再启动后已完成的页不重发、不重复计数。"""
    m = env.material("讯问笔录")
    v = env.submit(m["material_id"], [1, 2, 3])                        # 未 start：只入库
    pngs = rendered(PDF, "pdf", 3)
    rel = f"工作区/材料/识别页/{m['material_id']}/1.md"
    gate.write_bytes(str(env.root), rel, (expected_md(pngs[0]) + "\n").encode("utf-8"))
    con = sqlite3.connect(str(env.root / "工作区" / "case.db"))
    with con:
        con.execute("UPDATE ocr_pages SET status='done', result_path=? WHERE job_id=? AND page_no=1", (rel, v["job_id"]))
        con.execute("UPDATE ocr_pages SET status='sending' WHERE job_id=? AND page_no=2", (v["job_id"],))
        con.execute("UPDATE ocr_jobs SET status='running', done=1 WHERE job_id=?", (v["job_id"],))
    con.close()
    env.st.ocr._jobs.clear()                                           # 新进程：内存里什么都没有
    env.st.ocr.start()
    j = env.wait(v["job_id"], ("done",))
    assert (j["done"], j["failed"]) == (3, 0)
    assert hashlib.sha256(pngs[0]).hexdigest() not in fake.page_shas()  # 已完成的第 1 页没有重发
    assert sorted(fake.page_shas()) == sorted(hashlib.sha256(p).hexdigest() for p in pngs[1:])


# ---------------------------------------------------------------- 3. 395 停机后恢复

def test_prep_down_then_back(tmp_path):
    port = closed_port()
    f = Fake395()
    e = Env(tmp_path, f"http://127.0.0.1:{port}", {"卷一/讯问笔录.pdf": PDF})
    try:
        m = e.material("讯问笔录")
        e.st.ocr.start()
        v = e.submit(m["material_id"], [1, 2])
        j = e.wait(v["job_id"], ("paused",))
        assert j["pause_reason"] == "prep_down"
        with ServerThread(f.app, port=port):                           # 395 恢复
            j = e.wait(v["job_id"], ("done",))
        assert j["done"] == 2
    finally:
        e.close()


def test_submit_while_prep_down_shows_waiting_then_resumes(tmp_path):
    """395 已经连不上时再提交的任务，列表上直接是"等待 395 恢复"，不是"排队中"；恢复后两个任务都做完
    （T12 复核 NOTE 2：原来 _pause_all 只暂停当时在内存里的任务）。"""
    port = closed_port()
    f = Fake395()
    e = Env(tmp_path, f"http://127.0.0.1:{port}", {"卷一/讯问笔录.pdf": PDF})
    try:
        m = e.material("讯问笔录")
        e.st.ocr.start()
        first = e.submit(m["material_id"], [1])["job_id"]
        e.wait(first, ("paused",))
        second = e.submit(m["material_id"], [2])["job_id"]
        j = next(x for x in e.jobs() if x["job_id"] == second)
        assert (j["status"], j["pause_reason"]) == ("paused", "prep_down")
        with ServerThread(f.app, port=port):
            assert e.wait(second, ("done",))["done"] == 1
            assert e.wait(first, ("done",))["done"] == 1
    finally:
        e.close()


def _mark_job(env, job_id: str, job_status: str, page_status: str) -> None:
    con = sqlite3.connect(str(env.root / "工作区" / "case.db"))
    with con:
        con.execute("UPDATE ocr_jobs SET status = ? WHERE job_id = ?", (job_status, job_id))
        con.execute("UPDATE ocr_pages SET status = ? WHERE job_id = ?", (page_status, job_id))
    con.close()


def test_next_skips_job_being_finalized(env):
    """某个发送线程正在给任务收尾（finalizing）：_next 不再把它交给别的线程补收尾（T12 第三轮复核 P3，变异 C3）。"""
    q = env.st.ocr
    v = env.submit(env.material("讯问笔录")["material_id"], [1])
    _mark_job(env, v["job_id"], "running", "done")                 # 页都做完了，任务还没标完成
    with q._cv:
        q._jobs[v["job_id"]].finalizing = True
        assert q._next() is None
        q._jobs[v["job_id"]].finalizing = False
        assert q._next() == (q._jobs[v["job_id"]], None)             # 没人在收尾时，交出去补收尾


def test_next_drops_finished_job_from_memory(env):
    """库里已结束的任务（收尾时被 case_open 又放回内存的那种）：_next 读到就出内存（T12 第三轮复核 P3，变异 C7）。"""
    q = env.st.ocr
    v = env.submit(env.material("讯问笔录")["material_id"], [1])
    _mark_job(env, v["job_id"], "done", "done")
    with q._cv:
        assert q._next() is None
        assert v["job_id"] not in q._jobs


# ---------------------------------------------------------------- 4. 取消

def test_cancel_keeps_done_pages_and_drops_in_flight(env, fake):
    m = env.material("讯问笔录")
    env.st.ocr.concurrency = 1
    env.st.ocr.start()
    v = env.submit(m["material_id"], [1, 2, 3])
    end = time.monotonic() + 20
    while env.jobs()[0]["done"] < 1 and time.monotonic() < end:        # 等第 1 页完成
        time.sleep(0.05)
    fake.arrived.clear()
    fake.block = True
    assert fake.arrived.wait(10)                                       # 第 2 页正在发送
    t0 = time.monotonic()
    r = ok(env.client.post(f"/api/ocr/jobs/{v['job_id']}/cancel"), "ocr_cancel")
    assert r == {"job_id": v["job_id"], "status": "cancelled"} and time.monotonic() - t0 < 5
    end = time.monotonic() + 5                                         # 在途请求被断开：发送线程很快放下这一页
    while env.st.ocr._senders and time.monotonic() < end:              # （假 395 要到用例结束才返回）
        time.sleep(0.05)
    assert env.st.ocr._senders == {}
    time.sleep(0.5)
    p = env.pages(v["job_id"])
    assert p[1][0] == "done" and p[2][0] == "cancelled" and p[3][0] == "cancelled"
    j = env.jobs()[0]
    assert (j["status"], j["done"]) == ("cancelled", 1)
    text = env.text(m)
    assert "【第1页】\n> 识别所得" in text and "【第2页】\n（本页需识别）" in text   # 已完成的页保留并合并
    assert env.material("讯问笔录")["is_ocr"] == "partial"


# ---------------------------------------------------------------- 5. 401 / 503 / 5xx / 400

def test_401_pauses_whole_job(env, fake):
    fake.script = [(401, {})]
    m = env.material("讯问笔录")
    env.st.ocr.concurrency = 1                                         # 两路并发时另一页可能已在途并正常完成
    env.st.ocr.start()
    v = env.submit(m["material_id"], [1, 2, 3])
    j = env.wait(v["job_id"], ("paused",))
    assert j["pause_reason"] == "key_invalid" and j["done"] == 0 and j["failed"] == 0
    time.sleep(0.5)
    assert len(fake.calls) == 1                                        # 暂停后不再发
    assert all(p[0] == "pending" for p in env.pages(v["job_id"]).values())


def test_no_key_pauses_without_sending(tmp_path, fake):
    e = Env(tmp_path, fake.url, {"卷一/讯问笔录.pdf": PDF}, key=None)
    try:
        e.st.ocr.start()
        v = e.submit(e.material("讯问笔录")["material_id"], [1])
        assert e.wait(v["job_id"], ("paused",))["pause_reason"] == "key_invalid"
        assert fake.calls == []
    finally:
        e.close()


def test_503_waits_and_retries_without_counting(env, fake):
    fake.script = [(503, {"Retry-After": "1"})]
    m = env.material("讯问笔录")
    env.st.ocr.start()
    v = env.submit(m["material_id"], [1])
    j = env.wait(v["job_id"], ("done",))
    assert len(fake.calls) == 2 and fake.calls[1]["t"] - fake.calls[0]["t"] >= 1.0 and j["failed"] == 0
    assert env.pages(v["job_id"])[1][1] == 0                           # attempts 不计 503


def test_5xx_retried_three_times_then_failed_and_next_page_continues(env, fake):
    fake.script = [(500, {}), (504, {}), (502, {})]
    m = env.material("讯问笔录")
    env.st.ocr.concurrency = 1
    env.st.ocr.start()
    v = env.submit(m["material_id"], [1, 2])
    j = env.wait(v["job_id"], ("partial_failed",))
    p = env.pages(v["job_id"])
    assert p[1][:3] == ("failed", 3, "395 处理出错，已重试 3 次") and p[2][0] == "done"
    assert (j["done"], j["failed"]) == (1, 1)
    assert env.material("讯问笔录")["status"] == "partial"


@pytest.mark.parametrize("code,reason", [(400, "395 无法识别这页图片"), (413, "这页图片太大，395 不接收")])
def test_400_413_page_failed_with_reason(env, fake, code, reason):
    fake.script = [(code, {})]
    m = env.material("讯问笔录")
    env.st.ocr.concurrency = 1
    env.st.ocr.start()
    v = env.submit(m["material_id"], [1, 2])
    env.wait(v["job_id"], ("partial_failed",))
    p = env.pages(v["job_id"])
    assert p[1][0] == "failed" and p[1][2] == reason and p[1][1] == 0 and p[2][0] == "done"


# ---------------------------------------------------------------- 6. 不写临时文件；格式升级重解析后结果还在

def test_no_temp_files_while_sending(env, fake, tmp_path, monkeypatch):
    """发送全程不写临时文件：本进程的 TEMP / TMP 指到一个空目录（别的进程写系统临时目录不干扰），跑完仍是空的。"""
    t = tmp_path / "临时目录"
    t.mkdir()
    for k in ("TEMP", "TMP", "TMPDIR"):
        monkeypatch.setenv(k, str(t))
    monkeypatch.setattr(tempfile, "tempdir", str(t))
    m = env.material("讯问笔录")
    env.st.ocr.start()
    env.wait(env.submit(m["material_id"], [1, 2, 3])["job_id"], ("done",))
    assert len(fake.calls) == 3
    assert list(t.rglob("*")) == []


def test_reparse_after_format_bump_keeps_ocr_text(env, fake):
    """T5 第二轮复核 B：格式版本升级 → 原件没变也重新解析、重写文本；识别结果要合并回去，不能退回占位。"""
    m = env.material("讯问笔录")
    env.st.ocr.start()
    env.wait(env.submit(m["material_id"], [1, 2, 3])["job_id"], ("done",))
    status = env.root / "工作区" / "材料" / "_处理状态.md"
    from lawbench.case import materials as mat_mod
    status.write_text(status.read_text(encoding="utf-8").replace(f"材料文本格式版本：{mat_mod.TEXT_FORMAT_VERSION}", "材料文本格式版本：1"),
                      encoding="utf-8")
    ok(env.client.post("/api/materials/scan", json={"case_id": env.case_id}), "materials_scan")
    text = env.text(m)
    assert text.count("> 识别所得") == 3 and "（本页需识别）" not in text
    assert env.material("讯问笔录")["is_ocr"] == "full"


def test_stale_flag_cleared_after_reocr(env, fake):
    """原件改过 → 旧识别标过期；对新版本重新识别后不再过期。"""
    m = env.material("讯问笔录")
    env.st.ocr.start()
    env.wait(env.submit(m["material_id"], [1])["job_id"], ("done",))
    with open(env.root / "卷一" / "讯问笔录.pdf", "ab") as f:
        f.write(b"\n% changed\n")
    ok(env.client.post("/api/materials/scan", json={"case_id": env.case_id}), "materials_scan")
    lst = ok(env.client.get("/api/materials", params={"case_id": env.case_id}), "materials_list")
    assert next(x for x in lst["materials"] if x["material_id"] == m["material_id"])["stale_ocr"] is True
    env.wait(env.submit(m["material_id"], [1])["job_id"], ("done",))
    lst = ok(env.client.get("/api/materials", params={"case_id": env.case_id}), "materials_list")
    assert next(x for x in lst["materials"] if x["material_id"] == m["material_id"])["stale_ocr"] is False


def test_broken_registry_does_not_block_startup(tmp_path, monkeypatch):
    """注册表读不了：识别队列照样启动（服务不能因此起不来）。"""
    from lawbench.app import create_app
    app = create_app(Config(token=TOKEN, appdata=tmp_path / "ad"), key_getter=lambda: None)
    st = app.state.lb
    monkeypatch.setattr(st.cases, "recent", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    st.ocr.start()
    try:
        assert len(st.ocr._threads) == st.ocr.concurrency + 1
    finally:
        st.ocr.stop()



# ---------------------------------------------------------------- 401 之后 Key 换了、或保存了设置：自动恢复（1323 注记）

def test_key_change_resumes_key_invalid_job(tmp_path, fake):
    key = ["sk-bad"]
    e = Env(tmp_path, fake.url, {"卷一/讯问笔录.pdf": PDF}, key=lambda: key[0])
    try:
        fake.script = [(401, {})]
        e.st.ocr.concurrency = 1
        e.st.ocr.start()
        v = e.submit(e.material("讯问笔录")["material_id"], [1, 2])
        assert e.wait(v["job_id"], ("paused",))["pause_reason"] == "key_invalid"
        time.sleep(1.5)
        assert len(fake.calls) == 1                                    # Key 没变：不重试
        key[0] = "sk-good"                                             # 凭据管理器里换了 Key
        j = e.wait(v["job_id"], ("done",), timeout=20)
        assert j["done"] == 2 and fake.calls[-1]["auth"] == "Bearer sk-good"
    finally:
        e.close()


def test_no_key_then_key_set_resumes(tmp_path, fake):
    key = [None]
    e = Env(tmp_path, fake.url, {"卷一/讯问笔录.pdf": PDF}, key=lambda: key[0])
    try:
        e.st.ocr.start()
        v = e.submit(e.material("讯问笔录")["material_id"], [1])
        assert e.wait(v["job_id"], ("paused",))["pause_reason"] == "key_invalid" and fake.calls == []
        key[0] = KEY
        assert e.wait(v["job_id"], ("done",), timeout=20)["done"] == 1
    finally:
        e.close()


def test_settings_save_resumes_key_invalid_job(env, fake):
    fake.script = [(401, {})]
    env.st.ocr.concurrency = 1
    env.st.ocr.probe_seconds = 3600                                    # 排除定时读 Key 的作用，只看"保存设置"
    env.st.ocr.start()
    v = env.submit(env.material("讯问笔录")["material_id"], [1])
    assert env.wait(v["job_id"], ("paused",))["pause_reason"] == "key_invalid"
    s = ok(env.client.get("/api/settings"), "settings")
    ok(env.client.put("/api/settings", json=s), "settings")
    env.wait(v["job_id"], ("queued", "running", "done"), timeout=3)   # 3 秒内回到排队（P2-4）
    assert env.wait(v["job_id"], ("done",), timeout=20)["done"] == 1



# ---------------------------------------------------------------- T12 复核返修：一个案件出问题不挡别的，发送线程不死

def open_second_case(env, name: str) -> tuple[str, pathlib.Path]:
    root = env.root.parent / name
    (root / "卷一").mkdir(parents=True)
    shutil.copy(PDF, root / "卷一" / "讯问笔录.pdf")
    cid = ok(env.client.post("/api/case/open", json={"path": str(root)}), "case_open")["case_id"]
    ok(env.client.post("/api/materials/scan", json={"case_id": cid}), "materials_scan")
    return cid, root


def submit_in(env, case_id: str, pages: list[int]) -> str:
    m = next(x for x in env.st.materials.index(case_id)["materials"] if x["name"] == "讯问笔录")
    return ok(env.client.post("/api/ocr/jobs", json={"case_id": case_id, "material_id": m["material_id"],
                                                     "pages": pages, "dewatermark": False}), "ocr_submit")["job_id"]


def job_status(env, case_id: str, job_id: str) -> dict:
    jobs = ok(env.client.get("/api/ocr/jobs", params={"case_id": case_id}), "ocr_list")["jobs"]
    return next(x for x in jobs if x["job_id"] == job_id)


def wait_in(env, case_id, job_id, statuses, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        j = job_status(env, case_id, job_id)
        if j["status"] in statuses:
            return j
        time.sleep(0.1)
    raise AssertionError(f"任务没到 {statuses}：{j}")


def test_case_folder_gone_others_continue_then_resume_on_open(env, fake):
    """案件甲的文件夹被移走（移动盘拔了）：线程不死，案件乙照常做完；插回后打开案件甲，接着做完。"""
    cid_b, _ = open_second_case(env, "案件乙")
    ja = submit_in(env, env.case_id, [1, 2])
    time.sleep(1.1)                                                    # 甲的 job_id 一定排在乙前面（挑页按 job_id 顺序）
    jb = submit_in(env, cid_b, [1, 2])
    assert ja < jb
    moved = env.root.parent / "案件甲-拔掉了"
    env.root.rename(moved)
    env.st.ocr.start()
    assert wait_in(env, cid_b, jb, ("done",))["done"] == 2
    assert all(t.is_alive() for t in env.st.ocr._threads)
    moved.rename(env.root)                                             # 插回
    ok(env.client.post("/api/case/open", json={"path": str(env.root)}), "case_open")
    assert wait_in(env, env.case_id, ja, ("done",))["done"] == 2


def test_case_db_locked_20s_others_continue(env, fake):
    """案件甲的 case.db 被别的进程以 BEGIN IMMEDIATE 占住 20 秒：线程不死，案件乙照常做完；放开后甲也做完。"""
    cid_b, _ = open_second_case(env, "案件乙")
    ja = submit_in(env, env.case_id, [1, 2])
    time.sleep(1.1)                                                    # 甲的 job_id 一定排在乙前面（挑页按 job_id 顺序）
    jb = submit_in(env, cid_b, [1, 2])
    assert ja < jb
    hold = sqlite3.connect(str(env.root / "工作区" / "case.db"), timeout=1, isolation_level=None)
    hold.execute("BEGIN IMMEDIATE")
    t0 = time.monotonic()
    try:
        env.st.ocr.start()
        assert wait_in(env, cid_b, jb, ("done",), timeout=19)["done"] == 2
        assert time.monotonic() - t0 < 20
        assert all(t.is_alive() for t in env.st.ocr._threads)
        time.sleep(max(0.0, 20 - (time.monotonic() - t0)))
    finally:
        hold.execute("ROLLBACK")
        hold.close()
    assert wait_in(env, env.case_id, ja, ("done",), timeout=40)["done"] == 2
    assert all(t.is_alive() for t in env.st.ocr._threads)


def test_result_write_failure_stops_after_three(env, fake, monkeypatch):
    """识别结果写不进去（盘满）：计次，同一页最多发 3 次，之后标失败，不无限重发。"""
    from lawbench.ocr import queue as Q
    real = Q.gate.write_bytes

    def full(root, rel, data, op="write"):
        if op == "ocr_result":
            raise OSError(28, "No space left on device")
        return real(root, rel, data, op=op)
    monkeypatch.setattr(Q.gate, "write_bytes", full)
    env.st.ocr.concurrency = 1
    env.st.ocr.start()
    v = env.submit(env.material("讯问笔录")["material_id"], [1])
    j = env.wait(v["job_id"], ("partial_failed",))
    p = env.pages(v["job_id"])[1]
    assert (j["failed"], p[0], p[1], p[2]) == (1, "failed", 3, Q.MSG_WRITE) and len(fake.calls) == 3


def test_ocr_line_like_page_mark_escaped(env, fake):
    """识别文本里整行"【第1页】"：合并时行首加全角空格，不冒充位置标记；"【第9页】伪造"这种行首带标记的行
    是正文，原样保留、不被拆页（formats.md 第 2 节，T12 第二轮复核 P3-B）。"""
    from lawbench.case import texts
    fake.markdown = "【第1页】\n【第9页】伪造\n【2025-03-10 21:14】周立新：钱已经转了\n正文"
    m = env.material("讯问笔录")
    env.st.ocr.start()
    env.wait(env.submit(m["material_id"], [1, 2, 3])["job_id"], ("done",))
    text = env.text(m)
    assert "\n\u3000【第1页】\n" in text
    assert "\n【第9页】伪造\n" in text and "\u3000【第9页】伪造" not in text
    assert "\n【2025-03-10 21:14】周立新：钱已经转了\n" in text
    units = texts.split_units(text, "page")
    assert [u.no for u in units] == [1, 2, 3] and all(u.is_ocr for u in units)


def test_text_layer_line_starting_with_mark_not_split():
    """文字层（T5 写的，不转义）里一行"【第9页】伪造"：合并器只认整行页标记，页数不变、这行原样留在第 1 页
    （T12 第二轮复核 P3-B：原来的行首正则把它拆成独立的第 9 页、原文丢失）。"""
    from lawbench.case import texts
    from lawbench.ocr import merge
    t5 = ("# x\n\n> Source: a.pdf（部分识别，3页）\n\n【第1页】\n文字层第一页\n【第9页】伪造\n\n【第2页】\n"
          "（本页需识别）\n\n【第3页】\n文字层第三页\n")
    new, st = merge.merge_text(t5, {2: "识别出的第二页"})
    assert st == {"pages": 3, "ocr": [2], "pending": []}
    assert "文字层第一页\n【第9页】伪造\n" in new
    assert [u.no for u in texts.split_units(new, "page")] == [1, 2, 3]
    assert merge.merge_text(new, {2: "识别出的第二页"})[0] == new          # 再合并一次不变


# ---------------------------------------------------------------- N60 ②：水印重复行折叠

WM = "仅供办案使用"
WM_BODY = ("讯问笔录（第1次）\n\n时间：2026年1月15日14时20分至16时05分\n\n问：你是否认识吴某？\n\n"
           "答：认识，是在网上认识的，她说想贷款。\n\n编号：LBFX-CRIM01-7Q3Z")
# 真机补测（evidence\T12\real-395.txt）的样子：正文后水印重复 790 行、行间空一行，末尾截断成半行
WM_SAMPLE = WM_BODY + "\n\n" + "\n\n".join([WM] * 790) + "\n\n仅供"


def test_fold_watermark_run_into_one_line_and_note():
    from lawbench.ocr import merge
    out = merge.fold_repeats(WM_SAMPLE)
    assert out == WM_BODY + "\n\n" + WM + "\n（识别结果中该行重复 790 次，已折叠）\n\n仅供"
    assert merge.fold_repeats(out) == out                               # 已折过的再折不变


@pytest.mark.parametrize("n, folded", [(5, False), (6, True)])
def test_fold_threshold_is_more_than_five(n, folded):
    from lawbench.ocr import merge
    md = "正文\n" + "\n".join([WM] * n) + "\n结尾"
    out = merge.fold_repeats(md)
    if folded:
        assert out == f"正文\n{WM}\n（识别结果中该行重复 {n} 次，已折叠）\n结尾"
    else:
        assert out == md


def test_fold_leaves_scattered_long_and_short_table_repeats():
    from lawbench.ocr import merge
    scattered = "\n".join(f"{WM}\n第{i}行正文" for i in range(10))          # 散落的水印：每两行夹一行正文
    assert merge.fold_repeats(scattered) == scattered
    table = "| 问题 | 回答 |\n|---|---|\n" + "\n".join(["| 是 |"] * 5) + "\n是\n是\n是"   # 表格里合法的重复短行
    assert merge.fold_repeats(table) == table
    long = "\n".join(["本页内容系从原卷复印且与原件核对无误特此说明"] * 8)             # 超过 20 字的长行重复不折
    assert merge.fold_repeats(long) == long


def test_watermark_folded_in_material_text_raw_result_kept_and_searchable(env, fake):
    """395 返回正文 + 790 行水印：识别页\\<编号>\\<页号>.md 原样保留，材料文本里只剩一行加注；检索正文照常命中。"""
    fake.markdown = WM_SAMPLE
    m = env.material("讯问笔录")
    env.st.ocr.start()
    env.wait(env.submit(m["material_id"], [1])["job_id"], ("done",))
    raw = (env.root / "工作区" / "材料" / "识别页" / m["material_id"] / "1.md").read_text(encoding="utf-8")
    assert raw.count(WM) == 790 and raw.strip() == WM_SAMPLE
    text = env.text(m)
    assert f"【第1页】\n> 识别所得\n{WM_BODY}\n\n{WM}\n（识别结果中该行重复 790 次，已折叠）\n\n仅供" in text
    assert text.count(WM) == 1
    hits = ok(env.client.get("/api/search", params={"case_id": env.case_id, "q": "网上认识"}),
              "search")["hits"]
    assert len(hits) == 1 and hits[0]["is_ocr"] and "网上认识" in hits[0]["snippet"]


# ---------------------------------------------------------------- T12 第二轮复核 P2-A：在途页写库失败不留孤页

def page_rows(root, job_id):
    con = sqlite3.connect(str(pathlib.Path(root) / "工作区" / "case.db"))
    try:
        return {r[0]: r[1] for r in con.execute("SELECT page_no, status FROM ocr_pages WHERE job_id = ?", (job_id,))}
    finally:
        con.close()


def test_db_locked_while_page_in_flight_recovers_without_reopen(env, fake):
    """395 正处理第 1 页时 case.db 被占 13 秒：写"已完成"（10 秒）和回退待发送（1 秒）都写不进去，页留在库里的
    "发送中"。放开后不重开案件、不重启，_next 发现它不在 claimed 里，改回待发送重发，任务做完（复核员 x1）。"""
    fake.block = True
    env.st.ocr.concurrency = 1
    env.st.ocr.start()
    v = env.submit(env.material("讯问笔录")["material_id"], [1])
    assert fake.arrived.wait(10)
    hold = sqlite3.connect(str(env.root / "工作区" / "case.db"), timeout=1, isolation_level=None)
    hold.execute("BEGIN IMMEDIATE")
    fake.hold.set()
    try:
        time.sleep(13)
    finally:
        hold.execute("ROLLBACK")
        hold.close()
    j = env.wait(v["job_id"], ("done",), timeout=20)
    assert j["done"] == 1 and page_rows(env.root, v["job_id"]) == {1: "done"}
    assert len(fake.calls) == 2                                        # 第一次的结果没写进库，重发一次
    assert all(t.is_alive() for t in env.st.ocr._threads)


def test_folder_moved_while_page_in_flight_then_back(env, fake):
    """395 正处理第 1 页时案件文件夹被移走、4 秒后插回并打开案件：在途那页不成孤页，两页都做完（复核员 x3）。
    不在原路径重建文件夹。"""
    fake.block = True
    env.st.ocr.concurrency = 1
    env.st.ocr.start()
    v = env.submit(env.material("讯问笔录")["material_id"], [1, 2])
    assert fake.arrived.wait(10)
    moved = env.root.parent / "甲-拔掉"
    for _ in range(50):
        try:
            env.root.rename(moved)
            break
        except PermissionError:
            time.sleep(0.1)
    fake.hold.set()
    time.sleep(4)
    assert not env.root.exists()
    assert all(t.is_alive() for t in env.st.ocr._threads)
    moved.rename(env.root)
    ok(env.client.post("/api/case/open", json={"path": str(env.root)}), "case_open")
    assert wait_in(env, env.case_id, v["job_id"], ("done",), timeout=30)["done"] == 2


def test_finalize_db_failure_then_job_still_finishes(env, fake, monkeypatch):
    """所有页都完成后收尾写库失败（库被占超时）：任务不永远停在"识别中"，_next 发现没有待发、没有在途时再收尾。"""
    from lawbench.ocr import queue as Q
    real = Q.OcrQueue._finalize
    n = []

    def flaky(self, *a):
        n.append(1)
        if len(n) == 1:
            raise sqlite3.OperationalError("database is locked")
        return real(self, *a)
    monkeypatch.setattr(Q.OcrQueue, "_finalize", flaky)
    monkeypatch.setattr(Q, "LOCKED_BACKOFF_S", 0.5)
    env.st.ocr.concurrency = 1
    env.st.ocr.start()
    v = env.submit(env.material("讯问笔录")["material_id"], [1])
    assert env.wait(v["job_id"], ("done",), timeout=15)["done"] == 1
    assert len(n) == 2 and len(fake.calls) == 1


def test_settings_save_fast_while_case_db_locked(env, fake):
    """有任务在内存里、它们的 case.db 被占时保存设置不被拖住（T12 第二轮复核 P3-A：原来 21 秒）。"""
    fake.block = True
    env.st.ocr.concurrency = 1
    env.st.ocr.start()
    m = env.material("讯问笔录")
    env.submit(m["material_id"], [1])
    env.submit(m["material_id"], [2])
    assert fake.arrived.wait(10)
    env.st.ocr._bad_key = "x" * 64                                    # 就算有任务因 Key 暂停，也不在请求线程里动库
    hold = sqlite3.connect(str(env.root / "工作区" / "case.db"), timeout=1, isolation_level=None)
    hold.execute("BEGIN IMMEDIATE")
    try:
        s = ok(env.client.get("/api/settings"), "settings")
        t0 = time.monotonic()
        ok(env.client.put("/api/settings", json=s), "settings")
        dt = time.monotonic() - t0
    finally:
        hold.execute("ROLLBACK")
        hold.close()
        fake.hold.set()
    assert dt < 3, dt



# ---------------------------------------------------------------- T12 第三轮复核（N56 ①）：收尾写库失败也能自愈

def job_row(root, job_id):
    con = sqlite3.connect(str(pathlib.Path(root) / "工作区" / "case.db"))
    try:
        return con.execute("SELECT status FROM ocr_jobs WHERE job_id = ?", (job_id,)).fetchone()[0]
    finally:
        con.close()


def test_finalize_db_error_after_pages_done_self_heals(env, fake, monkeypatch):
    """复核员 y1：收尾时（页都完成了）写库失败一次（_other_active 抛 database is locked）：任务留在内存，
    退避后自己收尾成 done，不需要 case_open / 重启。"""
    from lawbench.ocr import queue as Q
    real = Q.OcrQueue._other_active
    n = []

    def flaky(root, mid, jid):
        n.append(1)
        if len(n) == 1:
            raise sqlite3.OperationalError("database is locked")
        return real(root, mid, jid)
    monkeypatch.setattr(Q.OcrQueue, "_other_active", staticmethod(flaky))
    monkeypatch.setattr(Q, "LOCKED_BACKOFF_S", 0.5)
    env.st.ocr.concurrency = 1
    env.st.ocr.start()
    v = env.submit(env.material("讯问笔录")["material_id"], [1])
    assert env.wait(v["job_id"], ("done",), timeout=15)["done"] == 1
    assert len(n) >= 2 and v["job_id"] not in env.st.ocr._jobs
    assert all(t.is_alive() for t in env.st.ocr._threads)


def test_finalize_final_update_locked_12s_self_heals(env, fake, monkeypatch):
    """复核员 y2：合并返回后另一连接 BEGIN IMMEDIATE 占 case.db 12 秒，"标完成"写不进去（10 秒超时）；
    放开后不重开、不重启，任务自己变 done。"""
    from lawbench.ocr import queue as Q
    real_apply = Q.OcrQueue._apply
    held = {}
    monkeypatch.setattr(Q, "LOCKED_BACKOFF_S", 0.5)

    def apply_then_lock(self, case_id, root, material_id, active=None):
        real_apply(self, case_id, root, material_id, active=active)
        if active is not None and "hold" not in held:
            h = sqlite3.connect(str(pathlib.Path(root) / "工作区" / "case.db"), timeout=1,
                                isolation_level=None, check_same_thread=False)
            h.execute("BEGIN IMMEDIATE")
            held["hold"] = h

            def release():
                time.sleep(12)
                h.execute("ROLLBACK")
                h.close()
                held["released"] = time.monotonic()
            threading.Thread(target=release, daemon=True).start()
    monkeypatch.setattr(Q.OcrQueue, "_apply", apply_then_lock)
    env.st.ocr.concurrency = 1
    env.st.ocr.start()
    v = env.submit(env.material("讯问笔录")["material_id"], [1])
    end = time.monotonic() + 30
    while "released" not in held and time.monotonic() < end:
        time.sleep(0.2)
    assert "released" in held
    end = time.monotonic() + 20
    while job_row(env.root, v["job_id"]) != "done" and time.monotonic() < end:
        time.sleep(0.2)
    assert job_row(env.root, v["job_id"]) == "done"
    assert v["job_id"] not in env.st.ocr._jobs and all(t.is_alive() for t in env.st.ocr._threads)


def test_finalizing_guard_no_double_finalize(env, fake, monkeypatch):
    """P3（复核员 C3）：补收尾进行中，另一个发送线程不再挑同一个任务收尾——合并只做一次。"""
    from lawbench.ocr import queue as Q
    real_other, real_apply = Q.OcrQueue._other_active, Q.OcrQueue._apply
    n, merges = [], []

    def flaky(root, mid, jid):
        n.append(1)
        if len(n) == 1:
            raise sqlite3.OperationalError("database is locked")    # 第一次收尾失败：之后由 _next 补收尾
        return real_other(root, mid, jid)

    def slow_apply(self, case_id, root, material_id, active=None):
        if active is not None:
            merges.append(threading.current_thread().name)
            time.sleep(2)                                           # 补收尾的合并慢：另一线程这期间也在挑
        return real_apply(self, case_id, root, material_id, active=active)
    monkeypatch.setattr(Q.OcrQueue, "_other_active", staticmethod(flaky))
    monkeypatch.setattr(Q.OcrQueue, "_apply", slow_apply)
    monkeypatch.setattr(Q, "LOCKED_BACKOFF_S", 0.3)
    env.st.ocr.concurrency = 2
    env.st.ocr.start()
    v = env.submit(env.material("讯问笔录")["material_id"], [1])
    assert env.wait(v["job_id"], ("done",), timeout=20)["done"] == 1
    time.sleep(1)
    assert len(merges) == 1, merges


def test_finished_job_left_in_memory_is_dropped(env, fake):
    """P3（复核员 C7）：库里已结束、却还在内存里的任务（收尾与 case_open 竞争留下的），_next 读到后移出内存，不空转。"""
    env.st.ocr.concurrency = 1
    env.st.ocr.start()
    v = env.submit(env.material("讯问笔录")["material_id"], [1])
    env.wait(v["job_id"], ("done",), timeout=15)
    m = env.material("讯问笔录")
    from lawbench.ocr import queue as Q
    with env.st.ocr._cv:
        env.st.ocr._jobs[v["job_id"]] = Q.Job(v["job_id"], env.case_id, str(env.root), m["material_id"], m["sha256"],
                                              m["rel_path"], m["type"])
        env.st.ocr._cv.notify_all()
    end = time.monotonic() + 5
    while v["job_id"] in env.st.ocr._jobs and time.monotonic() < end:
        time.sleep(0.1)
    assert v["job_id"] not in env.st.ocr._jobs
