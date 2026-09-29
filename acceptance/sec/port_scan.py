"""SEC-13（上线必过第 6 项后半"局域网不能绕过网关"）：两台服务器只开放应开放的端口。

python acceptance\\sec\\port_scan.py [--target 所内|所外|全部]

对 6000D、395 的所内、所外地址逐个尝试 TCP 连接一组常见端口（含模型直连端口）：
6000D 只应开放 8000（网关）；395 只应开放 9000（预处理服务），9101 / 9102（本机推理后端）必须连不上。
22（SSH）、3389（远程桌面）是运维端口，列为"注意"，不判不通过（是否保留由甲方决定，Spec 6.1）。
在律所局域网内跑一次、在所外（EasyTier）跑一次；所外只应看到 8000 和 9000。
只连律所自己的两台服务器。
"""
from __future__ import annotations

import argparse
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FAIL, PASS, SERVERS, UNMET, Report  # noqa: E402

PORTS = [21, 22, 23, 80, 111, 135, 139, 443, 445, 1433, 2375, 3000, 3306, 3389, 5000, 5432, 5900, 6006, 6379,
         7860, 8000, 8001, 8002, 8003, 8008, 8080, 8081, 8443, 8888, 9000, 9090, 9101, 9102, 11434, 11010,
         11011, 11012, 18765, 30000]
EXPECTED = {"6000D": {8000}, "395": {9000}}
ADMIN = {22, 3389}


def is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.8):
            return True
    except OSError:
        return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["所内", "所外", "全部"], default="全部")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    r = Report("port_scan", "SEC-13；上线必过第 6 项（局域网不能绕过网关）", a.out)
    idx = {"所内": [0], "所外": [1], "全部": [0, 1]}[a.target]
    bad, notes, any_up = [], [], False
    for name, bases in SERVERS.items():
        for i in idx:
            host = urlsplit(bases[i]).hostname
            label = f"{name}（{'所内' if i == 0 else '所外'} {host}）"
            with ThreadPoolExecutor(16) as ex:
                res = dict(zip(PORTS, ex.map(lambda p: is_open(host, p), PORTS)))
            opened = sorted(p for p, ok in res.items() if ok)
            if not opened:
                r.log(f"{label}：连不上（不在该网络内或主机未开）")
                continue
            any_up = True
            r.log(f"{label}：开放端口 {opened}")
            for p in opened:
                if p in EXPECTED[name]:
                    continue
                if p in ADMIN:
                    notes.append(f"{label} {p}")
                else:
                    bad.append(f"{label} {p}")
            for p in EXPECTED[name]:
                if not res[p]:
                    r.log(f"  注意：应开放的 {p} 连不上")
    for n in notes:
        r.log(f"  注意（运维端口，是否保留由甲方决定）：{n}")
    if not any_up:
        r.finish(UNMET, "两台服务器都连不上，需在律所局域网或 EasyTier 虚拟网内运行")
    if bad:
        r.finish(FAIL, "不应开放的端口：" + "、".join(bad))
    r.finish(PASS, "除网关 8000、预处理 9000（及运维端口）外没有开放端口")


if __name__ == "__main__":
    main()
