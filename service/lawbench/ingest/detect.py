"""按扩展名和文件头判断材料格式（Spec 5.1 第 2 步）。"""
from __future__ import annotations

import pathlib
import zipfile

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

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


def ole_encrypted(path: pathlib.Path) -> bool:
    """Office 加密文件：OLE 容器且含 EncryptionInfo 流（Spec 5.2）。"""
    import olefile
    try:
        with olefile.OleFileIO(str(path)) as ole:
            return ole.exists("EncryptionInfo")
    except Exception:  # noqa: BLE001
        return False


def is_zip(path: pathlib.Path) -> bool:
    return zipfile.is_zipfile(path)
