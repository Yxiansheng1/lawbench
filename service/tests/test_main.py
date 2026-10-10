"""启动入口 python -m lawbench：真起一个进程，只监听 127.0.0.1，令牌生效，转发端口只有两个路径。"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import httpx
import pytest

from lawbench.config import REPO_ROOT

from conftest import TOKEN, closed_port

SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _wait(url: str, proc: subprocess.Popen) -> httpx.Response:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"服务进程退出，退出码 {proc.returncode}")
        try:
            return httpx.get(url, trust_env=False, timeout=1)
        except httpx.TransportError:
            time.sleep(0.2)
    raise AssertionError("服务 30 秒内没有起来")


@pytest.mark.parametrize("via_env", [False, True])
def test_entrypoint(tmp_path, via_env):
    port, fport = closed_port(), closed_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("LB_")}
    args = [sys.executable, "-m", "lawbench"]
    if via_env:
        env.update(LB_PORT=str(port), LB_TOKEN=TOKEN, LB_APPDATA=str(tmp_path / "ad"), LB_FORWARD_PORT=str(fport))
    else:
        args += ["--port", str(port), "--token", TOKEN, "--appdata", str(tmp_path / "ad"),
                 "--forward-port", str(fport)]
    proc = subprocess.Popen(args, cwd=SERVICE_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        r = _wait(f"http://127.0.0.1:{port}/health", proc)
        want = (REPO_ROOT / "contracts" / "VERSION").read_text(encoding="utf-8").strip()   # 不写死版本号（契约 1.3 起）
        assert r.json() == {"status": "ok", "contract_version": want}
        assert httpx.get(f"http://127.0.0.1:{port}/api/case/recent", trust_env=False).status_code == 401
        r = httpx.get(f"http://127.0.0.1:{port}/api/case/recent", trust_env=False,
                      headers={"Authorization": f"Bearer {TOKEN}"})
        assert r.json() == {"ok": True, "value": {"cases": []}}
        _wait(f"http://127.0.0.1:{fport}/", proc)
        assert httpx.get(f"http://127.0.0.1:{fport}/admin", trust_env=False).status_code == 404
        assert (tmp_path / "ad" / "capsules.json").is_file()  # 首次启动复制默认胶囊配置
    finally:
        proc.terminate()
        out = proc.communicate(timeout=15)[0].decode("utf-8", "replace")
    assert TOKEN not in out


def test_entrypoint_needs_token(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("LB_")}
    p = subprocess.run([sys.executable, "-m", "lawbench", "--port", str(closed_port()), "--appdata",
                        str(tmp_path)], cwd=SERVICE_DIR, env=env, capture_output=True, timeout=60)
    assert p.returncode != 0


def test_listens_on_loopback_only():
    from lawbench.__main__ import _server
    from lawbench.net import LOOPBACK
    assert LOOPBACK == "127.0.0.1"
    assert _server(object(), 0).config.host == "127.0.0.1"


# ---------- 第七版待办 10：端口绑不上的原因分类（portdiag） ----------

NETSH_OUT = """
协议 tcp 端口排除范围

开始端口    结束端口
----------    --------
      5357        5357
     18700       18799
     50000       50059     *

