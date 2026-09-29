"""长截图切分（Spec 13.1，PRD F-TOOL-01）：有空白就只切空白，优先切在消息之间；切不开时重叠切分并提示。

1. 灰度图逐行算与该行众数颜色的差值，差值 < 8 的像素占 98% 以上的行为"空白行"（兼容彩色背景）。
2. 目标段高 H（默认 2000）。在 [0.6H, H] 内找连续空白行（至少 6 行），取最长的一段，在中间切。
3. 找不到时在 H 处切，下一段向上重叠 120 像素，并标注"此处可能切到文字"。
4. 输出 原名_01.png …，放在原图旁的"切分结果"文件夹；可合并为 PDF；原图不动。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

DIFF = 8
BLANK_RATIO = 0.98
MIN_RUN = 6
OVERLAP = 120
DEFAULT_H = 2000
OUT_DIR_NAME = "切分结果"
WARN = "此处可能切到文字"


@dataclass
class Segment:
    top: int
    bottom: int          # 不含
    warn: bool = False   # 这一段的下边界是硬切（可能切到文字）


@dataclass
class Result:
    source: Path
    outputs: list[Path]
    segments: list[Segment]
    pdf: Path | None = None

    @property
    def notes(self) -> list[str]:
        return [f"{p.name}：{WARN}" for p, s in zip(self.outputs, self.segments) if s.warn]


def blank_rows(gray: np.ndarray) -> np.ndarray:
    """每行是否为空白行。gray 为 uint8 二维数组。"""
    h, w = gray.shape
    out = np.zeros(h, dtype=bool)
    for y in range(h):
        row = gray[y]
        mode = int(np.bincount(row, minlength=256).argmax())
        close = np.abs(row.astype(np.int16) - mode) < DIFF
        out[y] = close.mean() >= BLANK_RATIO
    return out


def _runs(mask: np.ndarray, lo: int, hi: int) -> list[tuple[int, int]]:
    """[lo, hi) 内连续为真的区间 (start, end)，end 不含。"""
    runs, start = [], None
    for y in range(lo, hi):
        if mask[y] and start is None:
            start = y
        elif not mask[y] and start is not None:
            runs.append((start, y))
            start = None
    if start is not None:
        runs.append((start, hi))
    return runs


def plan(blank: np.ndarray, h_target: int = DEFAULT_H) -> list[Segment]:
    height = len(blank)
    if h_target < 200:
        raise ValueError("段高不能小于 200 像素")
    segs: list[Segment] = []
    pos = 0
    while height - pos > h_target:
        lo, hi = pos + int(0.6 * h_target), pos + h_target
        runs = [r for r in _runs(blank, lo, hi) if r[1] - r[0] >= MIN_RUN]
        if runs:
            s, e = max(runs, key=lambda r: (r[1] - r[0], r[0]))    # 最长；一样长取靠近 H 的，段数少
            cut = (s + e) // 2
            segs.append(Segment(pos, cut))
            pos = cut
        else:
            segs.append(Segment(pos, hi, warn=True))
            pos = hi - OVERLAP
    segs.append(Segment(pos, height))
    return segs


def split_image(path: Path, h_target: int = DEFAULT_H, make_pdf: bool = False) -> Result:
    path = Path(path)
    with Image.open(path) as im:
        im.load()
        img = im.convert("RGB")
    gray = np.asarray(img.convert("L"))
    segs = plan(blank_rows(gray), h_target)
    out_dir = path.parent / OUT_DIR_NAME
    out_dir.mkdir(exist_ok=True)
    width = len(str(len(segs))) if len(segs) >= 100 else 2
    outputs, pieces = [], []
    for i, s in enumerate(segs, 1):
        piece = img.crop((0, s.top, img.width, s.bottom))
        p = out_dir / f"{path.stem}_{i:0{width}d}.png"
        piece.save(p)
        outputs.append(p)
        pieces.append(piece)
    pdf = None
    if make_pdf:
        pdf = out_dir / f"{path.stem}.pdf"
        pieces[0].save(pdf, "PDF", save_all=True, append_images=pieces[1:], resolution=150)
    return Result(path, outputs, segs, pdf)


def split_many(paths: list[Path], h_target: int = DEFAULT_H, make_pdf: bool = False,
               progress=None) -> list[tuple[Path, Result | str]]:
    """批量；单个文件出错不影响其他文件，出错的返回中文原因。"""
    out = []
    for i, p in enumerate(paths, 1):
        try:
            r: Result | str = split_image(Path(p), h_target, make_pdf)
        except (OSError, ValueError) as e:
            r = f"无法处理：{type(e).__name__}"
        out.append((Path(p), r))
        if progress:
            progress(i, len(paths))
    return out
