"""所外访问检查（T27 验收）：在律所外的网络上、已加入 lawbench 虚拟网的电脑上运行。

用法：python deploy\\easytier\\check_remote.py（约半分钟；不通的端口要等超时）
只做端口连通和一次 /v1/models 请求，不发送任何案卷内容，不需要 Key。
"""
import socket
import sys
import urllib.request

LLM = "10.126.126.1"     # 6000D 的虚拟 IP（所外只能用它）
PREP = "10.126.126.3"    # 395 的虚拟 IP
MUST_OPEN = [(LLM, 8000, "6000D 网关")]
OPEN_AFTER_T11 = [(PREP, 9000, "395 识别服务（T11 部署后才一定会通）")]
MUST_CLOSED = [
    (LLM, 22, "6000D SSH"), (LLM, 8001, "6000D 其他端口"), (LLM, 8002, "6000D 其他端口"), (LLM, 3000, "6000D 其他端口"),
    (PREP, 22, "395 SSH"), (PREP, 3389, "395 远程桌面"), (PREP, 445, "395 文件共享"), (PREP, 9101, "395 OCR 后端"),
    (PREP, 9102, "395 9B 后端"),
    ("192.168.8.77", 8000, "律所局域网地址（所外不应可达）"), ("192.168.8.124", 3389, "律所局域网地址（所外不应可达）"),
]


def reachable(host, port, timeout=2.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def local_ips():
    try:
        return {a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except OSError:
        return set()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ips = local_ips()
    if any(ip.startswith("192.168.8.") for ip in ips):
        print("[警告] 本机有 192.168.8.x 地址，像是在律所局域网内；所外检查请换到手机热点等外部网络再跑。")
    bad = 0
    for host, port, name in MUST_OPEN:
        ok = reachable(host, port)
        bad += not ok
        print(f"[{'通过' if ok else '失败'}] {name} {host}:{port} 应可连通 -> {'通' if ok else '不通'}")
    try:
        with urllib.request.urlopen(f"http://{LLM}:8000/v1/models", timeout=8) as r:
            ok = r.status == 200
    except Exception:
        ok = False
    bad += not ok
    print(f"[{'通过' if ok else '失败'}] 6000D /v1/models 返回 200 -> {'是' if ok else '否'}")
    for host, port, name in OPEN_AFTER_T11:
        ok = reachable(host, port)
        print(f"[{'通过' if ok else '待定'}] {name} {host}:{port} -> {'通' if ok else '不通'}")
    for host, port, name in MUST_CLOSED:
        ok = not reachable(host, port, timeout=2.0)
        bad += not ok
        print(f"[{'通过' if ok else '失败'}] {name} {host}:{port} 应不通 -> {'不通' if ok else '通了'}")
    print("\n结论：" + ("全部通过" if bad == 0 else f"{bad} 项未通过"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
