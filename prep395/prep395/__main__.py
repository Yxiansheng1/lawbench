"""启动：python -m prep395（WinSW 服务也用这条命令）。

监听地址 PREP395_HOST（默认 127.0.0.1；部署时设为 395 的所内、所外两个地址，逗号分隔，
如 "192.168.8.124,10.126.126.3"，只听这几个地址、不听 0.0.0.0）、端口 PREP395_PORT（默认 9000）。
开机时 EasyTier 的虚拟网卡可能还没起来，绑不上的地址每 5 秒重试一次，全部绑上才开始服务。
关闭 uvicorn 自带的访问日志：访问记录只由 logs.AccessLog 按 Spec 6.6 写元数据。
"""
from __future__ import annotations

import os
import socket
import sys
import time

import uvicorn

from .app import create_app
from .config import Settings

RETRY_SECONDS = 5


def hosts() -> list[str]:
    raw = os.environ.get("PREP395_HOST", "127.0.0.1")
    return [h.strip() for h in raw.split(",") if h.strip()]


def port() -> int:
    return int(os.environ.get("PREP395_PORT", "9000"))


def uvicorn_config() -> uvicorn.Config:
    return uvicorn.Config(create_app(Settings.from_env()), host=hosts()[0], port=port(), access_log=False,
                          log_level="warning", server_header=False, date_header=False)


def bind_all(addrs: list[str], p: int, retry: float = RETRY_SECONDS, attempts: int | None = None) -> list[socket.socket]:
    """把每个地址都绑上；地址暂时不存在（网卡未起）就等 retry 秒再试。attempts 为 None 时一直等。"""
    n = 0
    while True:
        socks: list[socket.socket] = []
        try:
            for a in addrs:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                socks.append(s)
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                s.bind((a, p))
                s.listen(2048)
                s.set_inheritable(True)
            return socks
        except OSError as e:
            for s in socks:
                s.close()
            n += 1
            if attempts is not None and n >= attempts:
                raise
            print(f"prep395: 地址暂不可用，{retry:g} 秒后重试（{e.__class__.__name__}）", file=sys.stderr, flush=True)
            time.sleep(retry)


def main() -> None:
    socks = bind_all(hosts(), port())
    uvicorn.Server(uvicorn_config()).run(sockets=socks)


if __name__ == "__main__":
    main()
