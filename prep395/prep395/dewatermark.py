"""图片预处理（Spec 6.2、6.7）：纠偏与保守去水印，全部在内存中用 Pillow / numpy 完成。

去水印只在同时满足下面几条时动手，拿不准就原样返回：
- 候选像素是浅灰、低饱和的，并且占全图 ≥1%；
- 候选像素排成**重复的斜向**图案（沿某个斜向角度投影有多个等距的峰，而横排、竖排方向没有更强的规律），
  所以一页浅灰色的横排正文不会被当成水印；
- 带红色或蓝色色调的像素（印章、签名、批注笔迹，含它们浅色的边缘）以及它们周围 2 像素一律不动。
被判为水印的像素换成纸张底色。只处理本次请求的图片副本。
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

# 浅灰判定：各通道最大值与最小值之差（饱和度的近似）不超过 SAT_MAX，亮度落在 [GRAY_LO, GRAY_HI]
SAT_MAX = 25
GRAY_LO = 150
GRAY_HI = 235
MIN_AREA = 0.01            # 候选像素占全图的比例低于此值时不处理
TINT = 8                   # 红 / 蓝通道比另两个通道高出这么多即算"带色调"，不动
GUARD_PX = 2               # 带色调像素周围再保护几像素
DIAG_ANGLES = (-60, -45, -30, 30, 45, 60)
AXIS_ANGLES = (0, 90)
MIN_PEAKS = 3              # 投影上至少这么多个峰才算"重复"


def _protected(a: np.ndarray) -> np.ndarray:
    r, g, b = (a[..., i].astype(np.int16) for i in range(3))
    tinted = (r - np.maximum(g, b) > TINT) | (b - np.maximum(r, g) > TINT)
    if GUARD_PX:
        m = Image.fromarray(tinted.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(2 * GUARD_PX + 1))
        tinted = np.asarray(m) > 0
    return tinted


def watermark_mask(img: Image.Image) -> np.ndarray:
    a = np.asarray(img.convert("RGB"))
    mx = a.max(axis=2).astype(np.int16)
    mn = a.min(axis=2).astype(np.int16)
    cand = (mx - mn <= SAT_MAX) & (mx >= GRAY_LO) & (mx <= GRAY_HI)
    return cand & ~_protected(a)


def _profile(mask_img: Image.Image, angle: float) -> np.ndarray:
    rot = mask_img.rotate(angle, resample=Image.NEAREST, expand=True, fillcolor=0)
    return np.asarray(rot, dtype=np.float64).sum(axis=1)


def _strength(p: np.ndarray) -> float:
    return float(p.var() / (p.mean() ** 2 + 1e-9))


def _peaks(p: np.ndarray) -> int:
    """投影里明显高出平均的连续段个数。"""
    k = max(3, len(p) // 100)
    s = np.convolve(p, np.ones(k) / k, mode="same")
    nz = s[s > 0]
    if nz.size == 0:
        return 0
    hi = s > nz.mean() + 0.5 * nz.std()
    return int(np.count_nonzero(hi[1:] & ~hi[:-1]) + int(hi[0]))


def is_diagonal_repeat(mask: np.ndarray) -> bool:
    """候选像素是否呈现重复的斜向图案。"""
    small = Image.fromarray(mask.astype(np.uint8) * 255).resize(
        (max(1, mask.shape[1] // 4), max(1, mask.shape[0] // 4)), Image.BOX)
    small = small.point(lambda v: 255 if v >= 64 else 0)
    diag = {a: _profile(small, a) for a in DIAG_ANGLES}
    best = max(diag, key=lambda a: _strength(diag[a]))
    axis = max(_strength(_profile(small, a)) for a in AXIS_ANGLES)
    return _strength(diag[best]) > 1.3 * axis and _peaks(diag[best]) >= MIN_PEAKS


def dewatermark(img: Image.Image) -> tuple[Image.Image, int]:
    """返回 (处理后的副本, 被替换的像素数)；不像水印时原样返回副本和 0。"""
    a = np.array(img.convert("RGB"))
    mask = watermark_mask(img)
    n = int(mask.sum())
    if n < MIN_AREA * mask.size or not is_diagonal_repeat(mask):
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
