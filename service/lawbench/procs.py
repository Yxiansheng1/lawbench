"""子进程收尾的共用写法：连同它拉起的子进程一起结束（T25 复核：原来三处各写一份 taskkill）。

用于：LibreOffice（soffice.exe 会再拉起 soffice.bin）、发票引擎（invoke.py 会再起缓存里的 Python）、
证件识别驱动（虚拟环境的 python.exe 只是启动器，真正的解释器是它的子进程）。只结束本次启动的进程树，
不动律师自己开着的程序。
"""
from __future__ import annotations

import os
import subprocess


def kill_tree(proc: subprocess.Popen, drain: bool = False) -> None:
    """drain=True：用 communicate() 收尾，把 stdout / stderr 管道里剩下的读空（调用方开了 PIPE 时要这样，
    否则子进程可能卡在写满的管道上）；否则只 wait()。"""
    if proc.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            proc.kill()
    try:
        proc.communicate(timeout=10) if drain else proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.communicate(timeout=5) if drain else proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
