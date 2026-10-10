"""把文件移到系统回收站（契约 1.4 materials_remove；SEC-08 口径：律师确认后移到回收站，不永久删除）。

- Windows：SHFileOperationW + FOF_ALLOWUNDO（进回收站，可还原），不弹确认框、不弹出错框。
- macOS：移到 ~/.Trash（重名加序号）。
- 其他系统：不支持，抛 OSError（调用方按"移不了"处理，不退回成永久删除）。
失败一律抛 OSError，由调用方给律师一句中文原因；这里不记日志、不带路径。
"""
from __future__ import annotations

import os
import shutil
import sys


def recycle(path: str | os.PathLike) -> None:
    p = os.path.abspath(os.fspath(path))
    if not os.path.lexists(p):
        raise FileNotFoundError(p)
    if sys.platform == "win32":
        _recycle_windows(p)
    elif sys.platform == "darwin":
        _recycle_macos(p)
    else:
        raise OSError("recycle bin not supported on this platform")
    if os.path.lexists(p):
        raise OSError("still there after recycle")


def _recycle_windows(p: str) -> None:
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", ctypes.c_void_p),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE = 0x0003
    FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x0004, 0x0010, 0x0040, 0x0400
    buf = ctypes.create_unicode_buffer(p + "\0")      # pFrom 要以两个 NUL 结尾：这里一个，缓冲区自己再补一个
    op = SHFILEOPSTRUCTW(None, FO_DELETE, ctypes.cast(buf, ctypes.c_void_p), None,
                         FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI, False, None, None)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0 or op.fAnyOperationsAborted:
        raise OSError(f"SHFileOperationW failed: {rc}")


def _recycle_macos(p: str) -> None:
    trash = os.path.join(os.path.expanduser("~"), ".Trash")
    os.makedirs(trash, exist_ok=True)
    base = os.path.basename(p)
    stem, ext = os.path.splitext(base)
    dst, n = os.path.join(trash, base), 1
    while os.path.lexists(dst):
        n += 1
        dst = os.path.join(trash, f"{stem} {n}{ext}")
    shutil.move(p, dst)
