"""样本生成的共用工具：字体、PDF、扫描页渲染、docx 修订与超链接、特征字符串。

全部材料为虚构，人名一律"某"字化，地址、证件号、案号使用不存在的"虚"字行政区。
"""
from __future__ import annotations

import copy
import io
import math
import os
import random
from datetime import datetime
from pathlib import Path

from lxml import etree
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab import rl_config
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

rl_config.invariant = 1  # 固定 PDF 的创建时间和文件 ID，重新生成时内容稳定

FIXTURES = Path(__file__).resolve().parent.parent

# 每个案件一个独有的长字符串，写进该案件的每份材料（SEC-01 全盘搜索用）
FEATURE = {
    "criminal-01": "LBFX-CRIM01-7Q3Z",
    "civil-01": "LBFX-CIVL01-K8M2",
    "contract-01": "LBFX-CONT01-R5T9",
    "attack-01": "LBFX-ATTK01-W2N6",
    "broken": "LBFX-BRKN00-J4H7",
    "closed-01": "LBFX-CLSD01-P6V3",
    "tender-01": "LBFX-TNDR01-X9C4",
    "invoices-01": "LBFX-INVC01-D3F8",
}

# broken\ 中加密文件的密码（虚构测试值，不是任何真实口令）
TEST_PASSWORD = "lbfx-test"

FIXED_TIME = datetime(2026, 9, 29, 9, 0, 0)

FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"

# ---------------------------------------------------------------- 字体

_PDF_FONT = None


def pdf_font() -> str:
    """PDF 正文字体：优先嵌入黑体子集（文字可提取），没有时退回 STSong-Light。"""
    global _PDF_FONT
    if _PDF_FONT:
        return _PDF_FONT
    ttf = FONT_DIR / "simhei.ttf"
    if ttf.exists():
        pdfmetrics.registerFont(TTFont("LBHei", str(ttf)))
        _PDF_FONT = "LBHei"
    else:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        _PDF_FONT = "STSong-Light"
    return _PDF_FONT


def pil_font(size: int, kind: str = "song") -> ImageFont.FreeTypeFont:
    names = {
        "song": ["simsun.ttc", "simhei.ttf", "msyh.ttc"],
        "hei": ["simhei.ttf", "msyh.ttc", "simsun.ttc"],
        "kai": ["simkai.ttf", "STKAITI.TTF", "simsun.ttc"],
    }[kind]
    for n in names:
        p = FONT_DIR / n
        if p.exists():
            return ImageFont.truetype(str(p), size)
    raise SystemExit(f"找不到中文字体（{', '.join(names)}），请在 Windows 上运行")


# ---------------------------------------------------------------- 文字版 PDF


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    lines: list[str] = []
    for raw in text.split("\n"):
        cur = ""
        for ch in raw:
            if pdfmetrics.stringWidth(cur + ch, font, size) > width:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)
    return lines


def text_pdf(path: Path, pages: list[str], feature: str, title: str = "",
             size: float = 11.5) -> None:
    """每个元素一页；页面文字即材料原文（第 N 个元素 = 第 N 页）。"""
    font = pdf_font()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle(title or path.stem)
    c.setAuthor("lawbench 虚构样本")
    c.setKeywords(feature)
    w, h = A4
    for body in pages:
        y = h - 72
        for line in _wrap(body, font, size, w - 144):
            c.setFont(font, size)
            c.drawString(72, y, line)
            y -= size * 1.8
            if y < 60:
                raise ValueError(f"{path.name} 一页放不下，请拆页")
        c.showPage()
    c.save()


def mixed_pdf(path: Path, text: str, image: Image.Image, feature: str) -> None:
    """图文混排：上方文字（≥30 字），下方一张占页面 > 30% 的图片。"""
    font = pdf_font()
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle(path.stem)
    c.setKeywords(feature)
    w, h = A4
    y = h - 72
    for line in _wrap(text, font, 11.5, w - 144):
        c.setFont(font, 11.5)
        c.drawString(72, y, line)
        y -= 20
    img_w = w - 144
    img_h = img_w * image.height / image.width
    buf = io.BytesIO()
    image.convert("RGB").save(buf, "JPEG", quality=70)
    buf.seek(0)
    c.drawImage(ImageReader(buf), 72, y - 12 - img_h, img_w, img_h)
    c.showPage()
    c.save()


def image_pdf(path: Path, images: list[Image.Image], feature: str, quality: int = 55) -> None:
    """扫描件：每页一张整页图片，没有文字层。"""
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle(path.stem)
    c.setKeywords(feature)
    w, h = A4
    for im in images:
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=quality)
        buf.seek(0)
        c.drawImage(ImageReader(buf), 0, 0, w, h)
        c.showPage()
    c.save()


# ---------------------------------------------------------------- 扫描页渲染

PAGE_PX = (1240, 1754)  # A4 @150dpi


