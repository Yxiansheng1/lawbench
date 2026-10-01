"""生成导出用的两个占位模板（T15；Spec 12.1）：service/lawbench/export/templates/文书.docx、合同.docx。

律所的正式模板到位前用：取 pandoc 自带的 reference.docx，只改默认中文字体和字号——
文书：仿宋，小四（12 磅）；合同：宋体，小四。律所模板到位后在设置里指定，不用改程序。

用法：python scripts\\make_export_templates.py [pandoc.exe 路径]
"""
from __future__ import annotations

import io
import pathlib
import subprocess
import sys
import zipfile

from lxml import etree

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))
from lawbench.export.pandoc import TEMPLATE_DIR, find_pandoc  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
FONTS = {"文书": "仿宋", "合同": "宋体"}
SIZE = "24"  # 半磅：小四


def q(t: str) -> str:
    return f"{{{W}}}{t}"


def make(base: bytes, font: str) -> bytes:
    zin = zipfile.ZipFile(io.BytesIO(base))
    styles = etree.fromstring(zin.read("word/styles.xml"))
    rpr = styles.find(f"{q('docDefaults')}/{q('rPrDefault')}/{q('rPr')}")
    fonts = rpr.find(q("rFonts"))
    if fonts is None:
        fonts = etree.SubElement(rpr, q("rFonts"))
    for k in list(fonts.attrib):
        if k.endswith("Theme"):
            del fonts.attrib[k]
    fonts.set(q("eastAsia"), font)
    for tag in ("sz", "szCs"):
        el = rpr.find(q(tag))
        if el is None:
            el = etree.SubElement(rpr, q(tag))
        el.set(q("val"), SIZE)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "word/styles.xml":
                data = etree.tostring(styles, xml_declaration=True, encoding="UTF-8", standalone=True)
            zi = zipfile.ZipInfo(info.filename, date_time=(2026, 10, 1, 0, 0, 0))  # 固定时间：重跑结果逐字节相同
            zi.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(zi, data)
    return buf.getvalue()


def main() -> None:
    exe = sys.argv[1] if len(sys.argv) > 1 else find_pandoc()
    base = subprocess.run([exe, "--print-default-data-file", "reference.docx"], check=True,
                          capture_output=True).stdout
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    for name, font in FONTS.items():
        (TEMPLATE_DIR / f"{name}.docx").write_bytes(make(base, font))
        print(TEMPLATE_DIR / f"{name}.docx")


if __name__ == "__main__":
    main()
