"""按扩展名和文件头判断材料格式（Spec 5.1 第 2 步）。

扩展名只决定"是哪一类材料"（Word 类、Excel 类……）；走哪条解析、做哪道外链检查按文件头定
（T5 第一轮返修 X1：扩展名是 .xls、内容其实是 xlsx 的，不能不经检查就交给 LibreOffice）。
"""
from __future__ import annotations

import pathlib
import zipfile

from . import ParseError

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")

BY_EXT = {
    ".pdf": "pdf",
    ".docx": "docx", ".docm": "docx",
    ".doc": "doc",
    ".wps": "wps",
    ".xlsx": "xlsx", ".xlsm": "xlsx",
    ".xls": "xls",
    ".csv": "csv",
    ".md": "md", ".markdown": "md",
    ".txt": "txt",
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".tif": "image", ".tiff": "image", ".bmp": "image",
}

# 不当作材料的文件：Office 打开时的锁文件、系统缩略图等
IGNORED_PREFIXES = ("~$", ".~lock.")
IGNORED_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}


def is_ignored(name: str) -> bool:
    return name.startswith(IGNORED_PREFIXES) or name.lower() in IGNORED_NAMES


def material_type(path: pathlib.Path) -> str | None:
    """返回 material_type；不支持的格式返回 None（不进材料清单）。"""
    return BY_EXT.get(path.suffix.lower())


def head(path: pathlib.Path, n: int = 8) -> bytes:
    with open(path, "rb") as f:
        return f.read(n)


def is_ole(path: pathlib.Path) -> bool:
    return head(path) == OLE_MAGIC


def content_kind(path: pathlib.Path) -> str:
    """按文件头：ole（旧版 Office 二进制、加密的新版 Office）、zip（docx / xlsx 等压缩包格式）、pdf、other。"""
    h = head(path)
    if h == OLE_MAGIC:
        return "ole"
    if h[:4] in ZIP_MAGICS:
        return "zip"
    if h[:5] == b"%PDF-":
        return "pdf"
    return "other"


def ole_encrypted(path: pathlib.Path) -> bool:
    """Office 加密文件：OLE 容器且含 EncryptionInfo 流（Spec 5.2）。
    容器读不了时判断不了（X2）：报"无法检查"，不当成没加密放行。"""
    import olefile
    try:
        with olefile.OleFileIO(str(path)) as ole:
            return ole.exists("EncryptionInfo")
    except Exception:  # noqa: BLE001 olefile 对坏文件抛的异常种类很多
        raise ParseError("unchecked")


def is_zip(path: pathlib.Path) -> bool:
    return zipfile.is_zipfile(path)
