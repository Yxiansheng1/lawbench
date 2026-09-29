"""上线必过第 24、25 项配套：律所引擎里自带的联网代码清单（Spec 13.3、14.3）。

python acceptance\\sec\\engine_net_inventory.py
静态扫描 engines\\ 下的 .py / .js / .html，列出用到联网接口的文件（imaplib、smtplib、urllib.request、
http.client、requests、socket、fetch、XMLHttpRequest、WebSocket……），与 acceptance\\sec\\engine_net_known.json
的"已知、无调用入口"清单比对：
- 出现清单外的新联网文件 → 不通过（引擎被改过或升级了，需主编排复核）；
- 工作台服务的发票调用代码（service\\…\\invoice\\runner.py）存在时，核对它不引用清单里的模块；
  还不存在（T25 之前）时结论为"前提不满足"。
这份清单由抓包结果佐证：发票、委托材料全过程只见两台服务器和本机（net_watch.ps1、manual\\抓包.md）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FAIL, PASS, REPO, UNMET, Report  # noqa: E402

NET_MODULES = {"imaplib", "smtplib", "poplib", "ftplib", "telnetlib", "urllib.request", "urllib3", "http.client",
               "requests", "httpx", "aiohttp", "socket", "ssl", "webbrowser"}
IMPORT_RE = re.compile(r"^\s*(?:import\s+([\w.,\s]+?)\s*(?:#.*)?$|from\s+([\w.]+)\s+import\b)", re.M)


def py_net(text: str) -> list[str]:
    """import a,b,c 与 from x import y 两种写法里用到的联网模块。"""
    mods = set()
    for m in IMPORT_RE.finditer(text):
        names = m.group(1).split(",") if m.group(1) else [m.group(2)]
        for n in names:
            n = n.strip().split(" as ")[0].strip()
            if n in NET_MODULES:
                mods.add(n)
    return sorted(mods)


PATTERNS = {
    ".js": re.compile(r"\b(fetch\s*\(|XMLHttpRequest|WebSocket\s*\(|navigator\.sendBeacon|EventSource\s*\()"),
    ".html": re.compile(r"\b(fetch\s*\(|XMLHttpRequest|WebSocket\s*\(|navigator\.sendBeacon|EventSource\s*\()"),
}
KNOWN_FILE = Path(__file__).with_name("engine_net_known.json")


def inventory() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for p in sorted((REPO / "engines").rglob("*")):
        if not p.is_file() or "vendor" in p.parts or "__pycache__" in p.parts:
            continue
        suffix = p.suffix.lower()
        if suffix != ".py" and suffix not in PATTERNS:
            continue
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if suffix == ".py":
            found = py_net(t)
        else:
            found = sorted({m.group(1).strip("( ") for m in PATTERNS[suffix].finditer(t)})
        if found:
            out[p.relative_to(REPO).as_posix()] = found
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-known", action="store_true", help="用当前扫描结果重写已知清单（需主编排同意）")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    r = Report("engine_net_inventory", "Spec 13.3、14.3；上线必过第 24、25 项", a.out)
    inv = inventory()
    for f, apis in inv.items():
        r.log(f"  {f}：{', '.join(apis)}")
    if a.write_known:
        KNOWN_FILE.write_text(json.dumps({"说明": "律所引擎自带的联网代码；工作台只开放 Spec 13.3 的白名单动作，"
                                                 "这些文件没有调用入口", "files": inv},
                                         ensure_ascii=False, indent=1), encoding="utf-8")
        r.log(f"已写入 {KNOWN_FILE.name}")
    known = json.loads(KNOWN_FILE.read_text(encoding="utf-8"))["files"] if KNOWN_FILE.exists() else {}
    new = [f for f in inv if f not in known]
    changed = [f for f in inv if f in known and set(inv[f]) - set(known[f])]
    if new or changed:
        r.finish(FAIL, "清单外的联网代码：" + "、".join(new + changed))
    runners = list(REPO.glob("service/**/invoice/runner.py"))
    if not runners:
        r.finish(UNMET, f"联网代码与已知清单一致（{len(inv)} 个文件）；发票调用代码（T25）还没有，调用入口待核")
    mods = {Path(f).stem for f in inv}
    refs = [m for m in mods for rp in runners if re.search(rf"\b{re.escape(m)}\b", rp.read_text(encoding="utf-8"))]
    if refs:
        r.finish(FAIL, "发票调用代码引用了联网模块：" + "、".join(sorted(set(refs))))
    r.finish(PASS, f"联网代码与已知清单一致（{len(inv)} 个文件），工作台的发票调用代码不引用它们")


if __name__ == "__main__":
    main()
