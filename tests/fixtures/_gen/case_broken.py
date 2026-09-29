"""broken：无法处理的文件——加密 PDF、加密 docx、截断损坏的 PDF（虚构）。

加密文件的密码见 common.TEST_PASSWORD（虚构测试值），verify.py 用它解密后核对特征字符串。
"""
from __future__ import annotations

import io
from pathlib import Path

from msoffcrypto.format.ooxml import OOXMLFile
from docx import Document
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

import common as C

CASE = "broken"
FEAT = C.FEATURE[CASE]

FILES = ["加密.pdf", "加密.docx", "截断.pdf"]

TEXT = f"本文件为加密测试样本，内容虚构。样本编号：{FEAT}"


def _plain_pdf(pages: int) -> bytes:
    """不压缩的 PDF，特征字符串以 Helvetica 明文出现在第 1 页内容流中（截断后仍可在字节里找到）。"""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, pageCompression=0)
    c.setKeywords(FEAT)
    for i in range(pages):
        c.setFont("Helvetica", 12)
        c.drawString(72, 760, f"{FEAT} page {i + 1}")
        c.setFont(C.pdf_font(), 12)
        c.drawString(72, 730, f"截断样本第{i + 1}页，内容虚构。")
        for k in range(30):
            c.drawString(72, 700 - k * 20, "填充行 " + "测试" * 10)
        c.showPage()
    c.save()
    return buf.getvalue()


def build(root: Path) -> None:
    d = root / CASE
    d.mkdir(parents=True, exist_ok=True)

    tmp = io.BytesIO()
    src = io.BytesIO()
    c = canvas.Canvas(src, pagesize=A4)
    c.setFont(C.pdf_font(), 12)
    c.drawString(72, 760, TEXT)
    c.showPage()
    c.save()
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(src.getvalue())))
    w.encrypt(user_password=C.TEST_PASSWORD, owner_password=C.TEST_PASSWORD, algorithm="AES-256")
    with open(d / "加密.pdf", "wb") as f:
        w.write(f)

    doc = Document()
    C.set_east_asian_font(doc)
    C.fix_core(doc, "加密样本", FEAT)
    doc.add_paragraph(TEXT)
    doc.save(tmp)
    tmp.seek(0)
    enc = io.BytesIO()
    OOXMLFile(tmp).encrypt(C.TEST_PASSWORD, enc)
    (d / "加密.docx").write_bytes(enc.getvalue())

    full = _plain_pdf(3)
    (d / "截断.pdf").write_bytes(full[: int(len(full) * 0.6)])
