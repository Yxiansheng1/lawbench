"""上线必过第 16a 项：去水印后原件不变，印章、签名、手写批注未被去除。

python acceptance\\sec\\dewatermark_395.py
用 tests\\fixtures\\criminal-01\\讯问笔录.pdf 的第 2 页（蓝色批注）、第 3 页（红章）请求真实 395：
/v1/ocr/page?dewatermark=true&return_image=true，比较返回的工作副本与原图的红色、蓝色像素数，
并核对原件 PDF 的 sha256 前后不变。需要 395 已部署（T11）和一个可用的测试 Key（.env.local 的 LAWFIRM_TEST_KEY_A）。
"引用仍指向原件"由 T12 的测试覆盖（识别页的出处写原件页码），这里不重复。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FAIL, FIXTURES, PASS, SERVERS, UNMET, Report, env_local, http  # noqa: E402


def counts(img):
    import numpy as np
    a = np.asarray(img.convert("RGB")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    red = int(((r > 150) & (g < 110) & (b < 110)).sum())
    blue = int(((b > 120) & (r < 90) & (g < 120)).sum())
    return red, blue


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    r = Report("dewatermark_395", "上线必过第 16a 项；SEC-12", a.out)
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as pdfium_c
        from PIL import Image
    except ImportError:
        r.finish(UNMET, "缺少 pypdfium2 / Pillow / numpy（用仓库 .venv 的 Python 运行）")
    key = env_local().get("LAWFIRM_TEST_KEY_A")
    base = next((b for b in SERVERS["395"] if http("GET", b + "/health", timeout=2)[0] == 200), None)
    if not base:
        r.finish(UNMET, "395 的预处理服务连不上（T11 部署后再测）")
    if not key:
        r.finish(UNMET, ".env.local 里没有 LAWFIRM_TEST_KEY_A")
    pdf = FIXTURES / "criminal-01" / "讯问笔录.pdf"
    before = hashlib.sha256(pdf.read_bytes()).hexdigest()
    doc = pdfium.PdfDocument(str(pdf))
    bad = []
    for idx, what in ((1, "蓝色批注"), (2, "红章")):
        obj = list(doc[idx].get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE]))[0]
        img = obj.get_bitmap().to_pil().convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        st, _, body = http("POST", base + "/v1/ocr/page?dewatermark=true&deskew=false&return_image=true",
                           headers={"Authorization": f"Bearer {key}"}, raw=buf.getvalue(), ctype="image/png",
                           timeout=180)
        if st != 200:
            r.finish(UNMET, f"第 {idx + 1} 页识别请求返回 HTTP {st}")
        import json
        shot = json.loads(body)["image_png_base64"]
        out = Image.open(io.BytesIO(base64.b64decode(shot)))
        (r0, b0), (r1, b1) = counts(img), counts(out)
        r.log(f"第 {idx + 1} 页（{what}）：红色像素 {r0} → {r1}，蓝色像素 {b0} → {b1}")
        if r1 != r0 or b1 != b0:
            bad.append(f"第 {idx + 1} 页")
    doc.close()
    after = hashlib.sha256(pdf.read_bytes()).hexdigest()
    r.log(f"原件 sha256 前后{'一致' if before == after else '不一致'}")
    if bad or before != after:
        r.finish(FAIL, "印章或批注像素有变化：" + "、".join(bad) if bad else "原件被改动")
    r.finish(PASS, "去水印后红章、蓝色批注像素数不变，原件不变")


if __name__ == "__main__":
    main()
