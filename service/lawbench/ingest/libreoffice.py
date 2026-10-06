"""LibreOffice 转换（Spec 5.2）：doc/wps → docx，xls → xlsx，xlsx 重算。

soffice --headless --norestore -env:UserInstallation=file:///<应用数据>/临时/lo/<8 位随机>/p
        --convert-to <格式> --outdir <临时目录> <文件>
- 原件先复制进 <案件>/工作区/临时/ 再转换，LibreOffice 不直接打开原件（不在原件旁留锁文件）；
  被转换的副本和转换结果都在那里，会话结束删除。
- 用户配置目录和 LibreOffice 自己的临时文件（TMP/TEMP）放在 <应用数据>/临时/lo/<8 位随机>/（Spec 5.2，
  注记 致B-ORCH-注记-LibreOffice三件事-20260929-2218）：配置目录内部层级很深，自身路径约 146 字符时 soffice
  直接崩溃（0xC0000409）；放在案件目录下，案件路径一长就会崩。每次会话新建、用完删除（用 \\\\?\\ 长路径前缀并重试，
  删不掉就记日志）；服务启动时清掉上次的残留（配置目录里会留"最近打开的文件"记录，SEC-11）。
- 配置目录路径超过 100 字符不调用 soffice，失败原因"软件的数据目录路径太长"。
- 超时 120 秒只结束本次启动的进程树；同一时刻只跑一个转换；只用 --convert-to 导出，不走打印接口（Spec 12.3）。
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager

from .. import logs, procs
from . import LO_TIMEOUT, ParseError

_LOCK = threading.Lock()
TIMEOUT = LO_TIMEOUT  # 秒；测试里可改小
MAX_PROFILE_PATH = 100  # 配置目录路径的上限（146 字符实测会崩，留余量）
CRASH_EXIT_CODES = {0xC0000409, -1073740791}  # STATUS_STACK_BUFFER_OVERRUN：Windows 上按有符号或无符号报出

CANDIDATES = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]
# T28 macOS：默认安装位置（打包后 Host 传随包的 LAWBENCH_SOFFICE，用不到这里）
MAC_CANDIDATES = ["/Applications/LibreOffice.app/Contents/MacOS/soffice"]


def find_soffice() -> str | None:
    """查找顺序：环境变量 LAWBENCH_SOFFICE（设了且文件在；打包后 Host 传随包的 <安装目录>\\tools\\…）→ PATH →
    默认安装位置。"""
    env = os.environ.get("LAWBENCH_SOFFICE")
    if env and os.path.isfile(env):
        return env
    found = shutil.which("soffice")
    if found:
        return found
    for c in (MAC_CANDIDATES if sys.platform == "darwin" else CANDIDATES):
        if os.path.isfile(c):
            return c
    return None


def _long(path: pathlib.Path) -> str:
    """Windows 上加 \\\\?\\ 前缀，删除时不受 260 字符上限影响。"""
    p = os.path.abspath(path)
    if os.name == "nt" and not p.startswith("\\\\?\\"):
        return "\\\\?\\" + p
    return p


def remove_tree(path: pathlib.Path) -> bool:
    """删除目录：长路径前缀、重试（进程刚被结束时文件可能还被占用）。删不掉返回 False 并记日志。"""
    for _ in range(20):
        shutil.rmtree(_long(path), ignore_errors=True)
        if not os.path.exists(_long(path)):
            return True
        time.sleep(0.1)
    logs.event("libreoffice", "cleanup", status="fail", error="DIR_NOT_REMOVED")
    return False


def cleanup_base(lo_base: pathlib.Path) -> int:
    """服务启动时清掉 <应用数据>/临时/lo/ 下上次留下的配置目录。返回删掉的个数。"""
    if not lo_base.is_dir():
        return 0
    n = 0
    for child in lo_base.iterdir():
        if remove_tree(child):
            n += 1
    if n:
        logs.event("libreoffice", "startup_cleanup", status="ok")
    return n


class Converter:
    """绑定一个案件的 工作区/临时/。convert() 返回的文件在 session() 结束时删除。"""

    def __init__(self, temp_dir: pathlib.Path, lo_base: pathlib.Path, soffice: str | None = None):
        """lo_base 必填：<应用数据>/临时/lo（Spec 5.2）；不再有"系统临时目录"兜底（T5 返修 Y1）。"""
        self.temp_dir = pathlib.Path(temp_dir)
        self.soffice = soffice or find_soffice()
        self.lo_base = pathlib.Path(lo_base)

    @contextmanager
    def session(self):
        """临时目录在第一次真正转换时才建（大多数材料不需要 LibreOffice）；会话结束时删除。"""
        s = _Session(self)
        try:
            yield s
        finally:
            if s.work is not None:
                remove_tree(s.work)
            if s.profile_root is not None:
                remove_tree(s.profile_root)


# Spec 14.3：LibreOffice 会按文档里的外部链接去取图；每次启动前在独立用户配置目录里关掉
BLOCK_LINKS_XCU = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" \
xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="BlockUntrustedRefererLinks" \
oor:op="fuse"><value>true</value></prop></item>
</oor:items>
"""


