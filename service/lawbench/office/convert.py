"""Word 转 PDF（Spec 12.3、14.3）：Word → WPS → 内置 LibreOffice，按设置 converter 选择。

- auto：三个依次试；设置里指定了某一个（word / wps / libreoffice）就只用它，不换别的（律所为避免 Word / WPS
  在案件外留痕而改成 libreoffice 时，不能再悄悄退回 Word）。
- 源文件先经闸门复制到 工作区/临时/<本次>/，转换程序只打开副本。
- Word / WPS：每次在单独的子进程（com_worker）里做，120 秒超时；超时或出错时结束该子进程，并结束本次转换让 COM
  启动的 Word / WPS 进程——只认"本次开始后才出现、由 COM 启动（父进程是 svchost）"的那几个，不动律师自己开着的。
  成功后也等它们自己退出，5 秒没退的同样结束，不留隐藏窗口和残留进程。
- LibreOffice：复用 ingest/libreoffice 的 Converter（独立配置目录、外链拦截、超时杀树）；.doc / .wps、xlsx
  交给它之前按 14.3 ②a、②b 查外链，有就不交（这一份用 LibreOffice 转不了）。
- 不调用任何打印接口，不改系统默认打印机。三种都失败：CONVERTER_UNAVAILABLE。
"""
from __future__ import annotations

import ctypes
import os
import pathlib
import re
import subprocess
import sys
import threading
import time
from ctypes import wintypes

from .. import logs
from ..case import gate
from ..errors import ApiError
from ..ingest import ParseError, detect, links
from ..ingest import libreoffice as lo
from ..procs import kill_tree

TIMEOUT = 120          # 秒；测试里可改小
QUIT_WAIT = 5.0
ORDER = ("word", "wps", "libreoffice")
PROGIDS = {"word": ("Word.Application",), "wps": ("KWPS.Application", "WPS.Application")}
SERVER_EXE = {"word": ("winword.exe",), "wps": ("wps.exe", "wpsoffice.exe")}
WORD_TYPES = {".docx", ".doc", ".wps", ".docm", ".dotx", ".rtf"}
LO_ONLY = {".xlsx", ".xls", ".xlsm", ".csv", ".txt", ".odt", ".ods"}
# 测试可替换：Word / WPS 子进程的命令（默认 python -m lawbench.office.com_worker）
WORKER_CMD: list[str] | None = None
_PKG_PARENT = str(pathlib.Path(__file__).resolve().parents[2])
_COM_LOCK = threading.Lock()


class _Failed(Exception):
    """这一个程序转不了，换下一个。"""


# ---------------------------------------------------------------- 进程快照（Toolhelp32）

class _PE32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


def processes() -> dict[int, tuple[int, str]]:
    """{pid: (父 pid, 小写的程序名)}。"""
    out: dict[int, tuple[int, str]] = {}
    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    if snap in (None, wintypes.HANDLE(-1).value):
        return out
    try:
        e = _PE32()
        e.dwSize = ctypes.sizeof(_PE32)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile.lower())
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return out


def com_started(before: dict, after: dict, exes: tuple[str, ...]) -> list[int]:
    """本次开始后才出现、程序名是 Word / WPS、父进程是 svchost（COM 启动）的进程。律师双击打开的 Word
    父进程是 explorer，开始前就开着的不在"新出现"里，都不算。"""
    out = []
    for pid, (ppid, exe) in after.items():
        if pid in before or exe not in exes:
            continue
        parent = after.get(ppid) or before.get(ppid)
        if parent is not None and parent[1] == "svchost.exe":
            out.append(pid)
    return out


