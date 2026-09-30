"""T3 第三轮返修（执行令 致B-ORCH-执行令-T3第三轮及T5返修-20260930-0136）：S1 补漏。

校验地址时用发请求的同一个解析器（httpx.URL）再解析一次，两个解析器的结论还要一致；
含控制字符、非 ASCII 主机名等写法一律拒绝，不写盘；probe 接住解析异常，不出 500。
"""
from __future__ import annotations

import json

import httpx
import pytest

from lawbench.api.ui import probe_connection
from lawbench.errors import ApiError
from lawbench.net import Net, server_url_ok
from lawbench.settings import DEFAULTS

# 复核员 B 的 F10 列的 4 个地址
F10_URLS = [
    "http://127.0.0.1:8000/v1\n",
    "http://127.0.0.1:80\n00/v1",
    "http://127.0.0.1\t:8000/v1",
    "http://ｌｏｃａｌｈｏｓｔ:8000/v1",  # 全角 localhost
]
# 自己再想的"能过 urlsplit、但 httpx 不认或两者看法不一样"的写法
MORE_BAD = [
    "http://127.0.0.1:8000/v1\r",
    "http://127.0.0.1:8000/v1\x00",
    "http://127.0.0.1:8000/v1\x7f",
    "http://127.0.0.1:8000/v1​",                 # 零宽空格
    "http://127.0.0.1 :8000/v1",                      # 半角空格
    "http://127.0.0.1:8000/材料",              # 路径里的非 ASCII
    "http://127.0.0.1:８０００/v1",    # 全角端口
    "http://例子.com:8000/v1",                 # 中文域名
    "http://xn--fsq.com:8000/v1",                     # httpx 解出非 ASCII 主机名，与 urlsplit 不一致
    "http://127.0.0.1\\@192.168.8.77:8000/v1",        # 反斜杠加用户信息：两个解析器切法不同
    "http://a@127.0.0.1:8000/v1",
    "http://%31%32%37.0.0.1:8000/v1",
    "http://127.0.0.1:8000/v1#x",
    "http://127.0.0.1:8000/v1?a=1",
    "http://127.0.0.1:65536/v1",
    "http://127.0.0.1:0/v1",
    "http://0x7f.1:8000/v1",                          # 系统解析器可能当成 127.0.0.1
    "http://127.1:8000/v1",
    "http://2130706433:8000/v1",
    "https://127.0.0.1:8000/v1",
    "http://:8000/v1",
    "http:///v1",
    "http://127.0.0.1:8x/v1",
    "http://[::1/v1",
    "",
]
GOOD = [
    "http://192.168.8.77:8000/v1",
    "http://10.126.126.1:8000/v1",
    "http://192.168.8.124:9000",
    "http://10.126.126.3:9000",
    "http://127.0.0.1:8000/v1",
    "http://localhost:8000/v1",
    "http://[::1]:8000/v1",
    "http://gpu-6000d.lan:8000/v1",
    "http://127.0.0.1/v1",
]
KEYS = ["llm_base_url", "prep_base_url", "llm_alt_base_url", "prep_alt_base_url"]


@pytest.mark.parametrize("url", F10_URLS + MORE_BAD)
def test_s1_bad_urls_rejected(url):
    assert server_url_ok(url) is False


@pytest.mark.parametrize("url", GOOD)
def test_s1_good_urls_accepted(url):
    assert server_url_ok(url) is True
    httpx.URL(url)  # 发请求的那个库也认


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("url", F10_URLS)
def test_s1_put_f10_url_rejected_not_written(make_client, appdata, key, url):
    c = make_client()
    s = c.get("/api/settings").json()["value"]
    s["servers"][key] = url
    r = c.put("/api/settings", json=s).json()
    assert r["ok"] is False and r["error"]["code"] == "INVALID_ARGUMENT"
    assert not (appdata / "settings.json").exists()
    # 之后测试连接照常返回，不是 500
    t = c.post("/api/connection/test", json={"server": "llm"})
    assert t.status_code == 200


@pytest.mark.parametrize("url", F10_URLS)
def test_s1_check_servers_rejects_f10(url):
    s = dict(DEFAULTS["servers"], llm_alt_base_url=url)
    with pytest.raises(ApiError) as ei:
        Net(DEFAULTS["servers"], forward_port=None).check_servers(s)
    assert ei.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("url", F10_URLS)
def test_s1_saved_f10_url_starts_with_defaults(make_client, appdata, key, url):
    """启动时设置文件里已经存着这种地址：改用默认地址启动，测试连接不出 500。"""
    s = json.loads(json.dumps(DEFAULTS))
    s["servers"][key] = url
    (appdata / "settings.json").write_text(json.dumps(s), encoding="utf-8")
    c = make_client()
    assert c.get("/health").status_code == 200
    assert c.app.state.lb.net._servers == DEFAULTS["servers"]
    for server in ("llm", "prep"):
        assert c.post("/api/connection/test", json={"server": server}).status_code == 200


@pytest.mark.parametrize("url", F10_URLS)
def test_s1_probe_catches_invalid_url(make_client, url):
    """即使坏地址绕过了校验进了内存（兜底），probe 也按不通处理，测试连接返回 200 而不是 500。"""
    c = make_client()
    st = c.app.state.lb
    st.net._servers = dict(st.net._servers, llm_base_url=url, llm_alt_base_url=None)
    st.net._routes.clear()
    assert st.net.probe("llm", url.rstrip("/")) is False
    out = probe_connection(st, "llm")
    assert out["reachable"] is False
    r = c.post("/api/connection/test", json={"server": "llm"})
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["value"]["reachable"] is False


def test_s1_parsers_must_agree_alone(monkeypatch):
    """单独测"两个解析器的主机要一致"这一层：把主机名规则放宽到什么都收，xn-- 主机名（httpx 解出非 ASCII、
    urlsplit 仍是 ASCII）照样被拒。"""
    import re

    from lawbench import net
    monkeypatch.setattr(net, "_HOST_LABELS", re.compile(r".*"))
    assert server_url_ok("http://xn--fsq.com:8000/v1") is False
    assert server_url_ok("http://gpu-6000d.lan:8000/v1") is True
