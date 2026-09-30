"""T3 返修（执行令 致B-ORCH-执行令-T3返修-20260929-1950）逐条回归测试。编号与返修令一致。"""
from __future__ import annotations

import json
import os
import pathlib
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import tomllib

import anyio
import httpx
import pytest

from lawbench import contracts, logs
from lawbench.case import gate
from lawbench.config import REPO_ROOT
from lawbench.errors import MESSAGES, ApiError
from lawbench.net import Net, forward_app
from lawbench.settings import DEFAULTS

from conftest import AUTH, IS_WIN, TOKEN, ServerThread, closed_port, make_junction, servers
from fakes import CHUNK1, Fake6000D

SERVICE_DIR = pathlib.Path(__file__).resolve().parents[1]


def read_logs(appdata: pathlib.Path) -> str:
    logs.close()
    return "".join(p.read_text(encoding="utf-8") for p in (appdata / "logs").glob("*"))


def wait_log(appdata: pathlib.Path, needle: str, timeout: float = 5.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = "".join(p.read_text(encoding="utf-8") for p in (appdata / "logs").glob("*"))
        if needle in text:
            return text
        time.sleep(0.05)
    return read_logs(appdata)


# ---------- R1：坏配置不阻止启动 ----------

@pytest.mark.parametrize("content", ["{坏的 json", json.dumps({"v": 2})])
def test_r1_bad_settings_still_starts(make_client, appdata, content):
    (appdata / "settings.json").write_text(content, encoding="utf-8")
    c = make_client()
    assert c.get("/health").status_code == 200
    r = c.get("/api/settings")
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL"
    assert c.app.state.lb.net._servers == DEFAULTS["servers"]   # Net 用默认地址
    assert c.get("/api/case/recent").status_code == 200          # 其他接口照常


@pytest.mark.parametrize("content", ["{坏的 json", json.dumps({"v": 2, "hint": "", "shared": [], "groups": []})])
def test_r1_bad_capsules_reset_recovers(make_client, appdata, content):
    (appdata / "capsules.json").write_text(content, encoding="utf-8")
    c = make_client()
    assert c.get("/health").status_code == 200
    r = c.get("/api/capsules")
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL"
    default = json.loads((REPO_ROOT / "skills" / "capsules.default.json").read_text(encoding="utf-8"))
    r = c.post("/api/capsules/reset", json={})
    assert r.status_code == 200 and r.json() == {"ok": True, "value": default}
    assert c.get("/api/capsules").json()["value"] == default
    assert "capsules_load" in read_logs(appdata)


# ---------- R2：Windows 设备名 ----------

DEVICE_PATHS = ["NUL", "CON", "COM1", "LPT1", "CONIN$", "CONOUT$", "证据/NUL.txt", "证据/con.txt", "aux.tar.gz",
                "prn ", "Nul.", "com9", "LPT0", "COM¹", "lpt³.log", "证据/CoNoUt$"]


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "案件"
    (r / "证据").mkdir(parents=True)
    (r / "工作区").mkdir()
    logs.setup(tmp_path / "ad")
    return gate.check_root(str(r))


@pytest.mark.parametrize("rel", DEVICE_PATHS)
def test_r2_device_names_read(root, rel):
    with pytest.raises(ApiError) as ei:
        gate.resolve_read(root, rel)
    assert ei.value.code == "OUT_OF_CASE"


@pytest.mark.parametrize("rel", ["工作区/NUL", "工作区/con.txt", "成果/COM1.md", "工作区/临时/LPT1"])
def test_r2_device_names_write(root, rel):
    with pytest.raises(ApiError) as ei:
        gate.write_bytes(root, rel, b"x")
    assert ei.value.code == "OUT_OF_CASE"


@pytest.mark.parametrize("rel", ["证据/console.txt", "证据/com10.txt", "证据/nullable.md", "证据/con-合同.pdf"])
def test_r2_similar_names_allowed(root, rel):
    assert gate.resolve_read(root, rel)


def test_r2_relpath_valueerror_is_denied():
    if not IS_WIN:
        pytest.skip("盘符")
    with pytest.raises(ApiError) as ei:
        gate._relpath("D:\\x", "C:\\y", "t")
    assert ei.value.code == "OUT_OF_CASE"


# ---------- R3：原子写遇文件被占用 ----------

@pytest.mark.skipif(not IS_WIN, reason="Windows 上被打开的文件不能 replace")
def test_r3_replace_retries_while_file_held(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text("old", encoding="utf-8")
    held = open(target, "rb")
    threading.Timer(0.1, held.close).start()
    contracts.atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"new"
    assert not list(tmp_path.glob(".~lb-*"))


@pytest.mark.skipif(not IS_WIN, reason="Windows 上被打开的文件不能 replace")
def test_r3_replace_gives_up_eventually(tmp_path, monkeypatch):
    monkeypatch.setattr(contracts, "REPLACE_WAIT", 0.001)
    target = tmp_path / "x.json"
    target.write_text("old", encoding="utf-8")
    with open(target, "rb"):
        with pytest.raises(PermissionError):
            contracts.atomic_write_bytes(target, b"new")
    assert target.read_text(encoding="utf-8") == "old" and not list(tmp_path.glob(".~lb-*"))


def test_r3_settings_get_put_interleaved(appdata):
    from lawbench.app import create_app
    from lawbench.config import Config
    app = create_app(Config(token=TOKEN, appdata=appdata), key_getter=lambda: None)
    base = DEFAULTS
    results: list = []
    with ServerThread(app) as s:
        def worker(i: int) -> None:
            with httpx.Client(base_url=s.url, headers=AUTH, trust_env=False, timeout=30) as c:
                for j in range(25):
                    try:
                        if (i + j) % 2:
                            body = json.loads(json.dumps(base))
                            body["profile"]["lawyer_name"] = f"律师{i}-{j}"
                            results.append(c.put("/api/settings", json=body).status_code)
                        else:
                            results.append(c.get("/api/settings").status_code)
                    except httpx.HTTPError as e:
                        results.append(type(e).__name__)
        ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    assert len(results) == 200 and set(results) == {200}, {r: results.count(r) for r in set(results)}


# ---------- R4：转发端口被占时进程非零退出 ----------

def test_r4_forward_port_taken_exits_nonzero(tmp_path):
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    fport = blocker.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith("LB_")}
    try:
        p = subprocess.run([sys.executable, "-m", "lawbench", "--port", str(closed_port()), "--token", TOKEN,
                            "--appdata", str(tmp_path / "ad"), "--forward-port", str(fport)],
                           cwd=SERVICE_DIR, env=env, capture_output=True, timeout=60)
    finally:
        blocker.close()
    assert p.returncode != 0
    assert '"module": "forward", "op": "listen", "status": "fail"' in read_logs(tmp_path / "ad")


# ---------- R5：case.db 版本不对拒绝打开；错误日志带原因代号 ----------

def test_r5_case_db_version_mismatch(client, cases_dir, appdata):
    root = cases_dir / "旧版本"
    root.mkdir()
    cid = client.post("/api/case/open", json={"path": str(root)}).json()["value"]["case_id"]
    db = root / "工作区" / "case.db"
    con = sqlite3.connect(db)
    with con:
        con.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
    con.close()
    before = db.read_bytes()
    r = client.post("/api/case/open", json={"path": str(root)}).json()
    assert r["ok"] is False and r["error"]["code"] == "INVALID_ARGUMENT"
    assert db.read_bytes() == before and not list(db.parent.glob("case.db.bak*"))
    assert "INVALID_ARGUMENT:case_db_version" in read_logs(appdata)
    assert cid


def test_r5_error_log_has_reason_code(client, cases_dir, appdata):
    client.post("/api/case/open", json={"path": str(cases_dir / "不存在-LBTEST")})
    text = read_logs(appdata)
    assert "INVALID_ARGUMENT:root_not_dir" in text and "LBTEST" not in text


# ---------- R6：转发失败都记日志；500 不断开连接 ----------

def test_r6_upstream_breaks_mid_stream(tmp_path):
    logs.setup(tmp_path)

    async def upstream(scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                m = await receive()
                await send({"type": m["type"] + ".complete"})
                if m["type"] == "lifespan.shutdown":
                    return
        if scope["path"] == "/v1/models":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})
            return
        while (await receive()).get("more_body"):
            pass
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")]})
        await send({"type": "http.response.body", "body": CHUNK1, "more_body": True})
        raise RuntimeError("上游中途断开")  # uvicorn 直接断开连接

    with ServerThread(upstream) as up:
        net = Net(servers(up.url + "/v1", None, up.url, None))
        with ServerThread(forward_app(net)) as fwd:
            with pytest.raises(httpx.HTTPError):
                with httpx.stream("POST", fwd.url + "/v1/chat/completions", json={"stream": True},
                                  trust_env=False, timeout=10) as r:
                    for _ in r.iter_raw():
                        pass
            text = wait_log(tmp_path, '"module": "forward"')
    rec = [json.loads(line) for line in text.splitlines() if '"module": "forward"' in line]
    assert rec and rec[-1]["status"] == "fail" and rec[-1]["error"] not in (None, "CANCELLED")


