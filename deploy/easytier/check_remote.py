"""所外访问检查（T27 验收；README 第 4 节）：在律所外的网络上、已加入 lawbench 虚拟网的电脑上运行。

用法：python deploy\\easytier\\check_remote.py [--save docs\\plan\\evidence\\T27\\remote-check.txt]
（约半分钟；不通的端口要等超时）。只做端口连通、一次 6000D /v1/models 和一次 395 /health 请求，
不发送任何案卷内容，不需要 Key。--save 把同样的输出另存一份（UTF-8），可直接作为 T27 证据。

通过标准（README 第 4 节）：
- 6000D 虚拟 IP 10.126.126.1:8000 可连通，/v1/models 返回 200；
- 395 虚拟 IP 10.126.126.3:9000 可连通，/health 返回 200（T11 已部署，2026-10-02 起是必过项）；
- 两台虚拟 IP 上的 22、3389 及其他端口全部不通；
- 律所局域网地址 192.168.8.x 从所外不可达。
"""
import argparse
import datetime
import socket
import sys
import urllib.request

LLM = "10.126.126.1"     # 6000D 的虚拟 IP（所外只能用它）
PREP = "10.126.126.3"    # 395 的虚拟 IP
MUST_OPEN = [(LLM, 8000, "6000D 网关"), (PREP, 9000, "395 识别服务")]
MUST_HTTP_200 = [(f"http://{LLM}:8000/v1/models", "6000D /v1/models"), (f"http://{PREP}:9000/health", "395 /health")]
MUST_CLOSED = [
    (LLM, 22, "6000D SSH"), (LLM, 3389, "6000D 远程桌面"), (LLM, 8001, "6000D 其他端口"), (LLM, 8002, "6000D 其他端口"),
    (LLM, 3000, "6000D 其他端口"),
    (PREP, 22, "395 SSH"), (PREP, 3389, "395 远程桌面"), (PREP, 445, "395 文件共享"), (PREP, 9101, "395 OCR 后端"),
    (PREP, 9102, "395 9B 后端"),
    ("192.168.8.77", 8000, "律所局域网地址（所外不应可达）"), ("192.168.8.77", 22, "律所局域网地址（所外不应可达）"),
    ("192.168.8.124", 9000, "律所局域网地址（所外不应可达）"), ("192.168.8.124", 3389, "律所局域网地址（所外不应可达）"),
]


def reachable(host, port, timeout=2.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_200(url, timeout=8.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def local_ips():
    try:
        return {a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except OSError:
        return set()


def run() -> tuple[int, list[str]]:
    out: list[str] = []
    ips = local_ips()
    out.append(f"# 所外访问检查（T27）  {datetime.datetime.now().astimezone().isoformat(timespec='seconds')}")
    out.append(f"本机已加入虚拟网：{'是' if any(ip.startswith('10.126.126.') for ip in ips) else '否（未见 10.126.126.x 地址）'}；"
               f"本机在律所局域网：{'是——请换到手机热点等外部网络再跑' if any(ip.startswith('192.168.8.') for ip in ips) else '否'}")
    out.append("")
    bad = 0
    for host, port, name in MUST_OPEN:
        ok = reachable(host, port)
        bad += not ok
        out.append(f"[{'通过' if ok else '失败'}] {name} {host}:{port} 应可连通 -> {'通' if ok else '不通'}")
    for url, name in MUST_HTTP_200:
        ok = http_200(url)
        bad += not ok
        out.append(f"[{'通过' if ok else '失败'}] {name} 返回 200 -> {'是' if ok else '否'}")
    for host, port, name in MUST_CLOSED:
        ok = not reachable(host, port, timeout=2.0)
        bad += not ok
        out.append(f"[{'通过' if ok else '失败'}] {name} {host}:{port} 应不通 -> {'不通' if ok else '通了'}")
    out.append("")
    out.append("结论：" + ("全部通过" if bad == 0 else f"{bad} 项未通过"))
    return bad, out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="所外访问检查（T27）")
    ap.add_argument("--save", help="把输出另存到这个文件（UTF-8），如 docs\\plan\\evidence\\T27\\remote-check.txt")
    args = ap.parse_args()
    bad, out = run()
    print("\n".join(out))
    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
