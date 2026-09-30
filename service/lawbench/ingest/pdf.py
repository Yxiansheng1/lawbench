"""PDF：pypdfium2 逐页取文字，按 Spec 5.4 判断每页类型。"""
from __future__ import annotations

import pathlib

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from . import MAX_PAGES, PDF_MIN_CHARS, PDF_MIXED_IMAGE_RATIO, Block, Parsed, ParseError

NEEDS_OCR = "（本页需识别）"


def _open(path: pathlib.Path) -> pdfium.PdfDocument:
    try:
        return pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as e:
        if getattr(e, "err_code", None) == pdfium_c.FPDF_ERR_PASSWORD or "password" in str(e).lower():
            raise ParseError("encrypted")
        raise ParseError("corrupt")


def _image_ratio(page: pdfium.PdfPage) -> float:
    w, h = page.get_size()
    area = w * h
    if area <= 0:
        return 0.0
    covered = 0.0
    for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=4):
        left, bottom, right, top = obj.get_bounds()
        cw = max(0.0, min(right, w) - max(left, 0.0))
        ch = max(0.0, min(top, h) - max(bottom, 0.0))
        covered += cw * ch
    return min(1.0, covered / area)


def page_kind(text: str, image_ratio: float) -> str:
    """text / needs_ocr / mixed（Spec 5.4）。"""
    chars = sum(1 for c in text if not c.isspace())
    if chars < PDF_MIN_CHARS:
        return "needs_ocr"
    if image_ratio > PDF_MIXED_IMAGE_RATIO:
        return "mixed"
    return "text"


def parse(path: pathlib.Path) -> Parsed:
    doc = _open(path)
    try:
        n = len(doc)
        if n > MAX_PAGES:
            raise ParseError("too_large")
        out = Parsed(unit="page", unit_count=n, count_word="页")
        for i in range(n):
            try:
                page = doc[i]
                tp = page.get_textpage()
                text = tp.get_text_range().replace("\r\n", "\n").replace("\r", "\n").strip()
                ratio = _image_ratio(page)
                tp.close()
                page.close()
            except pdfium.PdfiumError:
                raise ParseError("corrupt")
            kind = page_kind(text, ratio)
            if kind == "needs_ocr":
                out.pages_need_ocr.append(i + 1)
                out.blocks.append(Block(f"第{i + 1}页", NEEDS_OCR, ocr_pending=True))
                continue
            if kind == "mixed":
                out.pages_mixed.append(i + 1)
            out.blocks.append(Block(f"第{i + 1}页", text))
        return out
    finally:
        doc.close()
