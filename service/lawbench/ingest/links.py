"""旧版二进制 .doc / .wps 里的外链图片检测（Spec 14.3 第 ②a 条）。

LibreOffice 的 BlockUntrustedRefererLinks 对旧版二进制格式无效，仍会去取外链图片；所以交给 LibreOffice 之前
先查文件里有没有指向 http://、https://、\\\\ 开头地址的图片链接（INCLUDEPICTURE 域），查到就不转换。
域代码可能是 UTF-16LE 或单字节编码；奇偶两种字节对齐都查。拿不准时宁可误拒；正文里普通的网址文字不触发。
"""
from __future__ import annotations

import pathlib
import re

# 域代码：INCLUDEPICTURE [开关] "地址"；地址前可能有引号、空白和 \d 之类的开关
_FIELD = re.compile(r"INCLUDEPICTURE\s+(?:\\[a-z*]+\s+)*\"?\s*(?:https?://|\\\\)", re.IGNORECASE)


def _texts(data: bytes):
    yield data.decode("latin-1")
    for off in (0, 1):
        yield data[off:].decode("utf-16-le", errors="ignore")


def has_external_picture(path: pathlib.Path) -> bool:
    data = pathlib.Path(path).read_bytes()
    return any(_FIELD.search(t) for t in _texts(data))
