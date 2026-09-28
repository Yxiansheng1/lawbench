"""在开发机上检查能否访问 395：远程桌面、SSH、预处理服务端口，以及服务起来后的 /health。
只用标准库。用法：python scripts/check_395_reach.py <395 的 IP>
（也可以把 PREP395_BASE=http://<IP>:9000 写进 .env.local，然后不带参数运行）
"""
import json, pathlib, socket, sys, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]


def env():
    d = {}
    p = ROOT / ".env.local"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def tcp(host, port, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return "通"
    except Exception as e:
        return f"不通（{type(e).__name__}）"


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else None
    if not host:
        base = env().get("PREP395_BASE", "")
        host = base.split("//")[-1].split(":")[0] if base and "<" not in base else None
    if not host:
        sys.exit("请给出 395 的 IP：python scripts/check_395_reach.py 192.168.x.x")
    print(f"395：{host}\n")
    for port, what in [(3389, "远程桌面"), (22, "SSH"), (9000, "预处理服务（未部署时不通是正常的）"),
                       (9101, "OCR 后端（应当不通，只监听本机）"), (9102, "9B 后端（应当不通，只监听本机）")]:
        print(f"{port:<6}{what:<30}{tcp(host, port)}")
    try:
        with urllib.request.urlopen(f"http://{host}:9000/health", timeout=5) as r:
            print("\n/health：", json.loads(r.read().decode("utf-8")))
    except Exception as e:
        print(f"\n/health：暂不可用（{type(e).__name__}）——预处理服务部署后再测")


if __name__ == "__main__":
    main()
