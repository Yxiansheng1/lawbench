"""启动：python -m prep395（WinSW 服务也用这条命令）。

监听地址 PREP395_HOST（默认 127.0.0.1；部署时设为 395 的局域网 IP）、端口 PREP395_PORT（默认 9000）。
关闭 uvicorn 自带的访问日志：访问记录只由 logs.AccessLog 按 Spec 6.6 写元数据。
"""
from __future__ import annotations

import os

import uvicorn

from .app import create_app
from .config import Settings


def uvicorn_config() -> uvicorn.Config:
    host = os.environ.get("PREP395_HOST", "127.0.0.1")
    port = int(os.environ.get("PREP395_PORT", "9000"))
    return uvicorn.Config(create_app(Settings.from_env()), host=host, port=port, access_log=False,
                          log_level="warning", server_header=False, date_header=False)


def main() -> None:
    uvicorn.Server(uvicorn_config()).run()


if __name__ == "__main__":
    main()
