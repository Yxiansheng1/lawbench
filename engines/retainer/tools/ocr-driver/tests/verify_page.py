# -*- coding: utf-8 -*-
"""
无头浏览器验证工具

用 Chrome 无头模式打开工作台页面，读取页面自检写入的 <title>，
避免经 PowerShell 管道导致的中文编码损坏。

用法
  python verify_page.py                 # 默认验证 #scantest
  python verify_page.py --hash uitest
  python verify_page.py --hash ""       # 只取页面标题，不触发自检
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER_DIR = os.path.dirname(HERE)
PKG_ROOT = os.path.dirname(os.path.dirname(DRIVER_DIR))
PAGE = os.path.join(PKG_ROOT, "启动.html")

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_browser():
    for p in CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    raise RuntimeError("未找到 Chrome 或 Edge")


def page_url(hash_value):
    url = "file:///" + PAGE.replace("\\", "/")
    if hash_value:
        url += "#" + hash_value
    return url


def dump(url, budget_ms=30000):
    browser = find_browser()
    with tempfile.TemporaryDirectory(prefix="verify-page-") as profile:
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--user-data-dir=" + profile,
            "--virtual-time-budget=%d" % budget_ms,
            "--dump-dom",
            url,
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=180)
    return proc.stdout.decode("utf-8", "ignore")


def grab(dom, pattern):
    m = re.search(pattern, dom, re.S)
    return m.group(1).strip() if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hash", default="scantest")
    ap.add_argument("--budget", type=int, default=30000)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    url = page_url(args.hash)
    dom = dump(url, args.budget)
    title = grab(dom, r"<title>(.*?)</title>")
    state = grab(dom, r'id="scanState"[^>]*>(.*?)</div>')
    summary = grab(dom, r'id="choiceSummary"[^>]*>(.*?)</div>')
    choices = len(re.findall(r'<input type="checkbox" value="[^"]*\.docx"', dom))

    lines = ["URL: " + url, "domChars: %d" % len(dom),
             "模板选项数(渲染出的复选框): %d" % choices, "", "TITLE:", title or "(空)", ""]
    if summary:
        lines += ["模板组摘要:", summary, ""]
    if state:
        lines += ["SCAN STATE:", state, ""]
    text = "\n".join(lines)

    out = args.out or os.path.join(HERE, "_verify_result.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(text.encode(sys.stdout.encoding or "utf-8", "replace").decode(sys.stdout.encoding or "utf-8", "replace"))


if __name__ == "__main__":
    main()
