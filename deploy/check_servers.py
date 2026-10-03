"""两台服务器一键检查（停电、重启、改 IP 之后跑；开发机或任何已入网的电脑都行）。

用法：python deploy\\check_servers.py [--save <文件>]
只做端口连通、395 /health 与 6000D /v1/models 各一次请求，不需要 Key，不发任何案卷内容；HTTP 不走系统代理
（scripts\\check_6000d.py 走系统代理，10-03 中午曾把"连不上"显示成代理返回的 502）。

查四个地址（所内 = 律所局域网，所外 = EasyTier 虚拟网）：
- 395 所内 192.168.8.124:9000、所外 10.126.126.3:9000：端口通、/health 200、status ok、契约版本等于 contracts\\VERSION；
  所内 /health 能到即视为 395 仍在 .124（停电后 DHCP 曾把它换成 .32）；
- 6000D 所内 192.168.8.77:8000、所外 10.126.126.1:8000：端口通、/v1/models 200。
本机不在律所局域网时所内两项记"不适用"，没加入虚拟网时所外两项记"不适用"，都不算不通过。
退出码：0 全部通过（不适用的除外）；1 有不通过。
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy" / "easytier"))
from check_remote import local_ips, reachable  # noqa: E402  端口连通与本机地址沿用所外检查的写法

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # 不走系统代理
CONTRACT = (ROOT / "contracts" / "VERSION").read_text(encoding="utf-8").strip()
TARGETS = [  # (名称, 主机, 端口, 路径, 所内/所外)
    ("395 所内", "192.168.8.124", 9000, "/health", "lan"),
    ("395 所外", "10.126.126.3", 9000, "/health", "vnet"),
    ("6000D 所内", "192.168.8.77", 8000, "/v1/models", "lan"),
    ("6000D 所外", "10.126.126.1", 8000, "/v1/models", "vnet"),
]


def get_json(url: str, timeout: float = 8.0) -> tuple[int | None, dict | None, str]:
    try:
        with OPENER.open(url, timeout=timeout) as r:
            body = r.read()
            try:
                return r.status, json.loads(body), ""
            except ValueError:
                return r.status, None, "返回的不是 JSON"
    except urllib.error.HTTPError as e:
        return e.code, None, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001 连不上、超时
        return None, None, type(e).__name__


def check(name: str, host: str, port: int, path: str) -> tuple[bool, str]:
    if not reachable(host, port, timeout=3.0):
        return False, f"{host}:{port} 端口不通"
    st, body, err = get_json(f"http://{host}:{port}{path}")
    if st != 200:
        return False, f"{path} {err or st}"
    if path == "/health":
        bad = [k for k in ("status", "ocr", "llm9b") if (body or {}).get(k) != "ok"]
        ver = (body or {}).get("contract_version")
        if bad:
            return False, f"/health 有项不是 ok：{', '.join(bad)}"
        if ver != CONTRACT:
            return False, f"契约版本 {ver}，仓库是 {CONTRACT}"
        extra = "；仍在 192.168.8.124" if host.startswith("192.168.") else ""
        return True, f"/health ok，契约 {ver}，排队 {body.get('queue')}{extra}"
    n = len((body or {}).get("data", []))
    return True, f"/v1/models 200，{n} 个模型"


def run() -> tuple[int, list[str]]:
    ips = local_ips()
    on_lan = any(ip.startswith("192.168.8.") for ip in ips)
    on_vnet = any(ip.startswith("10.126.126.") for ip in ips)
    out = [f"# 服务器检查  {datetime.datetime.now().astimezone().isoformat(timespec='seconds')}",
           f"本机在律所局域网：{'是' if on_lan else '否'}；本机已加入虚拟网：{'是' if on_vnet else '否'}；仓库契约版本 {CONTRACT}",
           "", "| 项 | 结果 | 说明 |", "|---|---|---|"]
    bad = 0
    for name, host, port, path, where in TARGETS:
        if (where == "lan" and not on_lan) or (where == "vnet" and not on_vnet):
            out.append(f"| {name} {host}:{port} | 不适用 | 本机不在{'律所局域网' if where == 'lan' else '虚拟网'} |")
            continue
        ok, why = check(name, host, port, path)
        bad += not ok
        out.append(f"| {name} {host}:{port} | {'通过' if ok else '不通过'} | {why} |")
    if any(r.startswith("| 395 所内") and "端口不通" in r for r in out):          # 只在连不上时提示换址
        out.append("")
        out.append("395 所内不通：先看它是不是又被 DHCP 换了地址（在 395 上 `Get-NetIPConfiguration`），"
                   "按 deploy\\操作单-服务器固定IP.md 处理；所外（10.126.126.3）若通，可经虚拟网远程查看。")
    out += ["", "结论：" + ("全部通过" if bad == 0 else f"{bad} 项不通过")]
    return bad, out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="两台服务器一键检查")
    ap.add_argument("--save", help="另存输出（UTF-8）")
    a = ap.parse_args()
    bad, out = run()
    print("\n".join(out))
    if a.save:
        pathlib.Path(a.save).write_text("\n".join(out) + "\n", encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
