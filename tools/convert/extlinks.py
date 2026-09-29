"""转换前检查旧版 Office 文件里指向外部地址的链接（Spec 14.3：查到就拒绝转换）。

LibreOffice 导入 .doc / .wps 时会去取 INCLUDEPICTURE 等域链接的外部图片，配置项挡不住，所以在交给它之前先查：
- OLE 复合文档（.doc、.wps）：只在 Word 域指令范围内查——域开始符 0x13 到分隔符 0x14 或结束符 0x15 之间。
  链接类域名 INCLUDEPICTURE、INCLUDETEXT、LINK、IMPORT、DDE、DDEAUTO 之后、同一段域指令之内任意位置出现
  http://、https://、ftp://、file:// 或 \\\\（UNC）即判为外链，不管开关在前在后、中间夹多少空白和引号。
  UTF-16LE 和单字节两种解码都查。正文里的普通文字（例如英文 "see the link http://…"）不在域指令里，不触发。
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


FIELD_BEGIN, FIELD_SEP, FIELD_END = "\x13", "\x14", "\x15"
_NAME_RE = re.compile(r"\b(?:" + "|".join(LINK_FIELDS) + r")\b", re.I)
_INSTR_RE = re.compile(FIELD_BEGIN + "([^" + FIELD_BEGIN + FIELD_SEP + FIELD_END + "]*)")


def instructions(text: str) -> list[str]:
    """Word 域指令：域开始符 0x13 到下一个分隔符 0x14、结束符 0x15（或嵌套域的开始符）之间的文字。"""
    return _INSTR_RE.findall(text)


def link_instruction(instr: str) -> bool:
    """链接类域名之后、同一段域指令之内任意位置出现外部地址前缀，就是外链（不管开关在前在后）。"""
    m = _NAME_RE.search(instr)
    if not m:
        return False
    rest = instr[m.end():].lower()
    return any(p in rest for p in PREFIXES)


def _texts(data: bytes) -> list[str]:
    """同一段字节按 UTF-16LE（两种对齐）和单字节各解一遍：.doc 的正文两种存法都有。"""
    return [data.decode("utf-16-le", "ignore"), data[1:].decode("utf-16-le", "ignore"), data.decode("latin-1")]


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
            if any(link_instruction(i) for t in _texts(data) for i in instructions(t)):
                return True
    return False
