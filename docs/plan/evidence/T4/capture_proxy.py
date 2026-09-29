"""T4 开发期抓包代理（只用于取证，不属于产品）。

监听 127.0.0.1:18765，把 /v1/chat/completions、/v1/models 转发到 .env.local 的 LAWFIRM_LLM_BASE，
并用 LAWFIRM_TEST_KEY_A 替换请求头里的 Key（DSH 侧只拿到占位 Key）。
每个 chat 请求只记录：model、工具名列表、chat_template_kwargs、reasoning_effort / enable_thinking、max_tokens。
不记录消息内容，不记录 Key。输出追加到 --out 指定的 JSONL。
"""
import argparse, json, pathlib, sys, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
from check_6000d import load_env  # noqa: E402

env = load_env()
BASE = env.get("LAWFIRM_LLM_BASE", "http://192.168.8.77:8000").rstrip("/")
KEY = env.get("LAWFIRM_TEST_KEY_A", "")
OUT = None


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _forward(self, body):
        if self.path not in ("/v1/chat/completions", "/v1/models"):
            self.send_response(404); self.end_headers(); return
        if body is not None and self.path == "/v1/chat/completions":
            try:
                j = json.loads(body)
                rec = {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "model": j.get("model"),
                    "tools": sorted(t.get("function", {}).get("name") for t in j.get("tools") or []),
                    "chat_template_kwargs": j.get("chat_template_kwargs"),
                    "reasoning_effort": j.get("reasoning_effort"),
                    "enable_thinking": j.get("enable_thinking"),
                    "max_tokens": j.get("max_tokens"),
                    "stream": j.get("stream"),
                }
                with open(OUT, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception as e:  # 记录失败不影响转发
                print("record error:", type(e).__name__, file=sys.stderr)
        headers = {"Authorization": f"Bearer {KEY}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(BASE + self.path, data=body, headers=headers,
                                     method="POST" if body is not None else "GET")
        try:
            r = urllib.request.urlopen(req, timeout=1200)
            status = r.status
        except urllib.error.HTTPError as e:
            r, status = e, e.code
        self.send_response(status)
        for k in ("Content-Type", "X-Queue-Wait-Ms"):
            if r.headers.get(k):
                self.send_header(k, r.headers[k])
        self.send_header("Connection", "close")
        self.end_headers()
        while True:
            chunk = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
            if not chunk:
                break
            self.wfile.write(chunk); self.wfile.flush()

    def do_GET(self):
        self._forward(None)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self._forward(self.rfile.read(n))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18765)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    OUT = a.out
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()
