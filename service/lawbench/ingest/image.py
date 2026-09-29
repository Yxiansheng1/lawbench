"""图片（jpg / png / tif / bmp）：整份材料需要识别，一张图算一页（Spec 5.2）。"""
from __future__ import annotations

import pathlib

from PIL import Image

from . import Block, Parsed, ParseError
from .pdf import NEEDS_OCR


def parse(path: pathlib.Path) -> Parsed:
    try:
        with Image.open(path) as im:
            im.verify()
    except Exception:  # noqa: BLE001 Pillow 对坏图抛的异常种类很多
        raise ParseError("corrupt")
    return Parsed(unit="page", unit_count=1, count_word="页", blocks=[Block("第1页", NEEDS_OCR, ocr_pending=True)],
                  pages_need_ocr=[1])
