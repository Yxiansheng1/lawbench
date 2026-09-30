"""T3 第二轮返修（执行令 致B-ORCH-执行令-T3第二轮返修并入T5-20260929-2145）逐条回归测试。编号与返修令一致。"""
from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import time

import anyio
import httpx
import pytest

from lawbench import logs
from lawbench.case import gate
from lawbench.errors import ApiError
from lawbench.net import Net, forward_app
from lawbench.settings import DEFAULTS

from conftest import IS_WIN, TOKEN, ServerThread, closed_port, make_junction, servers

SERVICE_DIR = pathlib.Path(__file__).resolve().parents[1]
BAD_URLS = ["http://127.0.0.1:8x/v1", "http://[::1/v1"]


def read_logs(appdata: pathlib.Path) -> str:
    logs.close()
    return "".join(p.read_text(encoding="utf-8") for p in (appdata / "logs").glob("*"))


# ---------- S1：解析不了的服务器地址 ----------

@pytest.mark.parametrize("key", ["llm_base_url", "prep_base_url", "llm_alt_base_url", "prep_alt_base_url"])
@pytest.mark.parametrize("url", BAD_URLS)
def test_s1_put_unparseable_url_rejected(make_client, appdata, key, url):
    c = make_client()
    s = c.get("/api/settings").json()["value"]
    s["servers"][key] = url
    r = c.put("/api/settings", json=s).json()
    assert r["ok"] is False and r["error"]["code"] == "INVALID_ARGUMENT"
    assert not (appdata / "settings.json").exists()


def test_s1_check_does_not_depend_on_forward_port():
    s = dict(DEFAULTS["servers"], prep_base_url="http://[::1/v1")
    with pytest.raises(ApiError) as ei:
        Net(DEFAULTS["servers"], forward_port=None).check_servers(s)
    assert ei.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("url", BAD_URLS)
def test_s1_saved_unparseable_url_starts_with_defaults(make_client, appdata, url):
    s = json.loads(json.dumps(DEFAULTS))
    s["servers"]["llm_base_url"] = url
    (appdata / "settings.json").write_text(json.dumps(s), encoding="utf-8")
    c = make_client()
    assert c.get("/health").status_code == 200
    assert c.app.state.lb.net._servers == DEFAULTS["servers"]


def test_s1_forward_unexpected_exception_is_502_not_cancelled(tmp_path):
    logs.setup(tmp_path)

    async def invalid(request):
        raise httpx.InvalidURL("解析不了的地址")  # 不是 httpx.HTTPError 的子类

    net = Net(servers("http://127.0.0.1:9/v1", None, "http://127.0.0.1:9", None),
              transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with ServerThread(forward_app(net, transport=httpx.MockTransport(invalid))) as fwd:
        r = httpx.post(fwd.url + "/v1/chat/completions", json={}, trust_env=False, timeout=10)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and '"module": "forward"' not in "".join(
                p.read_text(encoding="utf-8") for p in (tmp_path / "logs").glob("*")):
            time.sleep(0.05)
    assert r.status_code == 502 and r.json()["error"]["code"] == "INTERNAL"
    rec = [json.loads(x) for x in read_logs(tmp_path).splitlines() if '"module": "forward"' in x]
    assert rec[-1]["status"] == "fail" and rec[-1]["error"] == "InvalidURL"


# ---------- S2：resolve_internal 的拒绝路径 ----------

@pytest.fixture
def root(tmp_path):
    r = tmp_path / "案件"
    (r / "工作区" / "材料").mkdir(parents=True)
    (r / "工作区" / "材料" / "index.json").write_text("{}", encoding="utf-8")
    outside = tmp_path / "案外"
    outside.mkdir()
    (outside / "x.txt").write_text("x", encoding="utf-8")
    logs.setup(tmp_path / "ad")
    return gate.check_root(str(r)), outside


def test_s2_resolve_internal_ok(root):
    r, _ = root
    assert gate.resolve_internal(r, "工作区/材料/index.json").is_file()


@pytest.mark.skipif(not IS_WIN, reason="junction")
def test_s2_resolve_internal_rejects_junction(root):
    r, outside = root
    make_junction(pathlib.Path(r) / "工作区" / "链", outside)
    with pytest.raises(ApiError) as ei:
        gate.resolve_internal(r, "工作区/链/x.txt")
    assert ei.value.code == "OUT_OF_CASE"


@pytest.mark.parametrize("rel", ["工作区/../../案外/x.txt", "../案外/x.txt", "C:\\Windows\\win.ini", "工作区/NUL"])
def test_s2_resolve_internal_rejects_escape(root, rel):
    r, _ = root
    with pytest.raises(ApiError) as ei:
        gate.resolve_internal(r, rel)
    assert ei.value.code == "OUT_OF_CASE"


# ---------- S4：标准目录位置上有同名文件 ----------

def test_s4_template_skips_existing_file(client, cases_dir, appdata):
    root = cases_dir / "同名文件"
    root.mkdir()
    (root / "03一审").write_text("我是一个没有扩展名的文件", encoding="utf-8")
    r = client.post("/api/case/open", json={"path": str(root), "template": "civil"}).json()
    assert r["ok"] is True, r
    assert not any(x.startswith("03一审") for x in r["value"]["folders_created"])
    assert "04二审/我方证据" in r["value"]["folders_created"]
    assert (root / "03一审").read_text(encoding="utf-8") == "我是一个没有扩展名的文件"
    reg = json.loads((appdata / "cases.json").read_text(encoding="utf-8"))
    assert reg["cases"][0]["case_id"] == r["value"]["case_id"]


# ---------- S5：盘符根目录规则单独测 ----------

def test_s5_drive_root_reason():
    drive = os.path.splitdrive(str(SERVICE_DIR))[0] + os.sep if IS_WIN else "/"
    with pytest.raises(ApiError) as ei:
        gate.check_root(drive, appdata=None)  # 不给应用数据目录：只剩盘符根目录这一条能拦
    assert ei.value.code == "INVALID_ARGUMENT" and ei.value.reason == "root_is_drive"


# ---------- S7：两个回归 ----------

def test_s7_main_port_taken_exits_and_frees_forward(tmp_path):
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]
    fport = closed_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("LB_")}
    try:
        p = subprocess.run([sys.executable, "-m", "lawbench", "--port", str(port), "--token", TOKEN,
                            "--appdata", str(tmp_path / "ad"), "--forward-port", str(fport)],
                           cwd=SERVICE_DIR, env=env, capture_output=True, timeout=60)
    finally:
        blocker.close()
    assert p.returncode != 0
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", fport))  # 进程退出后转发端口没被占着
    finally:
        probe.close()


def test_s7_stream_chunks_arrive_progressively(tmp_path):
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
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/event-stream")]})
        for i in range(5):
            await send({"type": "http.response.body", "body": f"data: {i}\n\n".encode(), "more_body": True})
            await anyio.sleep(0.3)
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    with ServerThread(upstream) as up:
        net = Net(servers(up.url + "/v1", None, up.url, None))
        with ServerThread(forward_app(net)) as fwd:
            t0 = time.monotonic()
            times = []
            with httpx.stream("POST", fwd.url + "/v1/chat/completions", json={"stream": True}, trust_env=False,
                              timeout=10) as r:
                for _ in r.iter_raw():
                    times.append(time.monotonic() - t0)
    assert len(times) >= 3
    assert times[-1] - times[0] > 0.8   # 第一段明显早于最后一段到达：没有攒齐再发
