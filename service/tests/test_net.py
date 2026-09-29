"""统一 HTTP 客户端（Spec 14.3、第 15 节）：地址白名单、不跟随重定向、所内/所外地址选择、本机转发。"""
from __future__ import annotations

import json
import time

import httpx
import pytest

from lawbench import logs
from lawbench.errors import ApiError
from lawbench.net import CACHE_SECONDS, Allowlist, Net, forward_app

from conftest import ServerThread, closed_port, servers
from fakes import CHUNK1, CHUNK2, Fake395, Fake6000D

DEFAULT = servers("http://192.168.8.77:8000/v1", "http://10.126.126.1:8000/v1",
                  "http://192.168.8.124:9000", "http://10.126.126.3:9000")


# ---------- 白名单 ----------

@pytest.mark.parametrize("url", [
    "http://192.168.8.77:8000/v1/models", "http://10.126.126.1:8000/v1/chat/completions",
    "http://192.168.8.124:9000/health", "http://10.126.126.3:9000/v1/ocr/page",
    "http://127.0.0.1:18765/v1/models", "http://127.0.0.1:1/x",
])
def test_allowlist_allows(url):
    a = Allowlist()
    a.update(DEFAULT)
    assert a.allowed(url)


@pytest.mark.parametrize("url", [
    "http://example.com/", "http://192.168.8.77:22/", "http://192.168.8.77:9000/",   # 其他主机、同主机其他端口
    "http://192.168.8.124:8000/", "http://10.126.126.2:8000/", "https://192.168.8.77:8000/v1/models",
    "http://localhost:8000/", "http://0.0.0.0:8000/", "http://[::1]:8000/", "http://127.0.0.2/",
    "http://192.168.8.77:8000@evil.example/", "ftp://192.168.8.77:8000/", "http://192.168.8.77:abc/",
    "file:///C:/Windows/win.ini", "",
])
def test_allowlist_denies(url):
    a = Allowlist()
    a.update(DEFAULT)
    assert not a.allowed(url)


def test_allowlist_follows_settings():
    a = Allowlist()
    a.update(DEFAULT)
    assert not a.allowed("http://10.0.0.9:8000/v1/models")
    a.update(servers("http://10.0.0.9:8000/v1", None, "http://10.0.0.9:9000", None))
    assert a.allowed("http://10.0.0.9:8000/v1/models")
    assert not a.allowed("http://192.168.8.77:8000/v1/models")  # 旧地址随设置移除


def test_blocked_request_never_sent(tmp_path):
    logs.setup(tmp_path)
    calls = []
    net = Net(DEFAULT, transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200)))
    for url in ["http://evil.example/", "http://192.168.8.77:22/", "https://192.168.8.77:8000/v1/models"]:
        with pytest.raises(ApiError) as ei:
            net.client.get(url)
        assert ei.value.code == "HOST_NOT_ALLOWED"
    assert calls == []
    net.client.get("http://192.168.8.77:8000/v1/models")
    assert len(calls) == 1