def test_r6_other_httpx_error_before_headers(tmp_path):
    logs.setup(tmp_path)

    async def boom(request):
        raise httpx.ReadTimeout("上游不回")

    net = Net(servers("http://127.0.0.1:9/v1", None, "http://127.0.0.1:9", None),
              transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with ServerThread(forward_app(net, transport=httpx.MockTransport(boom))) as fwd:
        r = httpx.post(fwd.url + "/v1/chat/completions", json={}, trust_env=False, timeout=10)
        text = wait_log(tmp_path, '"module": "forward"')
    assert r.status_code == 502 and r.json()["error"]["code"] == "SERVER_UNREACHABLE"
    rec = [json.loads(line) for line in text.splitlines() if '"module": "forward"' in line]
    assert rec and rec[-1]["status"] == "fail" and rec[-1]["error"] == "ReadTimeout"


def test_r6_client_disconnect_mid_stream_not_ok(tmp_path):
    logs.setup(tmp_path)
    f = Fake6000D()
    with ServerThread(f.app()) as up:
        net = Net(servers(up.url + "/v1", None, up.url, None))
        with ServerThread(forward_app(net)) as fwd:
            with httpx.stream("POST", fwd.url + "/v1/chat/completions", json={"stream": True},
                              headers={"Authorization": "Bearer x"}, trust_env=False, timeout=10) as r:
                assert next(r.iter_raw()) == CHUNK1   # 读到第一段就断开
            text = wait_log(tmp_path, '"module": "forward"')
            f.release.set()
    rec = [json.loads(line) for line in text.splitlines() if '"module": "forward"' in line]
    assert rec[-1]["status"] == "fail" and rec[-1]["error"] == "CANCELLED"


def test_r6_500_keeps_connection(appdata, monkeypatch):
    from lawbench.app import create_app
    from lawbench.config import Config
    app = create_app(Config(token=TOKEN, appdata=appdata), key_getter=lambda: None)

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(app.state.lb.cases, "recent", boom)
    with ServerThread(app) as s, httpx.Client(base_url=s.url, headers=AUTH, trust_env=False) as c:
        for _ in range(5):
            r = c.get("/api/case/recent")
            assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL"
            assert c.get("/health").status_code == 200   # 同一条 keep-alive 连接上的下一个请求照常


# ---------- R8：回响应头之前客户端断开，取消上游请求 ----------

def test_r8_cancel_before_headers(tmp_path):
    logs.setup(tmp_path)
    seen: dict = {}

    async def slow_upstream(scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                m = await receive()
                await send({"type": m["type"] + ".complete"})
                if m["type"] == "lifespan.shutdown":
                    return
        if scope["path"] == "/v1/models":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})
            return
        while (await receive()).get("more_body"):
            pass
        t0 = time.monotonic()
        with anyio.move_on_after(3):
            msg = await receive()
            if msg["type"] == "http.disconnect":
                seen["closed_after"] = time.monotonic() - t0
                return
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"late"})

    with ServerThread(slow_upstream) as up:
        net = Net(servers(up.url + "/v1", None, up.url, None))
        with ServerThread(forward_app(net)) as fwd:
            with pytest.raises(httpx.ReadTimeout):
                httpx.post(fwd.url + "/v1/chat/completions", json={}, trust_env=False,
                           timeout=httpx.Timeout(0.5))
            deadline = time.monotonic() + 3
            while "closed_after" not in seen and time.monotonic() < deadline:
                time.sleep(0.05)
            text = wait_log(tmp_path, '"module": "forward"')
    assert seen.get("closed_after", 99) < 1.5, seen
    rec = [json.loads(line) for line in text.splitlines() if '"module": "forward"' in line]
    assert rec and rec[-1]["status"] == "fail" and rec[-1]["error"] == "CANCELLED"


