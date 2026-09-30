"""G-5 / G-6 实测（T11 第 4 步）：在开发机上对 395 的 prep395 发请求，量识别和抽取的速度与准确率。

python prep395\\deploy\\bench_g5g6.py --base http://192.168.8.124:9000 [--pages 20] [--out g5-g6.md]

- 样本：tests\\fixtures\\criminal-01\\讯问笔录.pdf 的 3 页扫描图，另用样本生成器现造 N 页扫描页
  （虚构文字，含姓名、日期、金额、证件号；一半带水印），渲染前的文字就是标准答案。
- G-5 识别：每页耗时；并发 1 / 2 / 3 时的吞吐（页/分钟）；字符准确率（与标准答案的相似度）；
  数字、姓名、日期三类关键字段的命中率；"看不清"标注（■、[看不清]）的数量。
- G-6 抽取：用起诉意见书的材料文本请求 9B 抽取日期、金额、案号，核对值能否在所标位置原样找到。
- Key 取仓库根 .env.local 的 LAWFIRM_TEST_KEY_A，不打印。结果写成 Markdown（只含数字，不含识别出的正文）。
"""
from __future__ import annotations

import argparse
import difflib
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "fixtures"
sys.path.insert(0, str(FIX / "_gen"))

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def env_key() -> str:
    for line in (REPO / ".env.local").read_text(encoding="utf-8").splitlines():
        if line.startswith("LAWFIRM_TEST_KEY_A="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(".env.local 里没有 LAWFIRM_TEST_KEY_A")


def post(url: str, body: bytes, ctype: str, key: str, timeout: float = 180):
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": ctype, "Authorization": f"Bearer {key}"})
    t0 = time.time()
    try:
        with _opener.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read()), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, {}, time.time() - t0
    except (urllib.error.URLError, OSError):
        return None, {}, time.time() - t0


# ---------------------------------------------------------------- 样本

FAKE_LINES = [
    "询问笔录（第{n}次）",
    "时间：2026年{m}月{d}日9时15分至10时40分",
    "被询问人：{name}，身份证号990102198{m}0{d}00{n:02d}（虚构）",
    "问：你于2025年{m}月{d}日向对方转账多少钱？",
    "答：转了人民币{amt}元，是通过手机银行转的。",
    "问：收款账户尾号是多少？",
    "答：尾号{tail}，户名是{name2}。",
    "问：以上所说是否属实？",
    "答：属实。",
]
NAMES = ["赵某甲", "钱某乙", "孙某丙", "李某丁", "周某戊", "吴某己", "郑某庚", "王某辛"]


def make_pages(n: int):
    import common as G
    import case_criminal01 as K
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c
    pages = []
    doc = pdfium.PdfDocument(str(FIX / "criminal-01" / "讯问笔录.pdf"))
    for i in range(len(doc)):
        img = list(doc[i].get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE]))[0].get_bitmap().to_pil().convert("RGB")
        pages.append((f"讯问笔录第{i + 1}页", img, K.XUNWEN[i], True))
    for k in range(n):
        vals = dict(n=k + 1, m=(k % 9) + 1, d=(k % 20) + 10, name=NAMES[k % 8], name2=NAMES[(k + 3) % 8],
                    amt=f"{(k + 3) * 12345:,}", tail=f"{(k * 7919) % 10000:04d}")
        text = "\n".join(line.format(**vals) for line in FAKE_LINES)
        img = G.render_page(text, seed=500 + k)
        wm = k % 2 == 0
        if wm:
            img = G.add_watermark(img, "仅供办案使用")
        pages.append((f"虚构样本{k + 1:02d}", img, text, wm))
    return pages


def key_fields(text: str) -> list[str]:
    pats = [r"\d{4}年\d{1,2}月\d{1,2}日", r"[\d,]+元", r"99\d{16}", r"尾号\d{4}", r"[赵钱孙李周吴郑王张刘陈]某[甲乙丙丁戊己庚辛]?"]
    out = []
    for p in pats:
        out += re.findall(p, text)
    return out


def squash(s: str) -> str:
    return re.sub(r"\s|[#*>|`\-]", "", s)


# ---------------------------------------------------------------- G-5

def ocr_one(base, key, img, dewatermark):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    q = "?dewatermark=true" if dewatermark else ""
    return post(f"{base}/v1/ocr/page{q}", buf.getvalue(), "image/png", key)


