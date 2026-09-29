"""LibreOffice 转换（Spec 5.2）：doc/wps → docx，xls → xlsx，xlsx 重算。

soffice --headless --norestore -env:UserInstallation=file:///<案件>/工作区/临时/lo_profile
        --convert-to <格式> --outdir <临时目录> <文件>
- 原件先复制进 工作区/临时/ 再转换，LibreOffice 不直接打开原件（不在原件旁留锁文件）；
- 用户配置目录放在案件临时目录，路径做 URL 编码；转换后连同中间文件一起删除（SEC-11）；
- 超时 120 秒；同一时刻只跑一个转换。
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import threading
import uuid
from contextlib import contextmanager

from . import LO_TIMEOUT, ParseError

_LOCK = threading.Lock()

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
        work = self.temp_dir / f"lo-{uuid.uuid4().hex[:8]}"
        work.mkdir(parents=True, exist_ok=False)
        try:
            yield _Session(self, work)
        finally:
            shutil.rmtree(work, ignore_errors=True)
            shutil.rmtree(self.temp_dir / "lo_profile", ignore_errors=True)


class _Session:
    def __init__(self, conv: Converter, work: pathlib.Path):
        self.conv = conv
        self.work = work
        self.n = 0

    def convert(self, src: pathlib.Path, fmt: str) -> pathlib.Path:
        if not self.conv.soffice:
            raise ParseError("convert_failed")
        self.n += 1
        job = self.work / str(self.n)
        (job / "out").mkdir(parents=True)
        local = job / ("in" + src.suffix.lower())
        shutil.copyfile(src, local)
        profile = (self.conv.temp_dir / "lo_profile").resolve().as_uri()
        args = [self.conv.soffice, "--headless", "--norestore", "--nologo", "--nodefault", "--nolockcheck",
                f"-env:UserInstallation={profile}", "--convert-to", fmt, "--outdir", str(job / "out"), str(local)]
        with _LOCK:
            try:
                subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=LO_TIMEOUT,
                               check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except (subprocess.TimeoutExpired, OSError):
                raise ParseError("convert_failed")
        out = job / "out" / ("in." + fmt)
        if not out.is_file() or out.stat().st_size == 0:
            raise ParseError("convert_failed")
        return out