def test_no_system_proxy(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://evil.example:3128")
    monkeypatch.setenv("ALL_PROXY", "http://evil.example:3128")
    net = Net(DEFAULT)
    assert net.client._mounts == {} and net.client._trust_env is False


def test_redirect_not_followed(tmp_path):
    logs.setup(tmp_path)
    f = Fake6000D()
    with ServerThread(f.app()) as s:
        net = Net(servers(s.url + "/v1", None, s.url, None))
        with pytest.raises(ApiError) as ei:
            net.client.get(s.url + "/v1/redirect")
        assert ei.value.code == "HOST_NOT_ALLOWED"
        assert f.hits == 1  # 只打到了发 302 的那一次，没有跟过去


# ---------- 地址选择 ----------

class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_select_primary_then_alternate(tmp_path):
    logs.setup(tmp_path)
    fa, fb = Fake6000D(), Fake6000D()
    with ServerThread(fa.app()) as a, ServerThread(fb.app()) as b:
        net = Net(servers(a.url + "/v1", b.url + "/v1", a.url, b.url))
        assert net.select("llm") == (a.url + "/v1", "primary")
        net2 = Net(servers(f"http://127.0.0.1:{closed_port()}/v1", b.url + "/v1", a.url, b.url))
        assert net2.select("llm") == (b.url + "/v1", "alternate")
        assert fb.seen[-1]["path"] == "/v1/models"  # 6000D 探测 /v1/models


def test_select_prep_uses_health(tmp_path):
    logs.setup(tmp_path)
    fp = Fake395()
    with ServerThread(fp.app()) as p:
        net = Net(servers("http://127.0.0.1:1/v1", None, f"http://127.0.0.1:{closed_port()}", p.url))
        assert net.select("prep") == (p.url, "alternate")
        assert fp.hits == 1


def test_select_both_down(tmp_path):
    logs.setup(tmp_path)
    net = Net(servers(f"http://127.0.0.1:{closed_port()}/v1", f"http://127.0.0.1:{closed_port()}/v1",
                      f"http://127.0.0.1:{closed_port()}", None))
    for kind in ("llm", "prep"):
        with pytest.raises(ApiError) as ei:
            net.select(kind)
        assert ei.value.code == "SERVER_UNREACHABLE"


def test_select_cached_60s(tmp_path):
    logs.setup(tmp_path)
    fa, fb = Fake6000D(), Fake6000D()
    clock = Clock()
    with ServerThread(fb.app()) as b:
        port = closed_port()
        net = Net(servers(f"http://127.0.0.1:{port}/v1", b.url + "/v1", b.url, None), clock=clock)
        assert net.select("llm")[1] == "alternate"
        with ServerThread(fa.app(), port=port):  # 所内地址恢复
            clock.t += CACHE_SECONDS - 1
            assert net.select("llm")[1] == "alternate"  # 60 秒内用缓存
            assert fa.hits == 0
            clock.t += 2
            assert net.select("llm")[1] == "primary"   # 过期后重新探测，先试所内
            assert fa.hits == 1


def test_reprobe_on_connection_error(tmp_path):
    logs.setup(tmp_path)
    fa, fb = Fake6000D(), Fake6000D()
    with ServerThread(fb.app()) as b:
        a = ServerThread(fa.app()).__enter__()
        net = Net(servers(a.url + "/v1", b.url + "/v1", b.url, None))
        assert net.select("llm")[1] == "primary"
        a.__exit__(None, None, None)            # 所内地址断开，缓存还没过期
        r, route = net.request("llm", "GET", "/models")
        assert r.status_code == 200 and route == "alternate"
        assert net.select("llm")[1] == "alternate"


def test_request_both_down_after_error(tmp_path):
    logs.setup(tmp_path)
    fa = Fake6000D()
    a = ServerThread(fa.app()).__enter__()
    net = Net(servers(a.url + "/v1", None, a.url, None))
    net.select("llm")
    a.__exit__(None, None, None)
    with pytest.raises(ApiError) as ei:
        net.request("llm", "GET", "/models")
    assert ei.value.code == "SERVER_UNREACHABLE"


def test_settings_change_resets_route(tmp_path):
    logs.setup(tmp_path)
    fa, fb = Fake6000D(), Fake6000D()
    with ServerThread(fa.app()) as a, ServerThread(fb.app()) as b:
        net = Net(servers(a.url + "/v1", None, a.url, None))
        assert net.select("llm")[0] == a.url + "/v1"
        net.update(servers(b.url + "/v1", None, b.url, None))
        assert net.select("llm")[0] == b.url + "/v1"


# ---------- 本机转发 ----------

@pytest.fixture
def forward(tmp_path):
    """假 6000D（所外地址）+ 不通的所内地址 + 转发服务，全部在 127.0.0.1 随机端口。"""
    logs.setup(tmp_path / "appdata")
    f = Fake6000D()
    with ServerThread(f.app()) as up:
        net = Net(servers(f"http://127.0.0.1:{closed_port()}/v1", up.url + "/v1", up.url, None))
        with ServerThread(forward_app(net)) as fwd:
            fwd.fake = f
            fwd.tmp = tmp_path
            yield fwd


def test_forward_chat_streams(forward):
    body = {"model": "qwen38-27b", "stream": True, "messages": [{"role": "user", "content": "LBTEST-PROMPT"}]}
    with httpx.Client(trust_env=False, timeout=10) as c:
        with c.stream("POST", forward.url + "/v1/chat/completions?x=1", json=body,
                      headers={"Authorization": "Bearer LBTEST-KEY", "X-Session-Id": "abcd1234-T-1",
                               "Cookie": "c=1"}) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            assert r.headers["x-queue-wait-ms"] == "12"
            it = r.iter_raw()
            first = next(it)
            # 第二段要等测试读到第一段后才放行：能读到第一段，说明转发没有攒齐再发
            assert first == CHUNK1
            forward.fake.release.set()
            rest = b"".join(it)
    assert first + rest == CHUNK1 + CHUNK2
    seen = [s for s in forward.fake.seen if s["path"] == "/v1/chat/completions"][0]
    assert seen["body"] == body
    assert seen["headers"]["authorization"] == "Bearer LBTEST-KEY"   # 律师 Key 原样带过去
    assert seen["headers"]["x-session-id"] == "abcd1234-T-1"
    assert "cookie" not in seen["headers"]
    assert seen["query"] == "x=1"


def test_forward_models(forward):
    r = httpx.get(forward.url + "/v1/models", trust_env=False)
    assert r.status_code == 200 and r.json()["data"][0]["id"] == "qwen38-27b"


@pytest.mark.parametrize("method,path", [
    ("POST", "/v1/embeddings"), ("GET", "/v1/embeddings"), ("POST", "/v1/completions"), ("GET", "/admin"),
    ("GET", "/v1/chat/completions"), ("POST", "/v1/models"), ("GET", "/"), ("GET", "/health"),
    ("GET", "/v1/models/../../admin"), ("GET", "/api/case/recent"), ("POST", "/v1/chat/completions/x"),
])
def test_forward_other_paths_404(forward, method, path):
    hits = forward.fake.hits
    r = httpx.request(method, forward.url + path, trust_env=False, json={})
    assert r.status_code == 404
    assert forward.fake.hits == hits  # 没有转发出去


def test_forward_upstream_down(tmp_path):
    logs.setup(tmp_path)
    net = Net(servers(f"http://127.0.0.1:{closed_port()}/v1", None, "http://127.0.0.1:1", None))
    with ServerThread(forward_app(net)) as fwd:
        r = httpx.post(fwd.url + "/v1/chat/completions", json={"stream": True}, trust_env=False, timeout=30)
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "SERVER_UNREACHABLE"


def test_forward_logs_metadata_only(forward):
    body = {"model": "qwen38-27b", "stream": True, "messages": [{"role": "user", "content": "LBTEST-PROMPT"}]}
    forward.fake.release.set()
    r = httpx.post(forward.url + "/v1/chat/completions", json=body, trust_env=False, timeout=10,
                   headers={"Authorization": "Bearer LBTEST-KEY"})
    assert r.status_code == 200
    log_dir = forward.tmp / "appdata" / "logs"
    deadline = time.monotonic() + 5  # 转发的日志在响应发完后由后台任务写
    while time.monotonic() < deadline:
        text = "".join(p.read_text(encoding="utf-8") for p in log_dir.glob("*"))
        if '"module": "forward"' in text:
            break
        time.sleep(0.05)
    logs.close()
    text = "".join(p.read_text(encoding="utf-8") for p in log_dir.glob("*"))
    assert '"module": "forward"' in text
    for bad in ["LBTEST", "LBFAKE", "Bearer", "127.0.0.1", "qwen"]:
        assert bad not in text, bad
    for line in text.splitlines():
        assert set(json.loads(line)) <= {"t", "module", "op", "status", "case_id", "ms", "error"}