* - 管理的端口排除。
"""


def _oserr(winerror: int) -> OSError:
    e = OSError(winerror, "x")
    e.winerror = winerror
    return e


def test_port_category_three_kinds():
    from lawbench import portdiag as pd
    assert pd.parse_excluded(NETSH_OUT) == [(5357, 5357), (18700, 18799), (50000, 50059)]
    calls = []

    def netsh():
        calls.append(1)
        return NETSH_OUT
    assert pd.classify(18765, _oserr(10048), netsh) == pd.PORT_IN_USE and calls == []     # 占用：不用查保留段
    assert pd.classify(18765, _oserr(10013), netsh) == pd.PORT_RESERVED and len(calls) == 1  # 10013 且在保留段，只查一次
    assert pd.classify(18901, _oserr(10013), netsh) == pd.PORT_DENIED                     # 10013 但不在保留段
    assert pd.classify(18765, _oserr(10013), lambda: None) == pd.PORT_DENIED              # netsh 跑不了、超时
    assert pd.classify(18765, _oserr(10022), netsh) == pd.PORT_DENIED                     # 其余错误
    # 保留段两端都算在内（复核 P3-1）：单端口段、段的起点和终点；紧邻段外的不算
    assert pd.classify(5357, _oserr(10013), netsh) == pd.PORT_RESERVED
    assert pd.classify(18700, _oserr(10013), netsh) == pd.PORT_RESERVED
    assert pd.classify(18799, _oserr(10013), netsh) == pd.PORT_RESERVED
    assert pd.classify(18699, _oserr(10013), netsh) == pd.PORT_DENIED
    assert pd.classify(18800, _oserr(10013), netsh) == pd.PORT_DENIED
    assert pd.classify(18765, None, netsh) == pd.PORT_DENIED
    assert pd.line(18765, pd.PORT_RESERVED) == "PORT_RESERVED 18765 18765 在 Windows 保留端口段内，请在设置里换一个端口"


def test_netsh_absolute_path_and_runs_once(monkeypatch):
    """复核 P3-2、P3-3：netsh 用系统目录的绝对路径；一个进程里只跑一次。"""
    from lawbench import portdiag as pd
    assert os.path.isabs(pd.NETSH[0]) and pd.NETSH[0].lower().endswith(os.path.join("system32", "netsh.exe"))
    calls = []

    class P:
        returncode, stdout = 0, NETSH_OUT.encode("utf-8")

    monkeypatch.setattr(pd.sys, "platform", "win32")
    monkeypatch.setattr(pd.subprocess, "run", lambda *a, **k: calls.append(a[0]) or P())
    pd.run_netsh.cache_clear()
    try:
        assert pd.classify(18765, _oserr(10013)) == pd.PORT_RESERVED and pd.classify(18901, _oserr(10013)) == pd.PORT_DENIED
        assert len(calls) == 1 and calls[0] == pd.NETSH
    finally:
        pd.run_netsh.cache_clear()


def test_report_port_never_raises(monkeypatch, capfdbinary):
    """复核 P3-4：分类过程出错也照样写一行（按系统拒绝），不抛出去。"""
    from lawbench import __main__ as m
    from lawbench import portdiag as pd

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(pd, "bind_error", boom)
    m._report_port(18765)
    assert capfdbinary.readouterr().err.decode("utf-8").startswith("PORT_DENIED 18765 ")
    monkeypatch.setattr(pd.socket, "socket", boom)          # 建 socket 就出错：bind_error 自己不抛 OSError 以外的也被兜住
    m._report_port(18765)
    assert capfdbinary.readouterr().err.decode("utf-8").startswith("PORT_DENIED 18765 ")


def test_port_in_use_first_stderr_line(tmp_path):
    """真起一次：转发端口被占着，服务以退出码 2 结束，标准错误第一行是"PORT_IN_USE <端口> …"（UTF-8）。"""
    import socket
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen(1)
    fport = busy.getsockname()[1]
    try:
        env = {k: v for k, v in os.environ.items() if not k.startswith("LB_")}
        p = subprocess.run([sys.executable, "-m", "lawbench", "--port", str(closed_port()), "--token", TOKEN,
                            "--appdata", str(tmp_path / "ad"), "--forward-port", str(fport)],
                           cwd=SERVICE_DIR, env=env, capture_output=True, timeout=90)
    finally:
        busy.close()
    first = p.stderr.decode("utf-8", "replace").splitlines()[0]
    assert p.returncode == 2 and first == f"PORT_IN_USE {fport} {fport} 端口被其他程序占用，请关闭占用程序后重试"
    assert TOKEN not in p.stderr.decode("utf-8", "replace")
