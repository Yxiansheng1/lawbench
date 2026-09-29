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
from PIL import Image, UnidentifiedImageError

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
    base = unique_base(out_dir, path.stem, len(segs), width, make_pdf)
    outputs, pieces = [], []
    for i, s in enumerate(segs, 1):
        piece = img.crop((0, s.top, img.width, s.bottom))
        p = out_dir / f"{base}_{i:0{width}d}.png"
        piece.save(p)
        outputs.append(p)
        pieces.append(piece)
    pdf = None
    if make_pdf:
        pdf = out_dir / f"{base}.pdf"
        pieces[0].save(pdf, "PDF", save_all=True, append_images=pieces[1:], resolution=150)
    return Result(path, outputs, segs, pdf)


def unique_base(out_dir: Path, stem: str, n: int, width: int, make_pdf: bool) -> str:
    """再次切分同一张图时不覆盖上次的结果：有同名文件就用"原名(2)"，与格式互转一致。"""
    def taken(b: str) -> bool:
        if make_pdf and (out_dir / f"{b}.pdf").exists():
            return True
        return any((out_dir / f"{b}_{i:0{width}d}.png").exists() for i in range(1, n + 1))
    base, k = stem, 2
    while taken(base):
        base, k = f"{stem}({k})", k + 1
    return base


def reason(e: BaseException) -> str:
    """给用户看的中文原因，不带英文类名和堆栈。"""
    if isinstance(e, Image.DecompressionBombError):
        return "图片过大，无法处理"
    if isinstance(e, (FileNotFoundError, IsADirectoryError, NotADirectoryError)):
        return "文件不存在或不是图片文件"
    if isinstance(e, PermissionError):
        return "没有读取或写入权限（文件可能被占用，或结果文件夹不可写）"
    if isinstance(e, (UnidentifiedImageError, OSError)):
        return "不是图片，或图片已损坏"
    if isinstance(e, ValueError):
        return "段高设置不对（不能小于 200 像素）"
    return "处理失败（程序内部错误），其余文件不受影响"


def split_many(paths: list[Path], h_target: int = DEFAULT_H, make_pdf: bool = False,
               progress=None) -> list[tuple[Path, Result | str]]:
    """批量；单个文件出错（含意外错误）不影响其他文件，出错的返回中文原因。"""
    out = []
    for i, p in enumerate(paths, 1):
        try:
            r: Result | str = split_image(Path(p), h_target, make_pdf)
        except Exception as e:  # noqa: BLE001
            r = f"无法处理：{reason(e)}"
        out.append((Path(p), r))
        if progress:
            progress(i, len(paths))
    return out
