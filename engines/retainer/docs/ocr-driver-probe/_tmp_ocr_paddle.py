# -*- coding: utf-8 -*-
"""离线 OCR 实测：PaddleOCR 本地推理，关闭 oneDNN 以避免 PIR/oneDNN 兼容缺陷"""
import os
import time
import traceback

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

LOG = r"D:\workbuddy测试\_ocr_paddle_result.txt"
log = []
imgs = [r"D:\workbuddy测试\_tmp_ocr_license.png", r"D:\workbuddy测试\_tmp_ocr_idcard.png"]

base = dict(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
)
attempts = [
    ("enable_mkldnn=False", dict(base, enable_mkldnn=False)),
    ("cpu+enable_mkldnn=False", dict(base, device="cpu", enable_mkldnn=False)),
    ("default", dict(base)),
]

try:
    from paddleocr import PaddleOCR
    log.append("paddleocr import OK")
    ocr = None
    for label, kw in attempts:
        t = time.time()
        try:
            ocr = PaddleOCR(**kw)
            log.append("engine init OK with [%s] seconds=%.1f" % (label, time.time() - t))
            break
        except Exception as e:
            log.append("engine init FAILED with [%s] : %s" % (label, str(e)[:200]))
    if ocr is None:
        raise RuntimeError("no engine variant could be initialised")

    for p in imgs:
        t1 = time.time()
        try:
            res = ocr.predict(p)
        except AttributeError:
            res = ocr.ocr(p, cls=False)
        texts = []
        for r in res:
            d = None
            if hasattr(r, "json"):
                d = r.json
            elif isinstance(r, dict):
                d = r
            if isinstance(d, dict):
                d = d.get("res", d)
                texts.extend(d.get("rec_texts", []) or [])
        log.append("IMAGE %s seconds=%.2f lines=%d" % (os.path.basename(p), time.time() - t1, len(texts)))
        for t in texts:
            log.append("  | " + str(t))
except Exception as e:
    log.append("OCR FAILED: " + str(e))
    log.append(traceback.format_exc()[-1500:])

with open(LOG, "w", encoding="utf-8") as f:
    f.write("\n".join(log))