def g5(base, key, pages, lines):
    lines.append("## G-5 识别\n")
    lines.append("| 页 | 水印 | 耗时（秒） | 应有字数 | 输出字数 | 字符相似度 | 关键字段命中 | ■ / [看不清] |")
    lines.append("|---|---|---|---|---|---|---|---|")
    tot_sim, tot_hit, tot_key, times = 0.0, 0, 0, []
    for name, img, truth, wm in pages:
        st, body, dt = ocr_one(base, key, img, wm)
        if st != 200:
            lines.append(f"| {name} | {'有' if wm else '无'} | — | {len(squash(truth))} | — | 请求失败 HTTP {st} | — | — |")
            continue
        md = body.get("markdown", "")
        sim = difflib.SequenceMatcher(None, squash(truth), squash(md)).ratio()
        kf = key_fields(truth)
        hit = sum(1 for f in kf if f in md or f.replace(",", "") in md)
        times.append(dt)
        tot_sim += sim
        tot_hit += hit
        tot_key += len(kf)
        lines.append(f"| {name} | {'有' if wm else '无'} | {dt:.1f} | {len(squash(truth))} | {len(squash(md))} | {sim:.3f} | "
                     f"{hit}/{len(kf)} | {body.get('unclear', 0)} |")
    if times:
        lines.append(f"\n单页平均 {sum(times) / len(times):.1f} 秒；平均字符相似度 {tot_sim / len(times):.3f}；"
                     f"关键字段命中率 {tot_hit}/{tot_key}（{tot_hit / max(tot_key, 1):.1%}）\n")
    lines.append("### 并发吞吐\n")
    lines.append("| 并发 | 页数 | 总耗时（秒） | 吞吐（页/分钟） | 失败 |")
    lines.append("|---|---|---|---|---|")
    imgs = [p[1] for p in pages]
    for c in (1, 2, 3):
        t0 = time.time()
        with ThreadPoolExecutor(c) as ex:
            res = list(ex.map(lambda im: ocr_one(base, key, im, False), imgs))
        dt = time.time() - t0
        fail = sum(1 for st, _, _ in res if st != 200)
        lines.append(f"| {c} | {len(imgs)} | {dt:.1f} | {len(imgs) / dt * 60:.1f} | {fail} |")
    lines.append("")


# ---------------------------------------------------------------- G-6

def g6(base, key, lines):
    import case_criminal01 as K
    text = "".join(f"【第{i}页】\n{t}\n" for i, t in enumerate(K.QISU, 1))
    body = json.dumps({"task": "fields", "text": text, "fields": ["日期", "金额", "案号", "当事人"]}).encode()
    lines.append("## G-6 9B 抽取\n")
    st, res, dt = post(f"{base}/v1/extract", body, "application/json", key)
    if st != 200:
        lines.append(f"请求失败 HTTP {st}\n")
        return
    items = res.get("result", [])
    pages = {i: t for i, t in enumerate(K.QISU, 1)}
    ok = 0
    for it in items:
        m = re.fullmatch(r"第(\d+)页", it.get("loc", ""))
        if m and it.get("value") and it["value"] in pages.get(int(m.group(1)), ""):
            ok += 1
    lines.append(f"耗时 {dt:.1f} 秒；返回 {len(items)} 条，值能在所标页原样找到的 {ok} 条"
                 f"（{ok / max(len(items), 1):.0%}）。客户端丢弃比例超过 20% 时改由 27B（F-ENT-04）。\n")
    t = json.dumps({"task": "classify", "text": K.XUNWEN[0],
                    "categories": ["起诉意见书", "讯问笔录", "询问笔录", "书证", "鉴定意见", "合同", "其他"]}).encode()
    st, res, dt = post(f"{base}/v1/extract", t, "application/json", key)
    lines.append(f"分类：HTTP {st}，耗时 {dt:.1f} 秒，结果 {res.get('result', {}).get('category')}（应为 讯问笔录）\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="G-5 / G-6 实测")
    ap.add_argument("--base", default="http://192.168.8.124:9000")
    ap.add_argument("--pages", type=int, default=20)
    ap.add_argument("--server-np", type=int, required=True,
                    help="395 上 OCR 后端的并行槽数（install.ps1 的 -OcrParallel），只记进报告")
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "plan" / "evidence" / "T11" / "g5-g6.md")
    a = ap.parse_args()
    key = env_key()
    with _opener.open(a.base + "/health", timeout=5) as r:
        health = json.loads(r.read())
    lines = [f"# G-5 / G-6 实测（{time.strftime('%Y-%m-%d %H:%M')}）", "",
             f"- 目标：{a.base}；/health：{json.dumps(health, ensure_ascii=False)}",
             f"- 样本：讯问笔录 3 页扫描件 + 现造 {a.pages} 页（一半带水印），全部虚构",
             f"- 服务端 OCR 并行槽数 -np = {a.server_np}（install.ps1 -OcrParallel）；并发数超过它的那几行只是排队，不算测过",
             "- 字数按去掉空白后的字符数计，只记数字，不含识别出的正文", ""]
    pages = make_pages(a.pages)
    g5(a.base, key, pages, lines)
    g6(a.base, key, lines)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n已写入 {a.out}")


if __name__ == "__main__":
    main()
