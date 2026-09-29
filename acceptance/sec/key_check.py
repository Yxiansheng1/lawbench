"""SEC-06（上线必过第 6 项前半）：无 Key、错误 Key、停用 Key 都不能用 6000D 和 395。

python acceptance\\sec\\key_check.py [--revoked-key-env LAWFIRM_REVOKED_KEY]

- 6000D：POST /v1/chat/completions（max_tokens 1、关闭思考），无 Key、错误 Key 应返回 401 / 403；
  无 Key 也返回 200 说明甲方还没开启 require_key（Spec 6.3），结论为"前提不满足"。
- 停用 Key：由管理员在网关 /admin 停用一个测试 Key，放进环境变量（缺省 LAWFIRM_REVOKED_KEY）后运行；
  没有提供时结论为"前提不满足"。395 按 Spec 6.3 最迟 30 秒内拒绝，本脚本等 35 秒后再测 395。
- 395：POST /v1/ocr/page（一张 8×8 的白图）同样测无 Key、错误 Key、停用 Key，应返回 401。
Key 不打印，证据里只写"无 / 错误 / 停用"。
"""
from __future__ import annotations

import argparse
import sys
import time
import zlib
import struct
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FAIL, PASS, SERVERS, UNMET, Report, env_local, http  # noqa: E402

WRONG = "sk-lbfx-invalid-000000"


def tiny_png() -> bytes:
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\xff" * 24 for _ in range(8))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def first_up(bases, path):
    for b in bases:
        st, _, _ = http("GET", b + path, timeout=2)
        if st is not None:
            return b
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--revoked-key-env", default="LAWFIRM_REVOKED_KEY")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    r = Report("key_check", "SEC-06；上线必过第 6 项", a.out)
    env = env_local()
    revoked = env.get(a.revoked_key_env)
    cases = [("无 Key", None), ("错误 Key", WRONG)] + ([("停用 Key", revoked)] if revoked else [])

    llm = first_up(SERVERS["6000D"], "/v1/models")
    prep = first_up(SERVERS["395"], "/health")
    r.log(f"6000D：{'连通 ' + llm if llm else '连不上'}；395：{'连通 ' + prep if prep else '连不上'}")
    if not llm and not prep:
        r.finish(UNMET, "两台服务器都连不上（需在律所局域网或 EasyTier 虚拟网内运行）")

    accepted, require_key_off = [], False
    if llm:
        body = {"model": "qwen38-27b", "messages": [{"role": "user", "content": "1"}], "max_tokens": 1,
                "stream": False, "chat_template_kwargs": {"enable_thinking": False}}
        for label, key in cases:
            h = {"Authorization": f"Bearer {key}"} if key else {}
            st, _, _ = http("POST", llm + "/v1/chat/completions", body, h, timeout=60)
            r.log(f"  6000D {label}：HTTP {st}")
            if st == 200:
                accepted.append(f"6000D {label}")
                if label == "无 Key":
                    require_key_off = True
    if prep:
        if revoked:
            r.log("  等 35 秒，让 395 的 Key 缓存（30 秒）过期……")
            time.sleep(35)
        for label, key in cases:
            h = {"Authorization": f"Bearer {key}"} if key else {}
            st, _, b = http("POST", prep + "/v1/ocr/page", headers=h, raw=tiny_png(), ctype="image/png", timeout=60)
            r.log(f"  395 {label}：HTTP {st} {b[:80].decode('utf-8', 'replace') if st and st != 200 else ''}")
            if st == 200:
                accepted.append(f"395 {label}")
    if require_key_off:
        r.finish(UNMET, "6000D 不带 Key 也返回 200：甲方尚未开启 require_key（Spec 6.3），开启后重测")
    if accepted:
        r.finish(FAIL, "以下请求没有被拒绝：" + "、".join(accepted))
    if not revoked:
        r.finish(UNMET, f"无 Key、错误 Key 已被拒绝；停用 Key 未测：请管理员停用一个测试 Key 并放进环境变量 {a.revoked_key_env}")
    if not (llm and prep):
        r.finish(UNMET, "有一台服务器连不上，没有测全")
    r.finish(PASS, "无 Key、错误 Key、停用 Key 在两台服务器上都被拒绝")


if __name__ == "__main__":
    main()
