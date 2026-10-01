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

        async def health(request: Request):
            return JSONResponse({"status": "ok"}) if self.up else Response(status_code=503)

        async def page(request: Request):
            body = await request.body()
            sha = hashlib.sha256(body).hexdigest()
            with self.lock:
                self.calls.append({"query": dict(request.query_params), "auth": request.headers.get("authorization"),
                                   "sha": sha, "ctype": request.headers.get("content-type")})
                step = self.script.pop(0) if self.script else None
            self.arrived.set()
            if self.block:
                import anyio
                await anyio.to_thread.run_sync(lambda: self.hold.wait(20))
            if step:
                code, headers = step
                return JSONResponse({"error": {"code": "X", "message": "x"}}, status_code=code, headers=headers)
            return JSONResponse({"markdown": f"识别文本 {sha[:12]}", "unclear": 0, "elapsed_ms": 1,
                                 "backend": "fake", "image_png_base64": None})

        self.app = Starlette(routes=[Route("/health", health), Route("/v1/ocr/page", page, methods=["POST"])])

    def page_shas(self) -> list[str]:
        with self.lock:
            return [c["sha"] for c in self.calls]


class Env:
    def __init__(self, tmp: pathlib.Path, prep_url: str, files: dict[str, pathlib.Path], key: str | None = KEY):
        self.appdata = pathlib.Path(tempfile.mkdtemp(prefix="lbocr-"))
        self.app = create_app(Config(token=TOKEN, appdata=self.appdata), key_getter=lambda: key)
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
    assert len(shas) <= 4                                              # 最多被作废的那一页重发一次


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
    t0 = time.monotonic()
    j = env.wait(v["job_id"], ("done",))
    assert time.monotonic() - t0 >= 0.9 and j["failed"] == 0
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
    status.write_text(status.read_text(encoding="utf-8").replace("材料文本格式版本：2", "材料文本格式版本：1"),
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
