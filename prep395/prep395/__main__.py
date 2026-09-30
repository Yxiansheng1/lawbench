"""启动：python -m prep395（WinSW 服务也用这条命令）。

监听地址 PREP395_HOST（默认 127.0.0.1；部署时设为 395 的所内、所外两个地址，逗号分隔，
如 "192.168.8.124,10.126.126.3"，只听这几个地址、不听 0.0.0.0——用户 2026-09-30 定）、端口 PREP395_PORT（默认 9000）。
第一个地址（所内）绑上就开始服务；其余地址（所外 EasyTier 的虚拟网卡开机时可能还没起来）在后台每 5 秒重试，
等到时记一条、绑上时记一条元数据日志。端口被占（WinError 10048）不重试，报错退出，让 Windows 服务显示失败。
关闭 uvicorn 自带的访问日志：访问记录只由 logs.AccessLog 按 Spec 6.6 写元数据。
"""
from __future__ import annotations

import asyncio
import errno
import os
import socket
import sys
import time

import uvicorn
from fastapi import FastAPI

from .app import create_app
from .config import Settings

RETRY_SECONDS = 5
ADDR_IN_USE = (errno.EADDRINUSE, 10048)          # 10048 = WSAEADDRINUSE


def hosts() -> list[str]:
    raw = os.environ.get("PREP395_HOST", "127.0.0.1")
    return [h.strip() for h in raw.split(",") if h.strip()]


def port() -> int:
    return int(os.environ.get("PREP395_PORT", "9000"))


def uvicorn_config(app: FastAPI | None = None, host: str | None = None, lifespan: str = "auto") -> uvicorn.Config:
    return uvicorn.Config(app or create_app(Settings.from_env()), host=host or hosts()[0], port=port(),
                          access_log=False, log_level="warning", server_header=False, date_header=False,
                          lifespan=lifespan)


def in_use(e: OSError) -> bool:
    return e.errno in ADDR_IN_USE or getattr(e, "winerror", None) == 10048


def bind_one(addr: str, p: int) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind((addr, p))
        s.listen(2048)
        s.set_inheritable(True)
        return s
    except OSError:
        s.close()
        raise


def bind_first(addr: str, p: int, retry: float | None = None, attempts: int | None = None) -> socket.socket:
    """所内地址：绑不上（网卡未起）就等 retry 秒再试；端口被占立即报错。attempts 为 None 时一直等。"""
    retry = RETRY_SECONDS if retry is None else retry
    n = 0
    while True:
        try:
            return bind_one(addr, p)
        except OSError as e:
            n += 1
            if in_use(e) or (attempts is not None and n >= attempts):
                raise
            print(f"prep395: 所内地址暂不可用，{retry:g} 秒后重试（{e.__class__.__name__}）", file=sys.stderr, flush=True)
            time.sleep(retry)


async def attach_later(main: uvicorn.Server, app: FastAPI, addr: str, p: int, retry: float | None = None) -> None:
    """其余地址：后台重试，绑上后在同一进程、同一应用上多开一个监听（不重复跑启动清理）。"""
    retry = RETRY_SECONDS if retry is None else retry
    log = getattr(app.state, "log", None)
    waited = False
    while not main.should_exit:
        try:
            s = bind_one(addr, p)
        except OSError as e:
            if in_use(e):
                raise
            if not waited and log:
                log.event("listen_wait", 1)             # 只记一条，不记地址
                waited = True
            await asyncio.sleep(retry)
            continue
        if waited and log and not main.should_exit:
            log.event("listen_ok", 1)
        extra = uvicorn.Server(uvicorn_config(app, host=addr, lifespan="off"))
        waiter = asyncio.ensure_future(_stop_with(main, extra))
        try:
            await extra._serve(sockets=[s])             # 不装信号处理：退出跟着主监听走
        finally:
            waiter.cancel()
        return


async def _stop_with(main: uvicorn.Server, extra: uvicorn.Server) -> None:
    while not main.should_exit:
        await asyncio.sleep(0.2)
    extra.should_exit = True


async def serve(addrs: list[str], p: int, first=None) -> None:
    """first：已绑好的所内套接字。main() 在事件循环外先绑（重试用的 time.sleep 不能卡住事件循环，
    否则 Ctrl+C / 服务停止只取消任务、取消不到阻塞的重试，停不下来——T11 小项 P3-A）；测试可省略。"""
    app = create_app(Settings.from_env())
    if first is None:
        first = bind_first(addrs[0], p)
    main = uvicorn.Server(uvicorn_config(app, host=addrs[0]))
    failed: list[BaseException] = []

    def on_done(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception() is not None:
            failed.append(t.exception())
            main.should_exit = True                      # 其余地址端口被占等：整个服务报错退出

    tasks = [asyncio.ensure_future(attach_later(main, app, a, p)) for a in addrs[1:]]
    for t in tasks:
        t.add_done_callback(on_done)
    try:
        await main.serve(sockets=[first])
    finally:
        main.should_exit = True
        await asyncio.gather(*tasks, return_exceptions=True)
    if failed:
        raise failed[0]


def main() -> None:
    try:
        addrs, p = hosts(), port()
        first = bind_first(addrs[0], p)                  # 在事件循环之外：重试期间 Ctrl+C 直接生效
        asyncio.run(serve(addrs, p, first))
    except KeyboardInterrupt:                             # 重试期间收到停止（Ctrl+C）：正常退出
        sys.exit(0)
    except OSError as e:
        print(f"prep395: 无法监听（{e.__class__.__name__}，{'端口被占用' if in_use(e) else '地址不可用'}）",
              file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
