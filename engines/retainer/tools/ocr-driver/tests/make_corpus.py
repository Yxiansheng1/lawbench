# -*- coding: utf-8 -*-
"""
生成合成测试语料（全部为虚构内容），覆盖证件识别的常见畸变场景。

用途：多轮测试的输入侧。语料一次生成、多次复用，保证各轮测试输入完全一致。
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "corpus")

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
]

LICENSE_TEXT = [
    "营业执照",
    "名　　称　深圳市示例科技有限公司",
    "统一社会信用代码　91440300MA5EXAMPLA",
    "类　　型　有限责任公司",
    "法定代表人　张三",
    "住　　所　广东省深圳市福田区示例路1号",
    "成立日期　2020年09月01日",
]

IDCARD_TEXT = [
    "居民身份证",
    "姓名　李四　性别　男　民族　汉",
    "出生　1985年3月12日",
    "住址　广东省深圳市南山区示例路2号",
    "公民身份号码　11010519491231002X",
]

EXPECT = {
    "business_license": {
        "name": "深圳市示例科技有限公司",
        "credit_code": "91440300MA5EXAMPLA",
        "org_type": "有限责任公司",
        "legal_rep": "张三",
        "address": "广东省深圳市福田区示例路1号",
        "established": "2020年09月01日",
    },
    "id_card_front": {
        "name": "李四",
        "gender": "男",
        "ethnicity": "汉",
        "birth": "1985年3月12日",
        "address": "广东省深圳市南山区示例路2号",
        "id_number": "11010519491231002X",
    },
}


def pick_font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    raise RuntimeError("找不到中文字体")


def base_image(lines, font_path, font_size=26, title_size=34, width=1000):
    title_font = ImageFont.truetype(font_path, title_size)
    body_font = ImageFont.truetype(font_path, font_size)
    h = 60 + 50 * len(lines) + 30
    img = Image.new("RGB", (width, h), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 22), lines[0], fill="black", font=title_font)
    y = 84
    for t in lines[1:]:
        d.text((50, y), t, fill="black", font=body_font)
        y += 50
    return img


def deform(img, kind):
    """返回 (处理后的图, 说明)"""
    from PIL import ImageEnhance, ImageFilter
    import numpy as np

    if kind == "clean":
        return img, "白底印刷体，正面平拍"

    if kind.startswith("rotate"):
        deg = float(kind.replace("rotate", ""))
        return img.rotate(deg, resample=Image.BICUBIC, expand=True, fillcolor="white"), "旋转 %s 度" % deg

    if kind == "blur":
        return img.filter(ImageFilter.GaussianBlur(1.2)), "高斯模糊 1.2"

    if kind == "noise":
        arr = np.array(img).astype(np.int16)
        rng = np.random.default_rng(20260913)
        noise = rng.normal(0, 18, arr.shape)
        arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
        return Image.fromarray(arr), "高斯噪点 σ=18"

    if kind == "jpeg60":
        return img, "JPEG 质量 60（保存时施加）"

    if kind == "lowres":
        w, h = img.size
        small = img.resize((int(w * 0.45), int(h * 0.45)), Image.BILINEAR)
        return small.resize((w, h), Image.BILINEAR), "降采样至 45% 再放大"

    if kind == "shadow":
        arr = np.array(img).astype(np.float32)
        w = arr.shape[1]
        grad = np.linspace(1.0, 0.55, w).reshape(1, w, 1)
        arr = np.clip(arr * grad, 0, 255).astype(np.uint8)
        return Image.fromarray(arr), "左侧亮右侧暗的渐变阴影"

    if kind == "scanbw":
        gray = img.convert("L")
        bw = gray.point(lambda x: 0 if x < 150 else 255).convert("RGB")
        return bw, "二值化，模拟复印件"

    if kind == "lowcontrast":
        arr = np.array(img).astype(np.float32)
        arr = 200 + (arr - 200) * 0.45
        return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)), "低对比度"

    return img, "未处理"


VARIANTS = ["clean", "rotate3", "rotate-5", "blur", "noise", "jpeg60", "lowres", "shadow", "scanbw", "lowcontrast"]

SOURCES = [
    ("license", "business_license", LICENSE_TEXT),
    ("idcard", "id_card_front", IDCARD_TEXT),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    font = pick_font()
    cases = []
    for prefix, doc_type, lines in SOURCES:
        base = base_image(lines, font)
        for kind in VARIANTS:
            img, note = deform(base, kind)
            name = "%s-%s.png" % (prefix, kind)
            path = os.path.join(OUT, name)
            if kind == "jpeg60":
                img.save(path, quality=60)
            else:
                img.save(path)
            cases.append({
                "id": "%s-%s" % (prefix, kind),
                "file": "corpus/" + name,
                "docType": doc_type,
                "scene": note,
                "expect": EXPECT[doc_type],
            })

    corpus = {
        "version": "1.0",
        "createdAt": "2026-09-13",
        "note": "全部为脚本生成的虚构内容，不含任何真实证件信息",
        "cases": cases,
    }
    with open(os.path.join(HERE, "corpus.json"), "w", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False, indent=1)

    with open(os.path.join(HERE, "_corpus_built.txt"), "w", encoding="utf-8") as f:
        f.write("font=%s\ncases=%d\n" % (font, len(cases)))
        for c in cases:
            f.write("%s  %s  %s\n" % (c["id"], c["docType"], c["scene"]))


if __name__ == "__main__":
    main()
