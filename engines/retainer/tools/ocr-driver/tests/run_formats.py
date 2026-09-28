# -*- coding: utf-8 -*-
"""
多格式装载与识别验证

逐格式验证：能否解析、是否走了 OCR、能取到多少文字、耗时多少。
"""
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER_DIR = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(DRIVER_DIR, "vendor"))
sys.path.insert(0, DRIVER_DIR)

os.environ.setdefault("HF_HUB_OFFLINE", "1")

import docloader  # noqa: E402
import fieldfix  # noqa: E402

CORPUS = os.path.join(HERE, "format-corpus")
LOG = os.path.join(HERE, "_last_format_run.txt")

CASES = [
    ("license.png", "PNG 图片"),
    ("license-q90.jpg", "JPG 图片（质量 90）"),
    ("license-q70.jpeg", "JPEG 图片（质量 70）"),
    ("license-text.pdf", "PDF（有文本层）"),
    ("license-scan.pdf", "PDF（扫描件，无文本层）"),
    ("license.docx", "DOCX（文字＋表格＋内嵌图片）"),
    ("license-noext", "无扩展名（内容为 PNG）"),
    ("license-old.doc", "老版 .doc"),
]

KEY_PHRASES = ["深圳市示例科技有限公司", "91440300MA5EXAMPLA", "张三"]

log = []
engine = None


def init_engine():
    from rapidocr import RapidOCR
    t0 = time.time()
    e = RapidOCR()
    return e, time.time() - t0


def ocr_images(eng, images):
    """对图像列表逐个识别，返回 (文本行集合, 明细)"""
    all_lines, detail = [], []
    for label, png in images:
        t0 = time.time()
        try:
            raw = eng(png)
        except Exception as e:
            detail.append({"label": label, "error": str(e)[:200]})
            continue
        txts = getattr(raw, "txts", None)
        scores = getattr(raw, "scores", None)
        boxes = getattr(raw, "boxes", None)
        if txts is None and isinstance(raw, (list, tuple)) and len(raw) == 2:
            seq = raw[0] or []
            txts = [x[1] for x in seq]
            scores = [x[2] for x in seq]
            boxes = [x[0] for x in seq]
        lines = []
        for i, t in enumerate(txts or []):
            box = boxes[i] if boxes is not None and i < len(boxes) else None
            if box is not None:
                box = [[int(p[0]), int(p[1])] for p in box]
            lines.append({
                "text": str(t),
                "score": None if scores is None or i >= len(scores) else round(float(scores[i]), 4),
                "box": box,
            })
        all_lines.extend(lines)
        detail.append({"label": label, "seconds": round(time.time() - t0, 2), "lines": len(lines)})
    return all_lines, detail


def main():
    global log
    eng, init_s = init_engine()
    log.append("引擎初始化 %.2f 秒" % init_s)
    log.append("")

    summary = []
    for fname, desc in CASES:
        path = os.path.join(CORPUS, fname)
        log.append("=" * 68)
        log.append("%s　（%s）" % (fname, desc))
        if not os.path.exists(path):
            log.append("  文件不存在，跳过")
            continue
        data = open(path, "rb").read()
        sniffed = docloader.sniff(data)
        log.append("  实际类型（按文件头）：%s" % (sniffed or "未知"))

        t0 = time.time()
        try:
            r = docloader.load_smart(data, fname)
        except Exception as e:
            log.append("  装载失败：%s" % str(e)[:300])
            summary.append({"file": fname, "desc": desc, "loaded": False, "error": str(e)[:200]})
            log.append("")
            continue
        load_s = time.time() - t0

        log.append("  格式=%s　文本层 %d 字　待识别图像 %d 张　装载 %.2fs" % (
            r.format, len(r.text), len(r.images), load_s))
        for n in r.notes:
            log.append("  · " + n)

        lines, detail = ocr_images(eng, r.images)
        ocr_s = time.time() - t0 - load_s
        for d in detail:
            if d.get("error"):
                log.append("  OCR 失败 %s：%s" % (d["label"], d["error"]))
            else:
                log.append("  OCR %s：%.2fs，%d 行" % (d["label"], d["seconds"], d["lines"]))

        combined = r.text + "\n" + "\n".join(l["text"] for l in lines)
        log.append("  --- 文本（文本层 + OCR 合并，前 300 字）---")
        for ln in combined.strip().splitlines()[:12]:
            log.append("    " + ln)
        found = [p for p in KEY_PHRASES if p in combined]
        log.append("  关键信息命中：%d/%d  %s" % (len(found), len(KEY_PHRASES), "、".join(found)))

        fields = {}
        if lines:
            fields, meta = fieldfix.extract("business_license", lines)
            log.append("  字段解析（来自 OCR 部分）：%s" % json.dumps(fields, ensure_ascii=False))

        summary.append({
            "file": fname, "desc": desc, "loaded": True, "format": r.format,
            "textChars": len(r.text), "imageCount": len(r.images),
            "usedOcr": len(r.images) > 0, "keyHit": len(found),
            "loadSeconds": round(load_s, 2), "ocrSeconds": round(ocr_s, 2),
            "notes": r.notes,
        })
        log.append("")

    log.append("=" * 68)
    log.append("汇总")
    log.append("%-20s %-8s %-7s %-8s %-9s %s" % ("文件", "格式", "文本字", "图像", "走OCR", "关键命中"))
    for s in summary:
        if not s.get("loaded"):
            log.append("%-20s %s" % (s["file"], "装载失败：" + s.get("error", "")))
            continue
        log.append("%-20s %-8s %-7d %-8d %-9s %d/3" % (
            s["file"], s["format"], s["textChars"], s["imageCount"],
            "是" if s["usedOcr"] else "否", s["keyHit"]))

    with open(LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(log))
    with open(os.path.join(HERE, "results", "formats.json"), "w", encoding="utf-8") as f:
        json.dump({"cases": summary}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
