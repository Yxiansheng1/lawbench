"""LibreOffice 转换（Spec 5.2）：doc/wps → docx，xls → xlsx，xlsx 重算。

soffice --headless --norestore -env:UserInstallation=file:///<短路径>/p
        --convert-to <格式> --outdir <临时目录> <文件>
- 原件先复制进 工作区/临时/ 再转换，LibreOffice 不直接打开原件（不在原件旁留锁文件）；
- 用户配置目录和 LibreOffice 自己的临时文件（TMP/TEMP）放在系统临时目录下一个每次新建的短路径目录里：
  配置目录内部层级很深，放在案件临时目录下时，案件路径一长就超过 Windows 260 字符上限，soffice 直接崩溃
  （T3 第二轮复核实测）。路径做 URL 编码；会话结束时连同中间文件一起删除（SEC-11），不留材料副本；
- 超时 120 秒；同一时刻只跑一个转换。
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager

from . import LO_TIMEOUT, ParseError

_LOCK = threading.Lock()
TIMEOUT = LO_TIMEOUT  # 秒；测试里可改小
SHORT_PREFIX = "lbo-"  # 系统临时目录下每次新建的短路径目录

CANDIDATES = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]


def find_soffice() -> str | None:
    """查找顺序：环境变量 LB_SOFFICE → PATH → 默认安装位置。"""
    env = os.environ.get("LB_SOFFICE")
    if env and os.path.isfile(env):
        return env
    found = shutil.which("soffice")
    if found:
        return found
    for c in CANDIDATES:
        if os.path.isfile(c):
            return c
    return None


class Converter:
    """绑定一个案件的 工作区/临时/。convert() 返回的文件在 session() 结束时删除。"""

    def __init__(self, temp_dir: pathlib.Path, soffice: str | None = None):
        self.temp_dir = pathlib.Path(temp_dir)
        self.soffice = soffice or find_soffice()

    @contextmanager
    def session(self):
        """临时目录在第一次真正转换时才建（大多数材料不需要 LibreOffice）；会话结束时删除。"""
        s = _Session(self)
        try:
            yield s
        finally:
            if s.work is not None:
                _rmtree(s.work)
            if s.short is not None:
                _rmtree(s.short)


def _rmtree(path: pathlib.Path) -> None:
    """进程刚被结束时文件可能还被占用：重试几次，保证不留材料副本。"""
    for _ in range(20):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(0.1)


# Spec 14.3：LibreOffice 会按文档里的外部链接去取图；每次启动前在独立用户配置目录里关掉
BLOCK_LINKS_XCU = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop></item>
</oor:items>
"""


def write_profile(profile_dir: pathlib.Path) -> None:
    user = profile_dir / "user"
    user.mkdir(parents=True, exist_ok=True)
    (user / "registrymodifications.xcu").write_text(BLOCK_LINKS_XCU, encoding="utf-8")


def kill_tree(proc: subprocess.Popen) -> None:
    """只结束本次启动的进程及其子进程（soffice.exe 会再拉起 soffice.bin），不动律师自己开着的程序。"""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


class _Session:
    def __init__(self, conv: Converter):
        self.conv = conv
        self.work: pathlib.Path | None = None   # 工作区/临时/lo-xxxxxxxx：原件副本和转换结果
        self.short: pathlib.Path | None = None  # 系统临时目录下的 lbo-xxxx：配置目录和 LibreOffice 的 TMP
        self.n = 0

    def _ensure_dirs(self) -> None:
        if self.work is None:
            work = self.conv.temp_dir / f"lo-{uuid.uuid4().hex[:8]}"
            work.mkdir(parents=True, exist_ok=False)
            self.work = work
        if self.short is None:
            self.short = pathlib.Path(tempfile.mkdtemp(prefix=SHORT_PREFIX))

    def convert(self, src: pathlib.Path, fmt: str) -> pathlib.Path:
        """只用 --convert-to 导出，不走任何打印接口，不改系统默认打印机（Spec 12.3）。"""
        if not self.conv.soffice:
            raise ParseError("convert_failed")
        try:
            self._ensure_dirs()
        except OSError:
            raise ParseError("path_too_long")  # 案件临时目录都建不出来：多半是路径太深
        self.n += 1
        job = self.work / str(self.n)
        (job / "out").mkdir(parents=True)
        local = job / ("in" + src.suffix.lower())
        shutil.copyfile(src, local)
        profile_dir = (self.short / "p").resolve()
        write_profile(profile_dir)
        tmp = self.short / "t"
        tmp.mkdir(exist_ok=True)
        args = [self.conv.soffice, "--headless", "--norestore", "--nologo", "--nodefault", "--nolockcheck",
                f"-env:UserInstallation={profile_dir.as_uri()}", "--convert-to", fmt, "--outdir", str(job / "out"),
                str(local)]
        # LibreOffice 自己的临时文件也落在本次的短路径目录里，会话结束一起删掉；系统临时目录不留材料副本
        env = dict(os.environ, TMP=str(tmp), TEMP=str(tmp), TMPDIR=str(tmp))
        with _LOCK:
            try:
                proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError:
                raise ParseError("convert_failed")
            try:
                proc.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                kill_tree(proc)
                raise ParseError("convert_failed")
        out = job / "out" / ("in." + fmt)
        if not out.is_file() or out.stat().st_size == 0:
            raise ParseError("convert_failed")
        return out
