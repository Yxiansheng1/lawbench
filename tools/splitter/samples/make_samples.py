"""生成 3 张虚构聊天长截图（测试样本）：纯色背景、彩色渐变背景、无空白区（斜纹底）。

python tools\\splitter\\samples\\make_samples.py   # 覆盖写同目录下的 3 张 PNG
对话内容全部虚构。
"""
from __future__ import annotations

import os
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
W = 750
FONT = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "simhei.ttf"

LINES = [
    "你好，借款的事情想跟你确认一下",
    "3月10日转给你的8万元收到了吧",
    "收到了，下个月开始付利息",
    "好的，按借条约定年利率百分之十二",
    "明白，到期一次还本",
    "六月份先还你两万",
    "这个月利息什么时候付？",
    "最近资金有点紧，月底前一定付",
    "已经拖了两个月了，请尽快",
    "知道了，再宽限几天",
    "借条上写的是九月十日前还清",
    "我记得，会想办法的",
]


def _font(size=28):
    return ImageFont.truetype(str(FONT), size)


def _messages(seed: int, n: int):
    rnd = random.Random(seed)
    for i in range(n):
        text = LINES[i % len(LINES)]
        lines = rnd.randint(1, 4)
        yield i % 2 == 0, [text] * lines


def _draw_chat(img: Image.Image, seed: int, n: int, gap: int, colors) -> int:
    d = ImageDraw.Draw(img)
    f = _font()
    y = 120
    left_c, right_c, avatar_c = colors
    for mine, lines in _messages(seed, n):
        bh = 24 + 42 * len(lines)
        tw = max(d.textlength(t, font=f) for t in lines) + 40
        if mine:
            d.rectangle((W - 96, y, W - 24, y + 72), fill=avatar_c)
            x1 = W - 110
            d.rounded_rectangle((x1 - tw, y, x1, y + bh), 10, fill=right_c)
            tx = x1 - tw + 20
        else:
            d.rectangle((24, y, 96, y + 72), fill=(120, 150, 200))
            d.rounded_rectangle((110, y, 110 + tw, y + bh), 10, fill=left_c)
            tx = 130
        for k, t in enumerate(lines):
            d.text((tx, y + 16 + 42 * k), t, font=f, fill=(30, 30, 30))
        y += max(bh, 72) + gap
    return y


def plain() -> Image.Image:
    img = Image.new("RGB", (W, 5200), (237, 237, 237))
    ImageDraw.Draw(img).rectangle((0, 0, W, 88), fill=(220, 220, 220))
    _draw_chat(img, 1, 34, 40, ((255, 255, 255), (149, 236, 105), (90, 160, 90)))
    return img


def colored() -> Image.Image:
    h = 5200
    img = Image.new("RGB", (W, h))
    d = ImageDraw.Draw(img)
    for y in range(h):          # 自上而下由粉到蓝的渐变，每一行颜色一致
        t = y / h
        d.line((0, y, W, y), fill=(int(250 - 40 * t), int(225 + 5 * t), int(235 + 15 * t)))
    _draw_chat(img, 2, 34, 40, ((255, 255, 255), (170, 210, 255), (200, 120, 160)))
    return img


def no_blank() -> Image.Image:
    h = 4600
    img = Image.new("RGB", (W, h), (245, 245, 245))
    d = ImageDraw.Draw(img)
    for x in range(-h, W, 18):  # 满幅斜纹：任何一行都不是空白行
        d.line((x, 0, x + h, h), fill=(205, 205, 205), width=4)
    _draw_chat(img, 3, 30, 12, ((255, 255, 255), (149, 236, 105), (90, 160, 90)))
    return img


SAMPLES = {"聊天-纯色背景.png": plain, "聊天-彩色背景.png": colored, "聊天-无空白.png": no_blank}


def main() -> None:
    for name, fn in SAMPLES.items():
        fn().save(HERE / name, optimize=True)
        print("生成", name)


if __name__ == "__main__":
    main()