def render_page(text: str, seed: int, size: int = 30) -> Image.Image:
    """把文字排成一页"纸"，加轻微噪点和倾斜，像复印扫描件。"""
    rnd = random.Random(seed)
    im = Image.new("RGB", PAGE_PX, (246, 244, 238))
    d = ImageDraw.Draw(im)
    f = pil_font(size, "song")
    x0, y = 120, 140
    maxw = PAGE_PX[0] - 240
    for raw in text.split("\n"):
        cur = ""
        for ch in raw:
            if d.textlength(cur + ch, font=f) > maxw:
                d.text((x0, y), cur, font=f, fill=(35, 35, 35))
                y += int(size * 1.75)
                cur = ch
            else:
                cur += ch
        d.text((x0, y), cur, font=f, fill=(35, 35, 35))
        y += int(size * 1.75)
    px = im.load()
    for _ in range(9000):
        x, yy = rnd.randrange(PAGE_PX[0]), rnd.randrange(PAGE_PX[1])
        g = rnd.randrange(150, 235)
        px[x, yy] = (g, g, g)
    return im.rotate(rnd.uniform(-0.6, 0.6), resample=Image.BICUBIC, fillcolor=(246, 244, 238))


def add_watermark(im: Image.Image, text: str) -> Image.Image:
    """浅灰、低饱和、斜向、大面积重复的水印（去水印测试的对象）。"""
    layer = Image.new("RGBA", (PAGE_PX[0] * 2, PAGE_PX[1] * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = pil_font(56, "hei")
    for yy in range(0, layer.height, 260):
        for xx in range(-200, layer.width, 520):
            d.text((xx + (yy // 260) % 2 * 260, yy), text, font=f, fill=(170, 170, 170, 70))
    layer = layer.rotate(30, resample=Image.BICUBIC)
    left = (layer.width - PAGE_PX[0]) // 2
    top = (layer.height - PAGE_PX[1]) // 2
    layer = layer.crop((left, top, left + PAGE_PX[0], top + PAGE_PX[1]))
    out = im.convert("RGBA")
    out.alpha_composite(layer)
    return out.convert("RGB")


def add_seal(im: Image.Image, center: tuple[int, int], ring_text: str, seed: int = 7) -> Image.Image:
    """红色圆形印章：外圈、五角星、环形文字，带一点不均匀的印泥效果。"""
    r = 150
    layer = Image.new("RGBA", (r * 2 + 20, r * 2 + 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx = cy = r + 10
    red = (210, 30, 35, 230)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=red, width=9)
    pts = []
    for i in range(10):
        ang = math.pi / 2 + i * math.pi / 5
        rr = 46 if i % 2 == 0 else 18
        pts.append((cx + rr * math.cos(ang), cy - rr * math.sin(ang)))
    d.polygon(pts, fill=red)
    f = pil_font(34, "song")
    n = len(ring_text)
    span = math.radians(240)
    for i, ch in enumerate(ring_text):
        ang = math.radians(210) - span * i / max(n - 1, 1)
        tx = cx + (r - 38) * math.cos(ang)
        ty = cy - (r - 38) * math.sin(ang)
        g = Image.new("RGBA", (44, 44), (0, 0, 0, 0))
        ImageDraw.Draw(g).text((5, 2), ch, font=f, fill=red)
        g = g.rotate(math.degrees(ang) - 90, resample=Image.BICUBIC)
        layer.alpha_composite(g, (int(tx - 22), int(ty - 22)))
    rnd = random.Random(seed)
    px = layer.load()
    for _ in range(2500):  # 印泥不均
        x, y = rnd.randrange(layer.width), rnd.randrange(layer.height)
        if px[x, y][3]:
            px[x, y] = (px[x, y][0], px[x, y][1], px[x, y][2], rnd.randrange(60, 200))
    out = im.convert("RGBA")
    out.alpha_composite(layer, (center[0] - cx, center[1] - cy))
    return out.convert("RGB")


def add_handwriting(im: Image.Image, pos: tuple[int, int], text: str, seed: int = 3) -> Image.Image:
    """蓝色手写批注：楷体字加一条手画的波浪下划线。"""
    rnd = random.Random(seed)
    out = im.copy()
    d = ImageDraw.Draw(out)
    f = pil_font(40, "kai")
    x, y = pos
    for ch in text:
        d.text((x, y + rnd.randint(-4, 4)), ch, font=f, fill=(25, 60, 190))
        x += 40 + rnd.randint(-3, 3)
    pts = [(pos[0] + i * 12, pos[1] + 54 + 5 * math.sin(i / 2.0) + rnd.uniform(-1.5, 1.5))
           for i in range((x - pos[0]) // 12)]
    d.line(pts, fill=(25, 60, 190), width=4)
    return out


def screenshot_image(lines: list[tuple[str, int, tuple[int, int, int]]], size=(750, 1334)) -> Image.Image:
    """手机截图样式的图片：(文字, 字号, 颜色) 逐行居中。"""
    im = Image.new("RGB", size, (245, 245, 245))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, size[0], 88), fill=(40, 120, 220))
    y = 150
    for text, fs, color in lines:
        f = pil_font(fs, "hei")
        tw = d.textlength(text, font=f)
        d.text(((size[0] - tw) / 2, y), text, font=f, fill=color)
        y += int(fs * 1.9)
    return im


def save_jpeg(im: Image.Image, path: Path, comment: str, quality: int = 80) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im.convert("RGB").save(path, "JPEG", quality=quality, comment=comment.encode("ascii"))


# ---------------------------------------------------------------- docx

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _w(tag: str) -> str:
    return f"{{{W}}}{tag}"


def fix_core(doc, title: str, feature: str) -> None:
    cp = doc.core_properties
    cp.title = title
    cp.author = "lawbench 虚构样本"
    cp.last_modified_by = "lawbench 虚构样本"
    cp.keywords = feature
    cp.created = FIXED_TIME
    cp.modified = FIXED_TIME
    cp.revision = 1


def set_east_asian_font(doc, name: str = "宋体", size_pt: float = 12) -> None:
    from docx.shared import Pt
    st = doc.styles["Normal"]
    st.font.name = name
    st.font.size = Pt(size_pt)
    rpr = st.element.get_or_add_rPr()
    fonts = rpr.find(_w("rFonts"))
    if fonts is None:
        fonts = etree.SubElement(rpr, _w("rFonts"))
    fonts.set(_w("eastAsia"), name)


def _run(text: str, deleted: bool = False):
    r = etree.Element(_w("r"))
    t = etree.SubElement(r, _w("delText" if deleted else "t"))
    t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return r


_rev_id = [100]


def revision_paragraph(paragraph, parts: list[tuple[str, str]], author: str = "某某律师（虚构）",
                       date: str = "2026-03-09T10:00:00Z") -> None:
    """用 (kind, text) 片段重写一段：kind 为 'keep' / 'ins' / 'del'，生成真实的 w:ins / w:del 修订。"""
    p = paragraph._p
    for r in list(p.findall(_w("r"))):
        p.remove(r)
    for kind, text in parts:
        if kind == "keep":
            p.append(_run(text))
        else:
            _rev_id[0] += 1
            el = etree.SubElement(p, _w("ins" if kind == "ins" else "del"))
            el.set(_w("id"), str(_rev_id[0]))
            el.set(_w("author"), author)
            el.set(_w("date"), date)
            el.append(_run(text, deleted=(kind == "del")))


def add_hyperlink(paragraph, url: str, text: str) -> None:
    part = paragraph.part
    rid = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                         is_external=True)
    h = etree.SubElement(paragraph._p, _w("hyperlink"))
    h.set(f"{{{R_NS}}}id", rid)
    r = etree.SubElement(h, _w("r"))
    rpr = etree.SubElement(r, _w("rPr"))
    etree.SubElement(rpr, _w("color")).set(_w("val"), "0563C1")
    etree.SubElement(rpr, _w("u")).set(_w("val"), "single")
    t = etree.SubElement(r, _w("t"))
    t.text = text


def header_footer(doc, header: str, footer: str) -> None:
    sec = doc.sections[0]
    sec.header.paragraphs[0].text = header
    sec.footer.paragraphs[0].text = footer


def body_paragraphs(docx_path: Path) -> list[str]:
    """按 Spec 5.2 的段号规则读正文：非空段落顺序号从 1 开始，表格整体算一段；
    保留 w:ins、去掉 w:del。返回每段的纯文本（表格为单元格用 | 连接的行）。"""
    import zipfile
    with zipfile.ZipFile(docx_path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    body = root.find(_w("body"))
    out: list[str] = []

    def ptext(p) -> str:
        return "".join(t.text or "" for t in p.iter(_w("t")))

    for el in body:
        if el.tag == _w("p"):
            s = ptext(el)
            if s.strip():
                out.append(s)
        elif el.tag == _w("tbl"):
            rows = []
            for tr in el.iter(_w("tr")):
                cells = ["".join(ptext(p) for p in tc.iter(_w("p"))) for tc in tr.findall(_w("tc"))]
                rows.append("|".join(cells))
            out.append("\n".join(rows))
    return out


def docx_all_text(docx_path: Path) -> str:
    """document、页眉、页脚、脚注中的全部可见文字（不含 w:delText）。"""
    import zipfile
    parts = []
    with zipfile.ZipFile(docx_path) as z:
        for n in z.namelist():
            if n.startswith("word/") and n.endswith(".xml") and any(
                    k in n for k in ("document", "header", "footer", "footnotes")):
                root = etree.fromstring(z.read(n))
                parts.append("".join(t.text or "" for t in root.iter(_w("t"))))
    return "\n".join(parts)


def clone(x):
    return copy.deepcopy(x)
