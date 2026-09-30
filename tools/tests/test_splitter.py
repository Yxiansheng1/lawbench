"""长截图切分（Spec 13.1）：前两张样本只切在空白行上；第三张重叠切分并标注；原图不动。"""
from __future__ import annotations

import shutil

import numpy as np
import pytest
from PIL import Image

from conftest import SAMPLES, sha256
from splitter import core

CLEAN = ["聊天-纯色背景.png", "聊天-彩色背景.png"]
NO_BLANK = "聊天-无空白.png"


def copy_sample(name, tmp_path):
    p = tmp_path / name
    shutil.copyfile(SAMPLES / name, p)
    return p


@pytest.mark.parametrize("name", CLEAN)
def test_cuts_only_on_blank_rows(name, tmp_path):
    src = copy_sample(name, tmp_path)
    before = sha256(src)
    r = core.split_image(src)
    img = Image.open(SAMPLES / name).convert("RGB")
    gray = np.asarray(img.convert("L"))
    blank = core.blank_rows(gray)
    assert len(r.segments) >= 3
    for s in r.segments[:-1]:
        assert not s.warn
        cut = s.bottom
        assert blank[cut] and blank[cut - 1], f"{name} 切在第 {cut} 行，不是空白行"
        # 切分行的像素本身：与该行众数差值 < 8 的占 98% 以上
        row = gray[cut].astype(int)
        mode = np.bincount(gray[cut]).argmax()
        assert (np.abs(row - mode) < 8).mean() >= 0.98
    # 不重叠、不遗漏；每段不超过段高
    assert r.segments[0].top == 0 and r.segments[-1].bottom == img.height
    for a, b in zip(r.segments, r.segments[1:]):
        assert a.bottom == b.top
    assert all(s.bottom - s.top <= core.DEFAULT_H for s in r.segments)
    # 输出命名与位置；原图不动
    assert [p.name for p in r.outputs] == [f"{src.stem}_{i:02d}.png" for i in range(1, len(r.outputs) + 1)]
    assert all(p.parent == src.parent / "切分结果" for p in r.outputs)
    assert sum(Image.open(p).height for p in r.outputs) == img.height
    assert sha256(src) == before
    assert r.notes == []


def test_no_blank_overlaps_and_warns(tmp_path):
    src = copy_sample(NO_BLANK, tmp_path)
    before = sha256(src)
    r = core.split_image(src)
    assert not core.blank_rows(np.asarray(Image.open(src).convert("L"))).any()
    warned = [s for s in r.segments if s.warn]
    assert len(warned) >= 1
    for a, b in zip(r.segments, r.segments[1:]):
        if a.warn:
            assert a.bottom - a.top == core.DEFAULT_H
            assert b.top == a.bottom - core.OVERLAP          # 下一段向上重叠 120 像素
    assert r.notes and all(core.WARN in n for n in r.notes)
    assert sha256(src) == before


def test_merge_pdf(tmp_path):
    import pypdfium2 as pdfium
    src = copy_sample(CLEAN[0], tmp_path)
    r = core.split_image(src, make_pdf=True)
    assert r.pdf and r.pdf.name == f"{src.stem}.pdf"
    assert len(pdfium.PdfDocument(str(r.pdf))) == len(r.outputs)


def test_custom_height_and_batch(tmp_path):
    a = copy_sample(CLEAN[0], tmp_path)
    b = copy_sample(CLEAN[1], tmp_path)
    bad = tmp_path / "坏文件.png"
    bad.write_bytes(b"not a png")
    res = core.split_many([a, b, bad], h_target=1000)
    assert isinstance(res[0][1], core.Result) and isinstance(res[1][1], core.Result)
    assert all(s.bottom - s.top <= 1000 for s in res[0][1].segments)
    assert isinstance(res[2][1], str) and res[2][1].startswith("无法处理")


def test_plan_picks_longest_run_in_window():
    blank = np.zeros(5000, dtype=bool)
    blank[1300:1310] = True        # 10 行
    blank[1500:1530] = True        # 30 行：最长
    blank[2100:2200] = True        # 在窗口 [1200, 2000] 外
    blank[1900:1904] = True        # 不足 6 行
    segs = core.plan(blank, 2000)
    assert segs[0].bottom == 1515 and not segs[0].warn


def test_plan_ignores_short_runs():
    blank = np.zeros(3000, dtype=bool)
    blank[1500:1505] = True        # 只有 5 行
    segs = core.plan(blank, 2000)
    assert segs[0].warn and segs[0].bottom == 2000 and segs[1].top == 1880


def test_rerun_does_not_overwrite(tmp_path):
    src = copy_sample(CLEAN[0], tmp_path)
    r1 = core.split_image(src, make_pdf=True)
    first = {p: p.read_bytes() for p in r1.outputs}
    r2 = core.split_image(src, make_pdf=True)
    assert all(p.name.startswith(f"{src.stem}(2)_") for p in r2.outputs)
    assert r2.pdf.name == f"{src.stem}(2).pdf"
    assert all(p.read_bytes() == b for p, b in first.items())     # 上次的结果没被覆盖


def test_batch_errors_are_chinese_and_isolated(tmp_path, monkeypatch):
    from PIL import Image
    good = copy_sample(CLEAN[0], tmp_path)
    folder = tmp_path / "一个文件夹.png"
    folder.mkdir()
    big = tmp_path / "超大图.png"
    Image.new("RGB", (3000, 3000)).save(big)
    bad = tmp_path / "坏文件.png"
    bad.write_bytes(b"not a png")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 2_000_000)
    res = core.split_many([folder, big, bad, good])
    assert isinstance(res[3][1], core.Result)
    for _, r in res[:3]:
        assert isinstance(r, str) and r.startswith("无法处理：")
        assert not any(w in r for w in ("Error", "OSError", "Exception"))
    assert "过大" in res[1][1]


def test_gui_builds():
    import tkinter as tk
    from splitter.app import SplitterApp
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("没有图形界面环境")
    root.withdraw()
    app = SplitterApp(root)
    assert app.height.get() == core.DEFAULT_H
    root.destroy()
