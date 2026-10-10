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

from . import logs, portdiag
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


EXIT_LISTEN_FAILED = 2


def _report_port(port: int) -> None:
    """绑不上的端口：标准错误写一行"<类别> <端口> <一句话>"（portdiag；Host 按类别给律师看）。按 UTF-8 写，不随控制台代码页。"""
    text = portdiag.line(port, portdiag.classify(port, portdiag.bind_error(LOOPBACK, port)))
    try:
        sys.stderr.buffer.write((text + "\n").encode("utf-8"))
        sys.stderr.flush()
    except (AttributeError, OSError, ValueError):
        pass


async def _serve(config: Config) -> int:
    """两个监听任一绑定失败：另一个也停下，进程以非零码退出，交给 Host 按 Spec 1.3 处理。"""
    _silence_uvicorn()
    app = create_app(config)
    servers = {"main": _server(app, config.port),
               "forward": _server(forward_app(app.state.lb.net), config.forward_port)}
    ports = {"main": config.port, "forward": config.forward_port}
    failed: list[str] = []

    async def run(name: str) -> None:
        try:
            await servers[name].serve()
        except (OSError, SystemExit) as e:  # uvicorn 绑定失败时 sys.exit(1)
            failed.append(name)
            logs.event(name, "listen", status="fail", error=type(e).__name__)
            _report_port(ports[name])
        for s in servers.values():
            s.should_exit = True

    await asyncio.gather(run("main"), run("forward"))
    return EXIT_LISTEN_FAILED if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m lawbench")
    ap.add_argument("--port", type=int)
    ap.add_argument("--token")
    ap.add_argument("--appdata", type=pathlib.Path)
    ap.add_argument("--forward-port", type=int)
    a = ap.parse_args(argv)
    config = Config.from_env(port=a.port, token=a.token, appdata=a.appdata, forward_port=a.forward_port)
    return asyncio.run(_serve(config))


if __name__ == "__main__":
    sys.exit(main())
