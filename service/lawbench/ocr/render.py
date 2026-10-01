"""把材料的一页渲染成 PNG 字节，全程在内存里，不写临时文件（Spec 7.2 第 3 条、D8）。

- PDF：pypdfium2 以 200 DPI 渲染；长边超过 2480 像素时等比缩小（395 的单页上限，契约 prep395/ocr_page）。
- 图片：整张就是第 1 页；同样限制长边、按 EXIF 方向摆正、转 RGB 后编码 PNG。
"""
from __future__ import annotations

import io
import pathlib

DPI = 200
MAX_LONG_EDGE = 2480
IMAGE_TYPES = ("image",)
PDF_TYPES = ("pdf",)
from ..ingest import PDFIUM_LOCK as _PDFIUM   # pdfium 不是线程安全的：与解析共用同一把锁


class RenderError(Exception):
    """原件读不了或页号不存在。reason 只给日志用。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def page_count(path: pathlib.Path, kind: str) -> int:
    if kind in IMAGE_TYPES:
        return 1
    with _PDFIUM:
        return _pdf_pages(path)


def _pdf_pages(path: pathlib.Path) -> int:
    import pypdfium2 as pdfium
    try:
        doc = pdfium.PdfDocument(str(path))
    except Exception:  # noqa: BLE001 加密、损坏
        raise RenderError("open") from None
    try:
        return len(doc)
    finally:
        doc.close()


def render_png(path: pathlib.Path, kind: str, page_no: int) -> bytes:
    """返回第 page_no 页（从 1 起）的 PNG 字节。"""
    from PIL import Image, ImageOps
    if kind in IMAGE_TYPES:
        if page_no != 1:
            raise RenderError("page")
        try:
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im)
                img = im.convert("RGB")
        except Exception:  # noqa: BLE001 不是图片、损坏
            raise RenderError("image") from None
    elif kind in PDF_TYPES:
        with _PDFIUM:
            img = _pdf_page_image(path, page_no)
    else:
        raise RenderError("type")
    img = _fit(img)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=False)
    return buf.getvalue()


def _pdf_page_image(path: pathlib.Path, page_no: int):
    import pypdfium2 as pdfium
    try:
        doc = pdfium.PdfDocument(str(path))
    except Exception:  # noqa: BLE001
        raise RenderError("open") from None
    try:
        if not 1 <= page_no <= len(doc):
            raise RenderError("page")
        page = doc[page_no - 1]
        try:
            return page.render(scale=DPI / 72).to_pil().convert("RGB")
        finally:
            page.close()
    finally:
        doc.close()


def _fit(img):
    w, h = img.size
    long_edge = max(w, h)
    if long_edge <= MAX_LONG_EDGE:
        return img
    scale = MAX_LONG_EDGE / long_edge
    from PIL import Image
    return img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
