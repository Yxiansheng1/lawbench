r"""外链检测（Spec 14.3 ②a、②b；注记 2106、2218）。

LibreOffice 的 BlockUntrustedRefererLinks 拦不住两类联网：旧版二进制 .doc / .wps 里的外链图片，
以及 Calc 导入 xlsx 时的外链图片和对象。所以交给 LibreOffice 之前先查，查到就不交。

.doc / .wps：
- 只在域指令范围内匹配：域开始符 0x13 到分隔符 0x14 或结束符 0x15 之间。
- 链接类域名（INCLUDEPICTURE、INCLUDETEXT、LINK、IMPORT、DDE、DDEAUTO）之后、同一段域指令内任意位置
  出现 http://、https://、ftp://、file:// 或 UNC 前缀（\\）就算外链——开关写在网址前面也拦得住。
- UTF-16LE（奇偶两种字节对齐）和单字节两种解码都查。
- 另查 OLE 容器的 Data 流：图片链接的地址以单字节存放在这里；超链接的地址是 UTF-16，不会误伤。
- 正文里普通的网址文字（包括 "see the link http://…"）不在域指令里，不触发；HYPERLINK 域不是链接类域名，不触发。

xlsx：压缩包里 xl/**/_rels/*.rels 有 TargetMode="External" 的关系（超链接和外部工作簿引用除外）即算外链。
"""
from __future__ import annotations

import pathlib
import re
import zipfile

from lxml import etree

_FIELD_NAMES = r"(?:INCLUDEPICTURE|INCLUDETEXT|LINK|IMPORT|DDEAUTO|DDE)"
# 域指令：0x13 之后到 0x14 / 0x15（或再遇到 0x13，嵌套域）为止
_INSTR = re.compile(r"\x13([^\x13\x14\x15]*)")
_LINK_FIELD = re.compile(r"(?:^|\s)" + _FIELD_NAMES + r"\b(.*)", re.IGNORECASE | re.DOTALL)
# 地址要在一个词的开头（引号或空白之后）：域代码里的本机路径 "C:\\图片\\a.png" 中间也有 \\，不能算 UNC
_URL = re.compile(r"(?:^|[\s\"'])(?:https?://|ftp://|file://|\\\\)", re.IGNORECASE)
_DATA_URL = re.compile(rb"(?:https?://|ftp://|file://|\\\\[A-Za-z0-9])([A-Za-z0-9.\-]*)", re.IGNORECASE)
# 内嵌图片自带的元数据（XMP 等）里常见的命名空间网址：不是链接，不算
_NAMESPACE_HOSTS = (b"ns.adobe.com", b"www.w3.org", b"purl.org", b"schemas.microsoft.com",
                    b"schemas.openxmlformats.org", b"iptc.org", b"ns.useplus.org", b"www.aiim.org", b"cipa.jp")


def _texts(data: bytes):
    yield data.decode("latin-1")
    for off in (0, 1):
        yield data[off:].decode("utf-16-le", errors="ignore")


def _field_has_link(text: str) -> bool:
    for m in _INSTR.finditer(text):
        instr = m.group(1)
        link = _LINK_FIELD.search(instr)
        if link and _URL.search(link.group(1)):
            return True
    return False


def _data_stream_has_url(path: pathlib.Path) -> bool:
    try:
        import olefile
        if not olefile.isOleFile(str(path)):
            return False
        with olefile.OleFileIO(str(path)) as ole:
            if not ole.exists("Data"):
                return False
            data = ole.openstream("Data").read()
    except Exception:  # noqa: BLE001 容器坏了：交给后面的解析去报损坏
        return False
    return data_bytes_have_url(data)


def data_bytes_have_url(data: bytes) -> bool:
    """Data 流里单字节存放的地址前缀；内嵌图片元数据里的命名空间网址不算。"""
    for m in _DATA_URL.finditer(data):
        host = m.group(1).lower()
        if not any(host == h or host.startswith(h) for h in _NAMESPACE_HOSTS):
            return True
    return False


def has_external_picture(path: pathlib.Path) -> bool:
    """.doc / .wps 里有没有外链图片（或其他链接类域）。"""
    data = pathlib.Path(path).read_bytes()
    if any(_field_has_link(t) for t in _texts(data)):
        return True
    return _data_stream_has_url(pathlib.Path(path))


# xlsx 里不算"联网取图"的外部关系：超链接（点了才打开）、外部工作簿引用（重算时实测不发请求）
_XLSX_HARMLESS = ("/hyperlink", "/externalLinkPath")


def xlsx_has_external_rels(path: pathlib.Path) -> bool:
    """xlsx 压缩包里有没有指向外部的图片或对象关系。确定性检查：读关系文件，不猜。"""
    try:
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.startswith("xl/") and "/_rels/" in n and n.endswith(".rels")]
            parser = etree.XMLParser(resolve_entities=False, no_network=True)
            for n in names:
                root = etree.fromstring(z.read(n), parser)
                for rel in root:
                    if not isinstance(rel.tag, str) or rel.get("TargetMode") != "External":
                        continue
                    if not rel.get("Type", "").endswith(_XLSX_HARMLESS):
                        return True
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError, OSError):
        return False  # 压缩包坏了：交给后面的解析去报损坏
    return False