# ---------- R9：转发端口检查 Host、拒绝 Origin ----------

@pytest.fixture
def fwd_env(tmp_path):
    logs.setup(tmp_path)
    f = Fake6000D()
    with ServerThread(f.app()) as up:
        net = Net(servers(up.url + "/v1", None, up.url, None))
        with ServerThread(forward_app(net)) as fwd:
            fwd.fake = f
            yield fwd


@pytest.mark.parametrize("headers", [{"Host": "evil.example"}, {"Host": "127.0.0.1:1"}, {"Host": "127.0.0.1"},
                                     {"Host": "192.168.8.77:8000"}, {"Origin": "http://evil.example"},
                                     {"Origin": "null"}])
def test_r9_host_origin_rejected(fwd_env, headers):
    hits = fwd_env.fake.hits
    r = httpx.get(fwd_env.url + "/v1/models", headers=headers, trust_env=False)
    assert r.status_code == 404 and fwd_env.fake.hits == hits


def test_r9_localhost_host_ok(fwd_env):
    r = httpx.get(fwd_env.url + "/v1/models", headers={"Host": f"localhost:{fwd_env.port}"}, trust_env=False)
    assert r.status_code == 200


# ---------- R10：6000D 地址不能是转发端口自己 ----------

@pytest.mark.parametrize("key,url", [("llm_base_url", "http://127.0.0.1:18765/v1"),
                                     ("llm_alt_base_url", "http://localhost:18765/v1")])