def word_has_external(path: pathlib.Path) -> bool:
    """交给 Word / WPS 之前查外链（2026-10-01 T23 实测：Word 打开带"链接到文件"图片的 docx 并导出 PDF 时会去取图，
    关掉 UpdateLinksAtOpen 也一样）。有外链、或查不了，就不交给 Word / WPS，只能走 LibreOffice（它有外链拦截）。
    **按文件头分流，不看扩展名**（T23 复核 P1-2：docx 改名 .doc 曾走二进制检查漏判）：
    - OLE（旧版二进制、加密的新版）：加密的不交；14.3 ②a 的检查；
    - 压缩包（docx 类）：任何关系文件里 TargetMode="External"（超链接除外：点了才打开）；正文、页眉页脚里链接类域
      （INCLUDEPICTURE 等）的指令里有外部地址（同一部件的域指令连起来查，宁可多拦）；altChunk 内嵌的 HTML 里有外部地址；
    - 其他（RTF、HTML、文本冒充 Word 文档）：一律不交 Word / WPS。"""
    try:
        kind = detect.content_kind(path)
        if kind == "ole":
            return detect.ole_encrypted(path) or links.has_external_picture(path)
        if kind != "zip":
            return True
        if links.xlsx_has_external_rels(path) or _altchunk_external(path):   # 函数名是 xlsx，对任何 OOXML 都成立
            return True
        with links.open_zip(path) as z:
            for n in z.namelist():
                if not (n.startswith("word/") and n.endswith(".xml")) or "/_rels/" in n:
                    continue
                root = links._rels_root(z, n)
                instr = [t.text or "" for t in root.iter(f"{{{_W}}}instrText")]
                instr += [e.get(f"{{{_W}}}instr") or "" for e in root.iter(f"{{{_W}}}fldSimple")]
                if instr and links._field_has_link("\x13" + " ".join(instr)):
                    return True
        return False
    except (ParseError, OSError):
        return True


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_HTML_URL = re.compile(rb"""(?:src|href|data|background)\s*=\s*["']?\s*(?:https?:|ftp:|file:|\\\\)""", re.IGNORECASE)


def _altchunk_external(path: pathlib.Path) -> bool:
    """docx 的 altChunk 内嵌 HTML / MHT 部件里有没有指向外部的 src、href 等（复核 NOTE-2，只做这一条低成本的）。"""
    with links.open_zip(path) as z:
        for n in z.namelist():
            if n.lower().endswith((".html", ".htm", ".mht", ".mhtml", ".xhtml")) and _HTML_URL.search(z.read(n)):
                return True
    return False


