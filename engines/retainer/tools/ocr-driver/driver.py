#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
委托材料工作台 · 本地证件识别驱动 v0.1

设计约束
  1. 只监听 127.0.0.1，不接受外部连接；
  2. 不落盘、不出网，图片仅在内存中处理；
  3. 只返回「带坐标的文本行」，不返回业务字段 —— 字段解析与校验由 HTML 侧完成。

用法
  python driver.py                    # 自动选择可用引擎，端口 17801
  python driver.py --engine rapidocr  # 指定引擎
  python driver.py --port 17801
"""
import argparse
import io
import json
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 以 pythonw.exe 无窗口启动时 stdout/stderr 为 None，print 会抛异常，这里兜底
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

# 让驱动自带依赖：优先使用同目录 vendor 下的包（隔离安装，不污染系统 Python）
_HERE = os.path.dirname(os.path.abspath(__file__))
_VENDOR = os.path.join(_HERE, "vendor")
if os.path.isdir(_VENDOR):
    sys.path.insert(0, _VENDOR)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import docloader  # noqa: E402

MAX_BYTES = 50 * 1024 * 1024
ALLOWED_ORIGIN = "*"
# ThreadingHTTPServer 会并发处理请求，而引擎实例内部有共享状态，识别必须串行
OCR_LOCK = threading.Lock()


def err(msg):
    return {"ok": False, "error": msg}


class EngineBase:
    name = "none"
    version = ""
    hint = ""

    def init(self):
        raise NotImplementedError

    def recognize(self, data):
        raise NotImplementedError

    @staticmethod
    def to_gray_array(data):
        import numpy as np
        import cv2
        buf = np.frombuffer(data, np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)

    @staticmethod
    def pack(lines, started, extra=None):
        out = {
            "ok": True,
            "engine": None,
            "durationMs": int((time.time() - started) * 1000),
            "lines": lines,
            "warnings": [],
        }
        if extra:
            out.update(extra)
        return out


class RapidOcrEngine(EngineBase):
    name = "rapidocr"
    hint = "pip install rapidocr onnxruntime（模型需预先下载，见 --download-models）"

    def init(self):
        from rapidocr import RapidOCR
        try:
            import rapidocr as _r
            self.version = str(getattr(_r, "__version__", ""))
        except Exception:
            pass
        self.engine = RapidOCR()

    def recognize(self, data):
        started = time.time()
        img = self.to_gray_array(data)
        raw = self.engine(img)

        boxes = getattr(raw, "boxes", None)
        txts = getattr(raw, "txts", None)
        scores = getattr(raw, "scores", None)

        if txts is None and isinstance(raw, (list, tuple)) and len(raw) == 2:
            seq = raw[0] or []
            txts = [x[1] for x in seq]
            scores = [x[2] for x in seq]
            boxes = [x[0] for x in seq]

        lines = []
        for i, text in enumerate(txts or []):
            box = boxes[i] if boxes is not None and i < len(boxes) else None
            sc = scores[i] if scores is not None and i < len(scores) else None
            lines.append({
                "text": str(text),
                "score": None if sc is None else round(float(sc), 4),
                "box": None if box is None else [[int(p[0]), int(p[1])] for p in box],
            })
        out = self.pack(lines, started)
        out["engine"] = self.name
        return out


class PaddleOcrEngine(EngineBase):
    name = "paddleocr"
    hint = "pip install paddleocr paddlepaddle（本机模型目录 ~/.paddlex/official_models）"

    def init(self):
        from paddleocr import PaddleOCR
        try:
            import paddleocr as _p
            self.version = str(getattr(_p, "__version__", ""))
        except Exception:
            pass
        try:
            self.engine = PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                enable_mkldnn=False,
            )
        except TypeError:
            self.engine = PaddleOCR()

    def recognize(self, data):
        started = time.time()
        import numpy as np
        import cv2
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        try:
            res = self.engine.predict(img)
        except AttributeError:
            res = self.engine.ocr(img, cls=False)
        lines = []
        for r in res:
            d = r.json if hasattr(r, "json") else r
            if isinstance(d, dict):
                d = d.get("res", d)
                texts = d.get("rec_texts", []) or []
                scores = d.get("rec_scores", []) or []
                polys = d.get("rec_polys", None)
                if polys is None:
                    polys = d.get("dt_polys", None)
                for i, t in enumerate(texts):
                    box = None
                    if polys is not None and i < len(polys):
                        box = [[int(p[0]), int(p[1])] for p in polys[i]]
                    lines.append({
                        "text": str(t),
                        "score": None if i >= len(scores) else round(float(scores[i]), 4),
                        "box": box,
                    })
        out = self.pack(lines, started)
        out["engine"] = self.name
        return out


ENGINES = [RapidOcrEngine, PaddleOcrEngine]


def build_engine(name=None):
    order = ENGINES
    if name:
        order = [e for e in ENGINES if e.name == name]
        if not order:
            raise RuntimeError("未知引擎：" + name)
    problems = []
    for cls in order:
        eng = cls()
        try:
            eng.init()
            return eng, problems
        except Exception as e:
            problems.append({"engine": cls.name, "error": str(e)[:300], "hint": cls.hint})
    return None, problems


class Handler(BaseHTTPRequestHandler):
    server_version = "RetainerOcrDriver/0.1"
    engine = None
    problems = []
    startup_error = None

    def log_message(self, fmt, *args):
        sys.stderr.write("[driver] " + (fmt % args) + "\n")

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-File-Name")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            ready = self.engine is not None
            self._json(200, {
                "ok": True,
                "ready": ready,
                "engine": None if not ready else self.engine.name,
                "version": None if not ready else self.engine.version,
                "maxBytes": MAX_BYTES,
                "offline": True,
                "formats": sorted(docloader.SUPPORTED),
                "imageFormats": sorted(docloader.IMAGE_EXTS),
                "problems": self.problems,
                "startupError": self.startup_error,
            })
            return
        self._json(404, err("未知路径：" + path))

    def _filename(self):
        name = self.headers.get("X-File-Name")
        if name:
            try:
                from urllib.parse import unquote
                return unquote(name)
            except Exception:
                return name
        if "?" in self.path:
            for part in self.path.split("?", 1)[1].split("&"):
                if part.startswith("name="):
                    from urllib.parse import unquote
                    return unquote(part[5:])
        return "upload.bin"

    def do_POST(self):
        path = self.path.split("?")[0]
        if path != "/ocr":
            self._json(404, err("未知路径：" + path))
            return
        if self.engine is None:
            self._json(503, err("本机没有可用的 OCR 引擎，请查看 /health 的 problems 字段"))
            return
        started = time.time()
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json(400, err("Content-Length 无效"))
            return
        if length <= 0:
            self._json(400, err("请求体为空"))
            return
        if length > MAX_BYTES:
            self._json(413, err("文件超过 " + str(MAX_BYTES // 1048576) + " MB"))
            return
        data = self.rfile.read(length)
        name = self._filename()

        try:
            loaded = docloader.load_smart(data, name)
        except docloader.UnsupportedFormat as e:
            self._json(415, {
                "ok": False,
                "error": str(e),
                "format": None,
                "durationMs": int((time.time() - started) * 1000),
            })
            return
        except Exception as e:
            self._json(500, {
                "ok": False,
                "error": "解析文件失败：" + str(e)[:300],
                "detail": traceback.format_exc()[-800:],
                "durationMs": int((time.time() - started) * 1000),
            })
            return

        lines = []
        try:
            with OCR_LOCK:
                for label, png in loaded.images:
                    res = self.engine.recognize(png)
                    for ln in res.get("lines", []):
                        ln["source"] = label
                        lines.append(ln)
        except Exception as e:
            self._json(500, {
                "ok": False,
                "error": "识别失败：" + str(e)[:300],
                "detail": traceback.format_exc()[-800:],
                "durationMs": int((time.time() - started) * 1000),
            })
            return

        self._json(200, {
            "ok": True,
            "engine": self.engine.name,
            "filename": name,
            "format": loaded.format,
            "text": loaded.text,
            "textSource": "document" if loaded.text else "none",
            "usedOcr": len(loaded.images) > 0,
            "lines": lines,
            "pages": loaded.pages,
            "notes": loaded.notes,
            "durationMs": int((time.time() - started) * 1000),
        })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=17801)
    ap.add_argument("--engine", default=None, help="rapidocr / paddleocr")
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    print("正在加载 OCR 引擎…", flush=True)
    started = time.time()
    try:
        eng, problems = build_engine(args.engine)
    except Exception as e:
        eng, problems = None, [{"engine": args.engine, "error": str(e), "hint": ""}]
    Handler.engine = eng
    Handler.problems = problems
    if eng is None:
        Handler.startup_error = "没有可用引擎"
        print("警告：没有可用 OCR 引擎，/ocr 将返回 503。", flush=True)
        for p in problems:
            print("  - %s 失败：%s" % (p["engine"], p["error"]), flush=True)
            if p.get("hint"):
                print("    提示：%s" % p["hint"], flush=True)
    else:
        print("引擎就绪：%s %s（加载 %.1f 秒）" % (eng.name, eng.version, time.time() - started), flush=True)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print("驱动已启动：http://%s:%d   （仅本机可访问，Ctrl+C 停止）" % (args.host, args.port), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。", flush=True)


if __name__ == "__main__":
    main()