def test_r10_llm_cannot_be_forward_port(make_client, appdata, key, url):
    c = make_client(forward_port=18765)
    s = c.get("/api/settings").json()["value"]
    s["servers"][key] = url
    r = c.put("/api/settings", json=s).json()
    assert r["ok"] is False and r["error"]["code"] == "INVALID_ARGUMENT"
    assert not (appdata / "settings.json").exists()
    with pytest.raises(ApiError):
        Net(DEFAULTS["servers"], forward_port=18765).update(s["servers"])


def test_r10_saved_bad_settings_fallback(make_client, appdata):
    s = json.loads(json.dumps(DEFAULTS))
    s["servers"]["llm_base_url"] = "http://127.0.0.1:18765/v1"
    (appdata / "settings.json").write_text(json.dumps(s), encoding="utf-8")
    c = make_client(forward_port=18765)
    assert c.get("/health").status_code == 200
    assert c.app.state.lb.net._servers == DEFAULTS["servers"]


# ---------- R11：案件根目录 ----------

def test_r11_long_prefix_stripped(client, cases_dir, appdata):
    if not IS_WIN:
        pytest.skip("\\\\?\\ 前缀")
    root = cases_dir / "长前缀"
    root.mkdir()
    r = client.post("/api/case/open", json={"path": "\\\\?\\" + str(root)}).json()
    assert r["ok"] is True
    reg = json.loads((appdata / "cases.json").read_text(encoding="utf-8"))
    assert reg["cases"][0]["root"] == os.path.realpath(root) and not reg["cases"][0]["root"].startswith("\\\\?\\")


def test_r11_drive_root_rejected(client):
    drive = os.path.splitdrive(str(REPO_ROOT))[0] + os.sep if IS_WIN else "/"
    r = client.post("/api/case/open", json={"path": drive}).json()
    assert r["ok"] is False and r["error"]["code"] == "INVALID_ARGUMENT"