def _kill_pid(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


# ---------------------------------------------------------------- 转换

class OfficeConverter:
    def __init__(self, lo_base: pathlib.Path, soffice: str | None = None):
        self.lo_base = pathlib.Path(lo_base)
        self.soffice = soffice

    def to_pdf(self, root: str, src: pathlib.Path, job_rel: str, choice: str = "auto") -> tuple[pathlib.Path, str]:
        """把原件 src 转成 PDF，返回 (pdf 路径（在 工作区/临时/<本次>/ 里）, 实际用的程序)。"""
        ext = src.suffix.lower()
        order = ORDER if choice == "auto" else (choice,)
        if ext in LO_ONLY:
            order = tuple(o for o in order if o == "libreoffice")
        elif ext not in WORD_TYPES:
            raise ApiError("INVALID_ARGUMENT", "not_convertible")
        n = len(list(gate.resolve_internal(root, job_rel, op="convert").glob("c*"))) + 1
        sub = f"{job_rel}/c{n}"
        local = gate.write_bytes(root, f"{sub}/in{ext}", src.read_bytes(), op="convert")
        if any(o != "libreoffice" for o in order) and word_has_external(local):
            logs.event("office", "convert", status="fail", error="external_link_skip_com")
            order = tuple(o for o in order if o == "libreoffice")
        for name in order:
            t0 = time.monotonic()
            try:
                out = self._lo(root, local, sub) if name == "libreoffice" else self._com(name, local)
            except _Failed as f:
                logs.event("office", "convert", status="fail", error=f"{name}:{f}",
                           duration_ms=(time.monotonic() - t0) * 1000)
                continue
            logs.event("office", "convert", error=name, duration_ms=(time.monotonic() - t0) * 1000)
            return out, name
        raise ApiError("CONVERTER_UNAVAILABLE", "all_failed")

    # ---------- Word / WPS ----------

    def _com(self, name: str, local: pathlib.Path) -> pathlib.Path:
        with _COM_LOCK:                   # 一次只做一个：收尾按"本次期间新出现"认进程，并发会互相误杀（复核 NOTE-1）
            return self._com_locked(name, local)

    def _com_locked(self, name: str, local: pathlib.Path) -> pathlib.Path:
        out = local.with_name("out.pdf")
        for progid in PROGIDS[name]:
            code = self._run_worker(name, progid, local, out)
            if code == 0 and out.is_file() and out.stat().st_size > 0:
                return out
            if code != 2:                          # 程序在但转换出错 / 超时：不再试同一程序的另一个名字
                raise _Failed("timeout" if code is None else f"exit{code}")
        raise _Failed("not_installed")

    def _run_worker(self, name: str, progid: str, local: pathlib.Path, out: pathlib.Path) -> int | None:
        cmd = (WORKER_CMD or [sys.executable, "-m", "lawbench.office.com_worker"]) + [progid, str(local), str(out)]
        env = dict(os.environ, PYTHONPATH=_PKG_PARENT + os.pathsep + os.environ.get("PYTHONPATH", ""))
        before = processes()
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            return 2
        code: int | None
        try:
            proc.communicate(timeout=TIMEOUT)
            code = proc.returncode
        except subprocess.TimeoutExpired:        # 卡在"等待打印机"之类的弹窗：结束子进程和它让 COM 启动的程序
            kill_tree(proc, drain=True)
            code = None
        self._reap(name, before, wait=0.0 if code is None else QUIT_WAIT)
        return code

    @staticmethod
    def _reap(name: str, before: dict, wait: float) -> None:
        end = time.monotonic() + wait
        while True:
            left = com_started(before, processes(), SERVER_EXE[name])
            if not left or time.monotonic() >= end:
                break
            time.sleep(0.2)
        for pid in left:
            _kill_pid(pid)
            logs.event("office", "reap", status="fail", error=name)
        end = time.monotonic() + QUIT_WAIT                 # 结束是异步的：等它们真的没了再返回
        while left and time.monotonic() < end:
            time.sleep(0.2)
            alive = processes()
            left = [p for p in left if p in alive]
        if left:
            logs.event("office", "reap", status="fail", error=f"{name}:still_alive")

    # ---------- LibreOffice ----------

    def _lo(self, root: str, local: pathlib.Path, sub: str) -> pathlib.Path:
        """交给 LibreOffice 之前按文件头查（T23 复核 P1-1、NOTE-3：旧版 .doc 改名 .docx 曾不经检查直接转换）：
        - Word 类：OLE → 加密的不转、14.3 ②a 查外链；压缩包 → 照转（配置里拦外链图片），altChunk HTML 有外部地址的不转；
          其他（RTF、HTML 冒充）→ 不转；
        - 表格类：OLE → 加密的不转；压缩包 → 14.3 ②b 查外部关系；其他 → 不转；
        - 文本类（txt、csv）：文件头是 OLE / 压缩包 / PDF 的不转；开头 4KB 里像 HTML、RTF 的不转（防 LibreOffice 按内容
          认成网页去取图）。
        副本扩展名按文件头定（与 T5 X1 同口径）。"""
        ext = local.suffix.lower()
        try:
            kind = detect.content_kind(local)
            if ext in WORD_TYPES:
                if kind == "ole":
                    if detect.ole_encrypted(local) or links.has_external_picture(local):
                        raise _Failed("encrypted_or_external_link")
                    suffix = ".doc"
                elif kind == "zip":
                    if _altchunk_external(local):
                        raise _Failed("external_link")
                    suffix = ".docx"
                else:
                    raise _Failed("not_office_file")
            elif ext in (".xlsx", ".xlsm", ".xls"):
                if kind == "ole":
                    if detect.ole_encrypted(local):
                        raise _Failed("encrypted")
                    suffix = ".xls"
                elif kind == "zip":
                    if links.xlsx_has_external_rels(local):
                        raise _Failed("external_link")
                    suffix = ".xlsx"
                else:
                    raise _Failed("not_office_file")
            else:
                head = local.read_bytes()[:4096].lower()
                if kind != "other" or any(m in head for m in (b"<html", b"<img", b"<iframe", b"<link", b"{\\rtf",
                                                                b"<?xml", b"<svg")):
                    raise _Failed("not_plain_text")
                suffix = ext
        except ParseError:
            raise _Failed("unchecked")
        conv = lo.Converter(gate.resolve_internal(root, sub, op="convert"), self.lo_base, soffice=self.soffice)
        try:
            with conv.session() as s:
                tmp = s.convert(local, "pdf", suffix=suffix)
                out = local.with_name("out.pdf")
                os.replace(tmp, out)           # 会话结束时会删它自己的工作目录；结果先挪到本次目录
        except ParseError as e:
            raise _Failed(str(e))
        return out
