"""启动入口：python -m lawbench --port <p> --token <t> [--appdata <dir>] [--forward-port <p>]

也读环境变量 LB_PORT、LB_TOKEN、LB_APPDATA、LB_FORWARD_PORT（Spec 1.3）。只监听 127.0.0.1。
同一进程里起两个监听：工作台接口（需要令牌）和本机转发（Spec 第 15 节，不需要令牌，只有两个路径）。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import pathlib
import sys

import uvicorn

from . import logs
from .app import create_app
from .config import Config
from .net import LOOPBACK, forward_app


def _silence_uvicorn() -> None:
    """uvicorn 的出错日志会带异常全文（可能含路径、内容），不符合 Spec 4.5；错误由本服务按类名自己记。"""
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi"):
        lg = logging.getLogger(name)
        lg.handlers = [logging.NullHandler()]
        lg.propagate = False


def _server(app, port: int) -> uvicorn.Server:
    # access_log 关掉：访问日志会带查询参数（检索词等），不符合 Spec 4.5
    return uvicorn.Server(uvicorn.Config(app, host=LOOPBACK, port=port, access_log=False, log_level="warning",
                                         log_config=None, lifespan="on"))


async def _serve(config: Config) -> None:
    _silence_uvicorn()
    app = create_app(config)
    main = _server(app, config.port)
    fwd = _server(forward_app(app.state.lb.net), config.forward_port)

    async def run_forward() -> None:
        try:
            await fwd.serve()
        except (OSError, SystemExit) as e:  # 转发端口被占用不影响工作台接口
            logs.event("forward", "listen", status="fail", error=type(e).__name__)

    await asyncio.gather(main.serve(), run_forward())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m lawbench")
    ap.add_argument("--port", type=int)
    ap.add_argument("--token")
    ap.add_argument("--appdata", type=pathlib.Path)
    ap.add_argument("--forward-port", type=int)
    a = ap.parse_args(argv)
    config = Config.from_env(port=a.port, token=a.token, appdata=a.appdata, forward_port=a.forward_port)
    asyncio.run(_serve(config))
    return 0


if __name__ == "__main__":
    sys.exit(main())
