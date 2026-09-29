"""去水印（Spec 6.7）：用 criminal-01 讯问笔录的扫描页（浅灰斜向水印、红章、蓝色手写批注）。"""
from __future__ import annotations

import base64
import io

import numpy as np
import pytest
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


# 以下直接调用 dewatermark() 的用例测的是本版未启用、留档备查的算法（服务不调用它），保留以免算法无人看管。


def tint_mask(img, channel: int) -> np.ndarray:
    """带红（channel=0）或蓝（channel=2）色调的像素，含浅色边缘：该通道比另两个通道高出 8 以上。"""
    a = np.asarray(img.convert("RGB")).astype(int)
    others = [a[..., i] for i in range(3) if i != channel]
    return a[..., channel] - np.maximum(*others) > 8


def test_seal_red_pixels_unchanged_and_watermark_variance_drops():
    page3 = scan_pages()[2]
    assert red_count(page3) > 2000                  # 样本里确有红章
    out, n = dewatermark(page3)
    assert n > 0
    m = tint_mask(page3, 0)                         # 逐像素：所有带红色调的像素（含浅色边缘）一个不变
    assert m.sum() > red_count(page3)
    assert np.array_equal(np.asarray(out)[m], np.asarray(page3)[m])
    v0, v1 = gray_var(page3, WM_BOX), gray_var(out, WM_BOX)
    assert v1 < v0 * 0.3, (v0, v1)


def test_blue_annotation_unchanged():
    page2 = scan_pages()[1]
    assert blue_count(page2) > 500                  # 样本里确有蓝色批注
    out, n = dewatermark(page2)
    assert n > 0
    m = tint_mask(page2, 2)
    assert np.array_equal(np.asarray(out)[m], np.asarray(page2)[m])


def test_light_gray_horizontal_text_untouched():
    """一页浅灰色（灰度约 170）的横排正文不是水印，去水印后逐像素不变。"""
    from PIL import ImageDraw, ImageFont
    import os
    img = Image.new("RGB", (1240, 1754), (246, 244, 238))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "simsun.ttc"), 30)
    for y in range(140, 1600, 52):
        d.text((120, y), "浅灰色正文测试文字，横排排列，每一行内容都是虚构的。", font=f, fill=(170, 170, 170))
    out, n = dewatermark(img)
    assert n == 0 and np.array_equal(np.asarray(out), np.asarray(img))


def test_scan_without_watermark_untouched():
    """同样的扫描噪点、没有水印的页：候选像素不成斜向重复图案，原样返回。"""
    import sys
    from conftest import FIXTURES
    sys.path.insert(0, str(FIXTURES / "_gen"))
    import common as G
    import case_criminal01 as K
    img = G.render_page(K.XUNWEN[0], seed=100)
    out, n = dewatermark(img)
    assert n == 0 and np.array_equal(np.asarray(out), np.asarray(img))


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


def _roundtrip(client, img, query="return_image=true&deskew=false&dewatermark=true"):
    hdr = {**auth(), "Content-Type": "image/png"}
    r = client.post(f"/v1/ocr/page?{query}", content=to_bytes(img), headers=hdr)
    assert r.status_code == 200, r.text                      # 契约不变：dewatermark=true 照常接受
    return Image.open(io.BytesIO(base64.b64decode(r.json()["image_png_base64"]))).convert("RGB")


def test_dewatermark_disabled_in_this_version():
    from prep395.dewatermark import DEWATERMARK_ENABLED
    assert DEWATERMARK_ENABLED is False


@pytest.mark.parametrize("idx", [1, 2], ids=["蓝色批注页", "红章页"])
def test_api_dewatermark_true_returns_original(client, idx):
    """本版去水印未启用：带水印的页 dewatermark=true 时，返回的工作副本与原图逐像素相同，红章、蓝色批注不变。"""
    page = scan_pages()[idx]
    out = _roundtrip(client, page)
    assert np.array_equal(np.asarray(out), np.asarray(page))
    assert red_count(out) == red_count(page) and blue_count(out) == blue_count(page)
    same = _roundtrip(client, page, "return_image=true&deskew=false")
    assert np.array_equal(np.asarray(out), np.asarray(same))  # 与不勾选时相同


def _page_with(lines, base, fill, kind="song", size=30, x=120, y0=140, step=52):
    import sys
    from PIL import ImageDraw
    from conftest import FIXTURES
    sys.path.insert(0, str(FIXTURES / "_gen"))
    import common as G
    img = base.copy()
    d = ImageDraw.Draw(img)
    f = G.pil_font(size, kind)
    for k, t in enumerate(lines):
        d.text((x, y0 + step * k), t, font=f, fill=fill)
    return img


def _gen():
    import sys
    from conftest import FIXTURES
    sys.path.insert(0, str(FIXTURES / "_gen"))
    import common as G
    import case_criminal01 as K
    return G, K


def test_gray_text_page_with_watermark_left_alone():
    """浅灰（约 170）横排正文页叠加水印：非水印的浅灰像素逐像素不变（整页原样返回）。"""
    G, _ = _gen()
    base = Image.new("RGB", G.PAGE_PX, (246, 244, 238))
    text = _page_with(["浅灰色正文测试文字，横排排列，每一行内容都是虚构的。"] * 29, base, (170, 170, 170))
    img = G.add_watermark(text, "仅供办案使用")
    gray_text = np.asarray(text).max(axis=2) < 200           # 正文笔画所在像素
    out, n = dewatermark(img)
    assert np.array_equal(np.asarray(out)[gray_text], np.asarray(img)[gray_text])
    assert n == 0


def test_scan_with_watermark_and_pencil_notes_left_alone(client):
    """扫描页叠加水印再加几行灰度约 160 的手写：经接口 dewatermark=true 后逐像素原样返回（本版去水印未启用）。"""
    G, K = _gen()
    base = G.add_watermark(G.render_page(K.XUNWEN[0], seed=100), "仅供办案使用")
    notes = _page_with(["铅笔批注：此处需核对转账时间", "与银行流水第三页对照", "询问笔录前后不一致"],
                       Image.new("RGB", G.PAGE_PX, (255, 255, 255)), (160, 160, 160), "kai", 40, 150, 1250, 70)
    hand = np.asarray(notes).max(axis=2) < 200
    img = Image.fromarray(np.where(hand[..., None], np.asarray(notes), np.asarray(base)).astype(np.uint8))
    out = _roundtrip(client, img)
    assert np.array_equal(np.asarray(out), np.asarray(img))
