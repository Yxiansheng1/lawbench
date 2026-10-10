"""监听端口绑不上时的原因分类（第七版待办 10，rv-A50 NOTE）。

服务启动绑定失败时，标准错误的**第一行**是 `<类别> <端口> <给律师看的一句话>`，类别是下面三个常量之一，
客户端（Host）按类别展示；这不是契约面，类别字面只在本文件定义。

- PORT_IN_USE：端口被别的程序占着（WinError 10048 / EADDRINUSE）。
- PORT_RESERVED：WinError 10013 且端口落在 Windows 的保留端口段里
  （`netsh int ipv4 show excludedportrange protocol=tcp`，Hyper-V、WSL 常见）——不是别人占了，换端口才行。
- PORT_DENIED：其余（10013 但不在保留段、查不到保留段、别的错误）。

查保留段只跑一次 netsh、超时 3 秒；跑不了、超时、解析不出都按 PORT_DENIED。
"""
from __future__ import annotations

import errno
import functools
import os
import re
import socket
import subprocess
import sys

PORT_IN_USE = "PORT_IN_USE"
PORT_RESERVED = "PORT_RESERVED"
PORT_DENIED = "PORT_DENIED"

MESSAGES = {
    PORT_IN_USE: "{port} 端口被其他程序占用，请关闭占用程序后重试",
    PORT_RESERVED: "{port} 在 Windows 保留端口段内，请在设置里换一个端口",
    PORT_DENIED: "{port} 端口无法监听（系统拒绝），请换一个端口或联系技术支持",
}

WSAEACCES, WSAEADDRINUSE = 10013, 10048
# 用系统目录里的 netsh（绝对路径），不靠 PATH 找
NETSH = [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "netsh.exe"),
         "int", "ipv4", "show", "excludedportrange", "protocol=tcp"]
NETSH_TIMEOUT = 3.0
_RANGE = re.compile(r"^\s*(\d{1,5})\s+(\d{1,5})\b")


def parse_excluded(text: str) -> list[tuple[int, int]]:
    """netsh 输出里每行"开始端口 结束端口"（后面可能带 *）；表头、分隔线、说明行不是两个数字开头，自然跳过。"""
    out = []
    for line in text.splitlines():
        m = _RANGE.match(line)
        if m and int(m.group(1)) <= int(m.group(2)) <= 65535:
            out.append((int(m.group(1)), int(m.group(2))))
    return out


@functools.lru_cache(maxsize=1)
def run_netsh() -> str | None:
    """只在 Windows 上跑；失败、超时返回 None。输出只取数字，按什么代码页解码都行。
    一个进程里只跑一次（两个端口都绑不上时不重复跑）。"""
    if sys.platform != "win32":
        return None
    try:
        p = subprocess.run(NETSH, capture_output=True, timeout=NETSH_TIMEOUT,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.decode("mbcs", "replace") if p.returncode == 0 else None


def bind_error(host: str, port: int) -> OSError | None:
    """再绑一次拿到系统的错误（uvicorn 绑定失败只给 SystemExit，不带原因）。绑得上（刚被放开）返回 None。"""
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((host, port))
    except OSError as e:
        return e
    finally:
        if s is not None:
            s.close()
    return None


def classify(port: int, err: OSError | None, netsh=run_netsh) -> str:
    code = getattr(err, "winerror", None) or getattr(err, "errno", None)
    if code in (WSAEADDRINUSE, errno.EADDRINUSE):
        return PORT_IN_USE
    if code in (WSAEACCES, errno.EACCES):
        text = netsh()
        if text is not None and any(a <= port <= b for a, b in parse_excluded(text)):
            return PORT_RESERVED
    return PORT_DENIED


def line(port: int, category: str) -> str:
    return f"{category} {port} {MESSAGES[category].format(port=port)}"
