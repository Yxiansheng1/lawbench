"""去水印（Spec 6.7）：用 criminal-01 讯问笔录的扫描页（浅灰斜向水印、红章、蓝色手写批注）。"""
from __future__ import annotations

import base64
import io

import numpy as np
from PIL import Image

from conftest import auth, scan_pages, to_bytes
from prep395.dewatermark import deskew, dewatermark, watermark_mask


def red_count(img: Image.Image) -> int:
    a = np.asarray(img.convert("RGB")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return int(((r > 150) & (g < 110) & (b < 110)).sum())


def blue_count(img: Image.Image) -> int:
    a = np.asarray(img.convert("RGB")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return int(((b > 120) & (r < 90) & (g < 120)).sum())


def gray_var(img: Image.Image, box) -> float:
    return float(np.asarray(img.convert("L").crop(box), dtype=np.float64).var())


# 第 3 页下半部左侧：只有水印和纸，没有正文，也避开右下角的印章
WM_BOX = (40, 1050, 620, 1700)


def test_seal_red_pixels_unchanged_and_watermark_variance_drops():
    page3 = scan_pages()[2]
    before_red = red_count(page3)
    assert before_red > 2000                        # 样本里确有红章
    out, n = dewatermark(page3)
    assert n > 0
    assert red_count(out) == before_red
    assert np.array_equal(np.asarray(out)[red_mask(page3)], np.asarray(page3)[red_mask(page3)])
    v0, v1 = gray_var(page3, WM_BOX), gray_var(out, WM_BOX)
    assert v1 < v0 * 0.3, (v0, v1)


def red_mask(img):
    a = np.asarray(img.convert("RGB")).astype(int)
    return (a[..., 0] > 150) & (a[..., 1] < 110) & (a[..., 2] < 110)


def test_blue_annotation_unchanged():
    page2 = scan_pages()[1]
    before = blue_count(page2)
    assert before > 500                             # 样本里确有蓝色批注
    out, _ = dewatermark(page2)
    assert blue_count(out) == before


def test_dark_text_untouched():
    page1 = scan_pages()[0]
    a = np.asarray(page1.convert("RGB"))
    dark = a.max(axis=2) < 110
    out, _ = dewatermark(page1)
    assert np.array_equal(np.asarray(out)[dark], a[dark])


def test_clean_page_left_alone():
    img = Image.new("RGB", (800, 1000), (246, 244, 238))
    out, n = dewatermark(img)
    assert n == 0 and np.array_equal(np.asarray(out), np.asarray(img))
    assert not watermark_mask(img).any()


def test_deskew_small_angle_not_rotated_and_tilt_corrected():
    page1 = scan_pages()[0]
    same, ang = deskew(page1)
    assert abs(ang) < 1.0                           # 样本本身只有 ±0.6° 的轻微倾斜
    tilted = page1.rotate(2.0, resample=Image.BICUBIC, fillcolor=(246, 244, 238))
    _, ang2 = deskew(tilted)
    assert abs(ang2 + 2.0) <= 0.8, ang2


def test_api_dewatermark_off_by_default(client):
    """不带 dewatermark 参数时，返回的工作副本里水印还在；带 dewatermark=true 时去掉。"""
    page3 = scan_pages()[2]
    raw = to_bytes(page3)
    hdr = {**auth(), "Content-Type": "image/png"}
    r0 = client.post("/v1/ocr/page?return_image=true&deskew=false", content=raw, headers=hdr)
    r1 = client.post("/v1/ocr/page?return_image=true&deskew=false&dewatermark=true", content=raw, headers=hdr)
    im0 = Image.open(io.BytesIO(base64.b64decode(r0.json()["image_png_base64"])))
    im1 = Image.open(io.BytesIO(base64.b64decode(r1.json()["image_png_base64"])))
    assert np.array_equal(np.asarray(im0.convert("RGB")), np.asarray(page3))
    assert gray_var(im1, WM_BOX) < gray_var(im0, WM_BOX) * 0.3
    assert red_count(im1) == red_count(page3)
