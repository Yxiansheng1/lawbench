"""docx 的 Word 兼容版本（T14 联调派修，2026-10-03）。

Word 按 word/settings.xml 里 <w:compat><w:compatSetting w:name="compatibilityMode" w:val="…"/> 决定是否进"兼容性模式"：
没有这一项按 12（Word 2007）处理，python-docx 默认底板写的是 14（Word 2010），都会在标题栏显示"兼容性模式"；
15 是 Word 2013 起的当前模式。我们自己生成的 docx 一律设 15：
- 导出：pandoc 原样沿用参考模板（templates\\文书.docx、合同.docx）的 settings.xml（实测），所以在生成模板时设
  （scripts\\make_export_templates.py）；
- 归档：没有律所模板时 python-docx 用默认底板，生成后设（archive\\documents.py）。
律所自己的模板若本身是旧模式，按交付说明的做法在 Word 里"转换"后另存副本，不在程序里改它。
"""
from __future__ import annotations

import io
import zipfile

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
URI = "http://schemas.microsoft.com/office/word"
MODE = "15"
# CT_Settings 里排在 w:compat 之后的元素（ECMA-376 第 1 部分 17.15.1.78 的顺序）：w:compat 插在第一个出现的这些元素前面
_AFTER_COMPAT = {f"{{{W}}}{t}" for t in (
    "docVars", "rsids", "attachedSchema", "themeFontLang", "clrSchemeMapping", "doNotIncludeSubdocsInStats",
    "doNotAutoCompressPictures", "forceUpgrade", "captions", "readModeInkLockDown", "smartTagType",
    "shapeDefaults", "doNotEmbedSmartTags", "decimalSymbol", "listSeparator")} | {
    "{http://schemas.openxmlformats.org/officeDocument/2006/math}mathPr",
    "{http://schemas.openxmlformats.org/schemaLibrary/2006/main}schemaLibrary"}


def _q(t: str) -> str:
    return f"{{{W}}}{t}"


def set_compat15(settings: etree._Element) -> None:
    """把 settings 根元素里的 compatibilityMode 设成 15；已有的其他 compat 项保留；没有 w:compat 就按规定位置插一个。"""
    compat = settings.find(_q("compat"))
    if compat is None:
        compat = etree.Element(_q("compat"))
        nxt = next((el for el in settings if el.tag in _AFTER_COMPAT), None)
        if nxt is None:
            settings.append(compat)
        else:
            nxt.addprevious(compat)
    for el in compat.findall(_q("compatSetting")):
        if el.get(_q("name")) == "compatibilityMode":
            compat.remove(el)
    el = etree.SubElement(compat, _q("compatSetting"))
    el.set(_q("name"), "compatibilityMode")
    el.set(_q("uri"), URI)
    el.set(_q("val"), MODE)


def compat_mode(data: bytes) -> int | None:
    """docx 字节里的 compatibilityMode；没写返回 None（Word 按 12 处理）。"""
    root = etree.fromstring(zipfile.ZipFile(io.BytesIO(data)).read("word/settings.xml"))
    for el in root.iter(_q("compatSetting")):
        if el.get(_q("name")) == "compatibilityMode":
            return int(el.get(_q("val")))
    return None
