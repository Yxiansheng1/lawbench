"""监听地址（T11 返修 P3-1、P3-2）：只听列出的地址；所内绑上即服务，所外后台重试；端口被占不重试、退出并释放端口。"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import random
import socket
import time

import httpx
import pytest

from prep395 import __main__ as m

LAN, VPN = "127.0.0.1", "127.0.0.2"                      # 用两个本机回环地址代替所内、所外


def free_port() -> int:
    """19000–19099 段随机取一个两个地址上都空闲的端口。"""
    for _ in range(200):
        p = random.randint(19000, 19099)              # prep395 专用段，避免撞并行复核员（T11 小项 8）
        try:
            for a in (LAN, VPN):
                s = socket.socket()
                s.bind((a, p))
                s.close()
            return p
        except OSError:
            continue
    raise RuntimeError("找不到空闲端口")


def can_bind(addr: str, p: int) -> bool:
    s = socket.socket()
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind((addr, p))
        return True
    except OSError:
        return False
    finally:
        s.close()


@pytest.fixture
def env(monkeypatch, settings):
    monkeypatch.setenv("PREP395_LLM_BASE", settings.llm_base)
    monkeypatch.setenv("PREP395_HOME", str(settings.home))
    monkeypatch.setenv("PREP395_BACKEND", "fake")
    return settings


def test_hosts_parsed_and_no_wildcard(monkeypatch):
    monkeypatch.setenv("PREP395_HOST", " 192.168.8.124 , 10.126.126.3 ")
    assert m.hosts() == ["192.168.8.124", "10.126.126.3"]
    assert "0.0.0.0" not in m.hosts()


def test_first_address_retried_then_gives_up_and_releases_port():
    p = free_port()
    with pytest.raises(OSError):
        m.bind_first("192.0.2.123", p, retry=0, attempts=2)     # 192.0.2.0/24 为文档保留地址，本机没有
    assert can_bind(LAN, p)


def test_port_in_use_not_retried():
    p = free_port()
    hold = m.bind_one(LAN, p)
    try:
        t = time.monotonic()
        with pytest.raises(OSError) as e:
            m.bind_first(LAN, p, retry=30, attempts=2)         # 若重试会等 30 秒；attempts 有限，退化时变红而不卡死
        assert m.in_use(e.value) and time.monotonic() - t < 5
    finally:
        hold.close()


async def _get(addr: str, p: int) -> int:
    async with httpx.AsyncClient() as c:
        return (await c.get(f"http://{addr}:{p}/health", timeout=5)).status_code


def test_serves_both_addresses_and_only_those(env):
    p = free_port()

    async def run():
        task = asyncio.ensure_future(m.serve([LAN, VPN], p))
        for _ in range(100):
            await asyncio.sleep(0.1)
            if not can_bind(VPN, p):
                break
        assert await _get(LAN, p) == 200 and await _get(VPN, p) == 200
        assert can_bind("127.0.0.3", p)                      # 没列出的地址没在听
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())
    assert can_bind(LAN, p) and can_bind(VPN, p)


def test_second_address_waits_then_attaches(env, monkeypatch):
    """所外地址暂不存在：所内先服务；所外重试到位后也能访问；只记一条等待、一条就绪。"""
    p = free_port()
    real = m.bind_one
    fails = {"n": 0}

    def flaky(addr, port):
        if addr == VPN and fails["n"] < 3:
            fails["n"] += 1
            raise OSError(10049, "地址无效")                   # WSAEADDRNOTAVAIL
        return real(addr, port)
    monkeypatch.setattr(m, "bind_one", flaky)
    monkeypatch.setattr(m, "RETRY_SECONDS", 0.05)

    async def run():
        task = asyncio.ensure_future(m.serve([LAN, VPN], p))
        await asyncio.sleep(0.3)
        assert await _get(LAN, p) == 200
        for _ in range(100):
            await asyncio.sleep(0.05)
            if fails["n"] >= 3 and not can_bind(VPN, p):
                break
        assert await _get(VPN, p) == 200
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())
    lines = [json.loads(x) for x in (env.home / "logs" / "access.log").read_text(encoding="utf-8").splitlines()]
    apis = [x["api"] for x in lines]
    assert apis.count("listen_wait") == 1 and apis.count("listen_ok") == 1
    assert "127.0.0.2" not in (env.home / "logs" / "access.log").read_text(encoding="utf-8")


def test_second_port_in_use_exits_and_releases_first(env):
    """所外地址端口被占：不重试，整个服务报错退出，所内端口也放掉（服务显示失败，由 WinSW 按失败处理）。"""
    p = free_port()
    hold = m.bind_one(VPN, p)
    try:
        t = time.monotonic()
        with pytest.raises(OSError) as e:
            asyncio.run(asyncio.wait_for(m.serve([LAN, VPN], p), 20))
        assert m.in_use(e.value) and time.monotonic() - t < 15
    finally:
        hold.close()
    assert can_bind(LAN, p)


def test_failed_setup_after_bind_releases_port(monkeypatch):
    """绑上后 listen 失败：刚绑的口必须当场关掉（变异 s.close() → pass 时本条变红）。"""
    p = free_port()

    class BadListen(socket.socket):
        def listen(self, *a):
            raise OSError(10055, "资源不足")                    # WSAENOBUFS
    monkeypatch.setattr(m.socket, "socket", BadListen)
    with pytest.raises(OSError) as e:
        m.bind_one(LAN, p)
    monkeypatch.undo()
    assert e.value is not None and can_bind(LAN, p)            # e 还持有出错帧，漏关的口此时仍被占着


HELPER = r'''
import ctypes, os, signal, subprocess, sys, time
ctypes.windll.kernel32.SetConsoleCtrlHandler(None, False)   # 取消从测试环境继承来的"忽略 Ctrl+C"（WinSW 的控制台没有这个）
env = dict(os.environ, PREP395_HOST="192.0.2.123", PREP395_PORT=sys.argv[1])
p = subprocess.Popen([sys.executable, "-m", "prep395"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(4)                                             # 让它进入所内地址的重试
alive_before = p.poll() is None
t = time.monotonic()
try:
    os.kill(0, signal.CTRL_C_EVENT)                       # 发给本控制台（助手自己的新控制台）里的全部进程，含助手自己
    time.sleep(1)
except KeyboardInterrupt:
    pass
while True:
    try:
        p.wait(timeout=20)
        print(f"{alive_before} {time.monotonic() - t:.1f} {p.returncode}")
        break
    except KeyboardInterrupt:
        continue
    except subprocess.TimeoutExpired:
        p.kill()
        print(f"{alive_before} TIMEOUT -")
        break
'''


@pytest.mark.skipif(os.name != "nt", reason="Windows 服务停止用的是控制台 Ctrl+C")
def test_ctrl_c_stops_while_retrying_lan_address(env, tmp_path):
    """所内地址绑不上、正在重试时收到 Ctrl+C（WinSW 停服务）：几秒内退出（T11 小项 P3-A，原来 40 秒仍在重试）。"""
    import subprocess
    import sys
    helper = tmp_path / "helper.py"
    helper.write_text(HELPER, encoding="utf-8")
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0                                    # 新控制台不显示窗口
    r = subprocess.run([sys.executable, str(helper), str(free_port())], capture_output=True, text=True, timeout=60,
                       creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=si, env=os.environ.copy(),
                       cwd=str(pathlib.Path(__file__).resolve().parents[1]))
    alive, secs, _code = r.stdout.split()
    assert alive == "True" and secs != "TIMEOUT" and float(secs) < 5