def test_r11_root_containing_appdata_rejected(make_client, tmp_path):
    ad = tmp_path / "用户目录" / "AppData" / "lawbench"
    ad.mkdir(parents=True)
    from lawbench.app import create_app
    from lawbench.config import Config
    from starlette.testclient import TestClient
    c = TestClient(create_app(Config(token=TOKEN, appdata=ad), key_getter=lambda: None))
    c.headers.update(AUTH)
    for p in (tmp_path / "用户目录", ad):
        r = c.post("/api/case/open", json={"path": str(p)}).json()
        assert r["ok"] is False and r["error"]["code"] == "INVALID_ARGUMENT", p
    c.close()


# ---------- R12：标准目录某一级已是 junction ----------

@pytest.mark.skipif(not IS_WIN, reason="junction")
def test_r12_template_skips_existing_junction(client, cases_dir, tmp_path, appdata):
    root = cases_dir / "含联接"
    root.mkdir()
    outside = tmp_path / "案件外目录"
    outside.mkdir()
    make_junction(root / "03一审", outside)
    r = client.post("/api/case/open", json={"path": str(root), "template": "civil"}).json()
    assert r["ok"] is True, r
    assert not any(x.startswith("03一审") for x in r["value"]["folders_created"])
    assert "04二审/我方证据" in r["value"]["folders_created"]
    assert list(outside.iterdir()) == []                            # 案件外没有被写入
    reg = json.loads((appdata / "cases.json").read_text(encoding="utf-8"))
    assert reg["cases"][0]["case_id"] == r["value"]["case_id"]      # 案件已登记


# ---------- R13：唯一事实源 ----------

def test_r13_messages_match_contract():
    enum = json.loads((REPO_ROOT / "contracts" / "common.schema.json").read_text(encoding="utf-8"))
    assert set(MESSAGES) == set(enum["$defs"]["error_code"]["enum"])


def test_r13_defaults_match_example():
    """默认设置与契约样例一致；律师姓名、日常办公文件夹、发票抬头在样例里是示例值，默认为空。"""
    ex = json.loads((REPO_ROOT / "contracts" / "examples" / "file_settings.json").read_text(encoding="utf-8"))
    assert not list(contracts.validator("files/settings.schema.json").iter_errors(DEFAULTS))
    for k in ("v", "servers", "defaults", "templates", "ocr_fallback_llm", "converter"):
        assert DEFAULTS[k] == ex[k], k
    assert set(DEFAULTS) == set(ex)
    assert DEFAULTS["profile"] == {"lawyer_name": None} and DEFAULTS["office"] == {"dir": None, "invoice_buyer": None}


def test_r13_logs_reject_unknown_status(tmp_path):
    logs.setup(tmp_path)
    with pytest.raises(ValueError):
        logs.event("x", "y", status="weird")


def test_r13_forward_routes_single_source():
    from lawbench import net
    assert set(net._FORWARD_ROUTES) == {("POST", "/v1/chat/completions"), ("GET", "/v1/models")}


# ---------- R14：keyring 读取出错 ----------

def test_r14_keyring_error_message(make_client):
    f = Fake6000D()
    with ServerThread(f.app()) as up:
        def broken():
            raise RuntimeError("凭据管理器不可用")
        c = make_client()
        c.app.state.lb.key_getter = broken
        s = c.get("/api/settings").json()["value"]
        s["servers"] = servers(up.url + "/v1", None, up.url, None)
        c.put("/api/settings", json=s)
        v = c.post("/api/connection/test", json={"server": "llm"}).json()["value"]
    assert v["reachable"] and v["key_valid"] is None
    assert "Key 暂时无法验证" in v["message"] and "尚未设置" not in v["message"]


# ---------- R15：依赖声明 ----------

def test_r15_dependencies_declared():
    deps = tomllib.loads((SERVICE_DIR / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    names = {d.split(">")[0].split("<")[0].split("=")[0].strip().lower() for d in deps}
    assert {"starlette", "uvicorn", "httpx", "jsonschema", "referencing", "keyring", "anyio"} <= names
    assert not names & {"fastapi", "pyyaml"}
    assert all(">=" in d and "<" in d for d in deps)
