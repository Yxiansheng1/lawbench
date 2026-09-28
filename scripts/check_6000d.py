"""检查 6000D 网关：连通性、Key 校验是否开启、两个测试 Key 能否使用。
只用标准库。Key 从 D:\\lawbench\\.env.local 读取，不在输出中打印 Key。
用法：python scripts/check_6000d.py [--base http://192.168.8.77:8000]
"""
import argparse, json, pathlib, time, urllib.request, urllib.error

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_env():
    env = {}
    p = ROOT / ".env.local"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def call(method, url, key=None, body=None, timeout=60):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace"), time.time() - t
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace"), time.time() - t
    except Exception as e:  # 连不上、超时
        return None, {}, f"{type(e).__name__}: {e}", time.time() - t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=None)
    a = ap.parse_args()
    env = load_env()
    base = (a.base or env.get("LAWFIRM_LLM_BASE") or "http://192.168.8.77:8000").rstrip("/")
    ka, kb = env.get("LAWFIRM_TEST_KEY_A"), env.get("LAWFIRM_TEST_KEY_B")
    print(f"网关：{base}；Key A {'已配置' if ka else '未配置'}，Key B {'已配置' if kb else '未配置'}\n")

    chat = {"model": "qwen38-27b", "messages": [{"role": "user", "content": "只回复两个字：收到"}],
            "max_tokens": 16, "temperature": 0, "stream": False,
            "chat_template_kwargs": {"enable_thinking": False}}
    rows = []
    for name, method, path, key, body in [
        ("health", "GET", "/health", None, None),
        ("models 无 Key", "GET", "/v1/models", None, None),
        ("models 错误 Key", "GET", "/v1/models", "sk-invalid-000", None),
        ("models Key A", "GET", "/v1/models", ka, None),
        ("chat 无 Key", "POST", "/v1/chat/completions", None, chat),
        ("chat 错误 Key", "POST", "/v1/chat/completions", "sk-invalid-000", chat),
        ("chat Key A", "POST", "/v1/chat/completions", ka, chat),
        ("chat Key B", "POST", "/v1/chat/completions", kb, chat),
    ]:
        if name.endswith(("Key A", "Key B")) and not key:
            rows.append((name, "跳过（未配置）", "", "")); continue
        st, hd, txt, dt = call(method, base + path, key, body)
        note = ""
        if path.endswith("completions") and st == 200:
            try:
                note = "回答：" + json.loads(txt)["choices"][0]["message"]["content"].strip()[:20]
            except Exception:
                note = txt[:60]
        elif st != 200:
            note = txt[:80].replace("\n", " ")
        rows.append((name, st, f"{dt:.2f}s", (f"排队 {hd.get('X-Queue-Wait-Ms')}ms " if hd.get("X-Queue-Wait-Ms") else "") + note))
    for r in rows:
        print(f"{r[0]:<16} 状态 {str(r[1]):<14} {r[2]:<7} {r[3]}")

    d = {r[0]: r[1] for r in rows}
    print("\n结论：")
    if d.get("chat 无 Key") is None:
        print("- 连不上网关：检查是否在律所局域网、地址和端口是否正确。")
        return
    print("- Key 校验：" + ("已开启（无 Key 被拒绝）" if d.get("chat 无 Key") in (401, 403) else "未开启（无 Key 也能调用），需要甲方在网关打开 require_key"))
    print("- /v1/models 是否校验 Key：" + ("是" if d.get("models 无 Key") in (401, 403) else "否（Spec 6.3 的 395 校验方式要改用 max_tokens=1 的请求）"))
    for k in ("chat Key A", "chat Key B"):
        print(f"- {k}：" + ("可用" if d.get(k) == 200 else f"不可用（{d.get(k)}）"))


if __name__ == "__main__":
    main()
