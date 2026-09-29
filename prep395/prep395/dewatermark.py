"""图片预处理（Spec 6.2、6.7）：纠偏与保守去水印，全部在内存中用 Pillow / numpy 完成。

去水印只动"浅灰、低饱和、大面积"的像素，把它们换成纸张底色；深色文字、红色（印章、签名）、
蓝色（批注笔迹）一律不动。只处理本次请求的图片副本。
"""
from __future__ import annotations

import numpy as np
from PIL import Image

# 浅灰判定：各通道最大值与最小值之差（饱和度的近似）不超过 SAT_MAX，亮度落在 [GRAY_LO, GRAY_HI]
SAT_MAX = 25
GRAY_LO = 150
GRAY_HI = 235
# 候选像素占全图的比例低于此值时视为没有大面积水印，不处理
MIN_AREA = 0.01


def _protected(a: np.ndarray) -> np.ndarray:
    r, g, b = (a[..., i].astype(np.int16) for i in range(3))
    red = (r > 110) & (r - np.maximum(g, b) > 40)
    blue = (b > 90) & (b - np.maximum(r, g) > 30)
    return red | blue


def watermark_mask(img: Image.Image) -> np.ndarray:
    a = np.asarray(img.convert("RGB"))
    mx = a.max(axis=2).astype(np.int16)
    mn = a.min(axis=2).astype(np.int16)
    cand = (mx - mn <= SAT_MAX) & (mx >= GRAY_LO) & (mx <= GRAY_HI)
    return cand & ~_protected(a)


def dewatermark(img: Image.Image) -> tuple[Image.Image, int]:
    """返回 (处理后的副本, 被替换的像素数)；没有大面积浅灰时原样返回副本和 0。"""
    a = np.array(img.convert("RGB"))
    mask = watermark_mask(img)
    n = int(mask.sum())
    if n < MIN_AREA * mask.size:
        return Image.fromarray(a), 0
    mx = a.max(axis=2)
    paper = (mx > GRAY_HI) & (mx.astype(np.int16) - a.min(axis=2) <= SAT_MAX)
    bg = np.median(a[paper], axis=0).astype(np.uint8) if paper.any() else np.array([255, 255, 255], np.uint8)
    a[mask] = bg
    return Image.fromarray(a), n


def deskew(img: Image.Image, max_deg: float = 3.0, step: float = 0.25) -> tuple[Image.Image, float]:
    """按水平投影的方差找倾斜角（±3°内），角度小于 0.3° 不旋转。返回 (图, 旋转角度)。"""
    g = img.convert("L")
    small = g.resize((max(1, g.width // 4), max(1, g.height // 4)))
    dark = (np.asarray(small) < 128).astype(np.uint8) * 255
    probe = Image.fromarray(dark)
    best, best_score = 0.0, -1.0
    for k in range(int(-max_deg / step), int(max_deg / step) + 1):
        ang = k * step
        rows = np.asarray(probe.rotate(ang, resample=Image.NEAREST, fillcolor=0)).sum(axis=1, dtype=np.float64)
        score = float(rows.var())
        if score > best_score:
            best, best_score = ang, score
    if abs(best) < 0.3:
        return img, 0.0
    fill = (255, 255, 255) if img.mode == "RGB" else 255
    return img.rotate(best, resample=Image.BICUBIC, fillcolor=fill), best