def write_profile(profile_dir: pathlib.Path) -> None:
    user = profile_dir / "user"
    user.mkdir(parents=True, exist_ok=True)
    (user / "registrymodifications.xcu").write_text(BLOCK_LINKS_XCU, encoding="utf-8")


def kill_tree(proc: subprocess.Popen) -> None:
    """只结束本次启动的进程及其子进程（soffice.exe 会再拉起 soffice.bin），不动律师自己开着的程序。"""
    procs.kill_tree(proc)


class _Session:
    def __init__(self, conv: Converter):
        self.conv = conv
        self.work: pathlib.Path | None = None          # <案件>/工作区/临时/lo-xxxxxxxx：原件副本和转换结果
        self.profile_root: pathlib.Path | None = None  # <应用数据>/临时/lo/xxxxxxxx：配置目录 p 和 TMP t
        self.n = 0

    def _ensure_dirs(self) -> None:
        if self.profile_root is None:
            root = self.conv.lo_base / uuid.uuid4().hex[:8]
            if len(str((root / "p").resolve())) > MAX_PROFILE_PATH:
                raise ParseError("appdata_too_long")
            root.mkdir(parents=True, exist_ok=False)
            self.profile_root = root
        if self.work is None:
            work = self.conv.temp_dir / f"lo-{uuid.uuid4().hex[:8]}"
            try:
                work.mkdir(parents=True, exist_ok=False)
            except OSError:
                raise ParseError("path_too_long")  # 案件临时目录都建不出来：多半是案件路径太深
            self.work = work

    def convert(self, src: pathlib.Path, fmt: str, suffix: str | None = None) -> pathlib.Path:
        """只用 --convert-to 导出，不走任何打印接口，不改系统默认打印机（Spec 12.3）。
        suffix：副本用的扩展名，按文件头定的真实格式（X1）；不给就用原件的扩展名。"""
        if not self.conv.soffice:
            raise ParseError("no_converter")
        self._ensure_dirs()
        self.n += 1
        job = self.work / str(self.n)
        (job / "out").mkdir(parents=True)
        local = job / ("in" + (suffix or src.suffix.lower()))
        shutil.copyfile(src, local)
        profile_dir = (self.profile_root / "p").resolve()
        write_profile(profile_dir)
        tmp = self.profile_root / "t"
        tmp.mkdir(exist_ok=True)
        args = [self.conv.soffice, "--headless", "--norestore", "--nologo", "--nodefault", "--nolockcheck",
                f"-env:UserInstallation={profile_dir.as_uri()}", "--convert-to", fmt, "--outdir", str(job / "out"),
                str(local)]
        # LibreOffice 自己的临时文件也落在本次的配置目录旁边，会话结束一起删掉；系统临时目录不留材料副本
        env = procs.python_env(dict(os.environ, TMP=str(tmp), TEMP=str(tmp), TMPDIR=str(tmp)))   # LibreOffice 自带 Python
        with _LOCK:
            try:
                proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **procs.own_group())
            except OSError:
                raise ParseError("no_converter")
            try:
                code = proc.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                kill_tree(proc)
                raise ParseError("convert_timeout")
        if code in CRASH_EXIT_CODES:
            logs.event("libreoffice", "convert", status="fail", error="CRASH_0xC0000409")
            raise ParseError("converter_crashed")
        out = job / "out" / ("in." + fmt)
        if not out.is_file() or out.stat().st_size == 0:
            raise ParseError("convert_failed")
        return out
