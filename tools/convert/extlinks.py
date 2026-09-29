"""转换前检查旧版 Office 文件里指向外部地址的链接（Spec 14.3：查到就拒绝转换）。

LibreOffice 导入 .doc / .wps 时会去取 INCLUDEPICTURE 等域链接的外部图片，配置项挡不住，所以在交给它之前先查：
- OLE 复合文档（.doc、.wps、.xls）：在 WordDocument / 1Table / 0Table / Workbook 等流的文字里
  （UTF-16LE 和单字节两种编码都查）找链接类域代码 INCLUDEPICTURE、INCLUDETEXT、LINK、IMPORT、DDE、DDEAUTO，
  其后紧跟的目标以 http://、https://、ftp://、file://、\\\\（UNC）开头即判为外链；
  Data 流（图片和链接图片的存放处）里出现单字节存放的上述地址前缀也判为外链（链接图片的路径这样存；
  普通超链接的地址在 Data 流里是 UTF-16，不算）。
- 不是 OLE 复合文档的 .doc / .wps（可能是改了扩展名的 RTF、HTML）：文件里出现上述地址前缀即判为外链。
正文里普通的网址文字和 HYPERLINK 超链接不算（它们不会被自动取回）；分不清的情形按外链处理（宁可误拒）。
"""
from __future__ import annotations

import re
from pathlib import Path

LINK_FIELDS = ("INCLUDEPICTURE", "INCLUDETEXT", "LINK", "IMPORT", "DDEAUTO", "DDE")
PREFIXES = ("http://", "https://", "ftp://", "file://", "\\\\")
DATA_STREAMS = ("Data",)
REASON = ("文档里有指向外部地址的图片或链接，为避免联网没有转换；"
          "请在 Word 或 WPS 里断开链接（或另存为 docx）后再试")


def _field_re() -> re.Pattern:
    fields = "|".join(LINK_FIELDS)
    pre = "|".join(re.escape(p) for p in PREFIXES)
    # 域代码形如：INCLUDEPICTURE  "http://x/y.png" \d   或不带引号
    return re.compile(rf"\b(?:{fields})\b\s+(?:\\\*\s*\w+\s+)?\"?\s*(?:{pre})", re.I)


FIELD_RE = _field_re()


def _texts(data: bytes) -> list[str]:
    return [data.decode("utf-16-le", "ignore"), data.decode("latin-1")]


def _has_prefix(data: bytes, utf16: bool = True) -> bool:
    low = data.lower()
    for p in PREFIXES:
        if p.encode("ascii") in low or (utf16 and p.encode("utf-16-le") in low):
            return True
    return False


def has_external_links(path: Path) -> bool:
    import olefile
    path = Path(path)
    if not olefile.isOleFile(str(path)):
        return _has_prefix(path.read_bytes())
    with olefile.OleFileIO(str(path)) as ole:
        for entry in ole.listdir(streams=True, storages=False):
            name = entry[-1]
            try:
                data = ole.openstream(entry).read()
            except OSError:
                continue
            # 链接图片的路径在 Data 流里是单字节存的；普通超链接的地址在那里是 UTF-16，不算
            if name in DATA_STREAMS and _has_prefix(data, utf16=False):
                return True
            if any(FIELD_RE.search(t) for t in _texts(data)):
                return True
    return False
