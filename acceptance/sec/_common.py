"""保密验收脚本的共用部分：三种结论、证据文件、只连白名单地址的 HTTP 调用。

每个脚本最后调用 finish()：打印"结论：通过 / 不通过 / 前提不满足"，把全部输出写进证据文件，
退出码 0 = 通过，1 = 不通过，2 = 前提不满足。证据里不写 Key、密码、案卷正文（只写特征字符串和文件路径）。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures"
PASS, FAIL, UNMET = "通过", "不通过", "前提不满足"
EXIT = {PASS: 0, FAIL: 1, UNMET: 2}

# 产品只允许连的地址（CLAUDE.md、Spec 14.3、15）
SERVERS = {
    "6000D": ["http://192.168.8.77:8000", "http://10.126.126.1:8000"],
    "395": ["http://192.168.8.124:9000", "http://10.126.126.3:9000"],
}
ALLOWED_IPS = {"192.168.8.77", "10.126.126.1", "192.168.8.124", "10.126.126.3", "127.0.0.1", "::1"}

FEATURES = {
    "criminal-01": "LBFX-CRIM01-7Q3Z", "civil-01": "LBFX-CIVL01-K8M2", "contract-01": "LBFX-CONT01-R5T9",
    "attack-01": "LBFX-ATTK01-W2N6", "broken": "LBFX-BRKN00-J4H7", "closed-01": "LBFX-CLSD01-P6V3",
    "tender-01": "LBFX-TNDR01-X9C4", "invoices-01": "LBFX-INVC01-D3F8",
}


class Report:
    def __init__(self, name: str, item: str, out_dir: Path | None = None) -> None:
        self.name = name
        self.item = item
        self.lines: list[str] = []
        self.out_dir = Path(out_dir or os.environ.get("LB_ACCEPT_OUT") or REPO / "acceptance" / "_out")
        self.log(f"# {name}　对应：{item}")
        self.log(f"# 运行时间：{datetime.now().astimezone().isoformat(timespec='seconds')}")

    def log(self, s: str = "") -> None:
        print(s, flush=True)
        self.lines.append(s)

    def finish(self, verdict: str, why: str) -> None:
        self.log("")
        self.log(f"结论：{verdict}（{why}）")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        p = self.out_dir / f"{self.name}-{stamp}.txt"
        p.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        print(f"证据文件：{p}")
        sys.exit(EXIT[verdict])


def env_local() -> dict[str, str]:
    """读仓库根的 .env.local（不打印任何值）。环境变量优先。"""
    out: dict[str, str] = {}
    p = REPO / ".env.local"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    out.update({k: v for k, v in os.environ.items() if k.startswith(("LAWFIRM_", "LB_", "PREP395_"))})
    return out


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 不走系统代理


def http(method: str, url: str, body=None, headers: dict | None = None, timeout: float = 10.0,
         raw: bytes | None = None, ctype: str | None = None):
    """返回 (状态码, 响应头, 响应体字节)；连不上返回 (None, {}, 异常类名)。不跟随重定向由调用方判断 3xx。"""
    data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
    h = dict(headers or {})
    if data is not None:
        h.setdefault("Content-Type", ctype or "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with _opener.open(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()
    except (urllib.error.URLError, OSError) as e:
        return None, {}, type(e).__name__.encode()


def reachable(base: str, path: str) -> bool:
    st, _, _ = http("GET", base + path, timeout=2)
    return st is not None


def service() -> tuple[str, str] | None:
    """工作台服务地址和令牌（LB_URL，如 http://127.0.0.1:18811；LB_TOKEN）；没有或连不上返回 None。"""
    e = env_local()
    url, token = e.get("LB_URL"), e.get("LB_TOKEN")
    if not url or not token or not reachable(url, "/health"):
        return None
    return url.rstrip("/"), token
