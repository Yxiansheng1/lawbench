import sys, numpy as np
sys.path.insert(0, ".")
sys.path.insert(0, "tests"); sys.path.insert(0, "../tests/fixtures/_gen")
from PIL import Image, ImageDraw
import common as G, case_criminal01 as K
from conftest import scan_pages
from prep395 import dewatermark as D

def gray_text_page(wm):
    im = Image.new("RGB", G.PAGE_PX, (246, 244, 238)); d = ImageDraw.Draw(im); f = G.pil_font(30)
    for y in range(140, 1600, 52):
        d.text((120, y), "浅灰色正文测试文字，横排排列，每一行内容都是虚构的。", font=f, fill=(170, 170, 170))
    return G.add_watermark(im, "仅供办案使用") if wm else im

def hand_page():
    im = G.add_watermark(G.render_page(K.XUNWEN[0], seed=100), "仅供办案使用"); d = ImageDraw.Draw(im); f = G.pil_font(40, "kai")
    for k, t in enumerate(["铅笔批注：此处需核对转账时间", "与银行流水第三页对照", "询问笔录前后不一致"]):
        d.text((150, 1250 + 70 * k), t, font=f, fill=(160, 160, 160))
    return im

def stats(img):
    m = D.watermark_mask(img)
    small = Image.fromarray(m.astype(np.uint8) * 255).resize((m.shape[1] // 4, m.shape[0] // 4), Image.BOX).point(lambda v: 255 if v >= 64 else 0)
    diag = {a: D._profile(small, a) for a in D.DIAG_ANGLES}
    best = max(diag, key=lambda a: D._strength(diag[a]))
    p = diag[best]
    band = p > p[p > 0].mean() if (p > 0).any() else p > 0
    out_frac = p[~band].sum() / max(p.sum(), 1)
    ax = [round(D._strength(D._profile(small, a)), 3) for a in D.AXIS_ANGLES]
    return dict(area=round(m.mean(), 3), best=best, diag=round(D._strength(p), 3), axis=ax, out=round(out_frac, 3), is_diag=D.is_diagonal_repeat(m))

pages = scan_pages()
for i, p in enumerate(pages): print("scan", i + 1, stats(p))
print("graytext+wm", stats(gray_text_page(True)))
print("graytext   ", stats(gray_text_page(False)))
print("hand+wm    ", stats(hand_page()))

def blocks(img, gy=14, gx=10):
    m = D.watermark_mask(img).astype(float)
    H, W = m.shape; h, w = H // gy, W // gx
    dens = np.array([[m[r*h:(r+1)*h, c*w:(c+1)*w].mean() for c in range(gx)] for r in range(gy)])
    med = np.median(dens)
    return round(dens.max() / med, 2), round(np.sort(dens.ravel())[-3] / med, 2)

print("--- blocks max/median, 3rd/median")
for i, p in enumerate(pages): print("scan", i + 1, blocks(p))
print("hand+wm", blocks(hand_page()))
print("graytext+wm", blocks(gray_text_page(True)))
