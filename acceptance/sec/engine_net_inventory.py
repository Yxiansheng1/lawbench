"""上线必过第 24、25 项配套：律所引擎里自带的联网代码清单与调用入口（Spec 13.3、13.5、14.3）。

python acceptance\\sec\\engine_net_inventory.py
1. 静态扫描 engines\\ 下的 .py / .js / .html，列出用到联网接口的文件（imaplib、smtplib、urllib.request、
   http.client、http.server、requests、socket、fetch、XMLHttpRequest、WebSocket……），与
   acceptance\\sec\\engine_net_known.json 的 files 清单比对：清单外的新联网文件 → 不通过（引擎被改过或升级了）。
2. 从工作台实际调用的入口出发（发票：service\\lawbench\\invoice\\runner.py 的 invoke.py 与白名单脚本；
   委托材料：retainer\\driver.py 起的 ocr-driver\\driver.py、启动.html 加载的 app\\*.js），沿 import 找出入口能
   加载到的联网文件，与清单里的"入口可达"比对：新可达的 → 不通过；清单登记了可达的，逐个核它的护栏：
   - flags：联网函数只在某些参数下才调；核 runner 的白名单真的拒绝这些参数和子命令（调 runner.assert_allowed）；
   - loopback：只连本机；核文件里的地址常量是 127.0.0.1，fetch 都用这个常量；工作台起驱动时传 --host 127.0.0.1。
3. 发票 / 委托材料调用代码（T25）还不存在时结论为"前提不满足"。
这份清单由抓包佐证：发票、委托材料全过程只见两台服务器和本机（net_watch.ps1、manual\\抓包.md）。
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FAIL, PASS, REPO, UNMET, Report  # noqa: E402

NET_MODULES = {"imaplib", "smtplib", "poplib", "ftplib", "telnetlib", "urllib.request", "urllib3", "http.client",
               "http.server", "socketserver", "requests", "httpx", "aiohttp", "socket", "ssl", "webbrowser"}
IMPORT_RE = re.compile(r"^\s*(?:import\s+([\w.,\s]+?)\s*(?:#.*)?$|from\s+([\w.]+)\s+import\b)", re.M)
JS_NET = re.compile(r"\b(fetch\s*\(|XMLHttpRequest|WebSocket\s*\(|navigator\.sendBeacon|EventSource\s*\()")
PATTERNS = {".js": JS_NET, ".html": JS_NET}
KNOWN_FILE = Path(__file__).with_name("engine_net_known.json")
RUNNER = REPO / "service" / "lawbench" / "invoice" / "runner.py"
RETAINER = REPO / "service" / "lawbench" / "retainer" / "driver.py"
INVOICE_DIR = REPO / "engines" / "invoice-ledger" / "scripts"
RETAINER_DIR = REPO / "engines" / "retainer"


def imported(text: str) -> set[str]:
    """import a,b,c 与 from x import y 两种写法里出现的模块名（含函数体里的延迟 import）。"""
    mods = set()
    for m in IMPORT_RE.finditer(text):
        names = m.group(1).split(",") if m.group(1) else [m.group(2)]
        for n in names:
            mods.add(n.strip().split(" as ")[0].strip())
    return mods


def py_net(text: str) -> list[str]:
    return sorted(m for m in imported(text) if m in NET_MODULES)


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
        found = py_net(t) if suffix == ".py" else sorted({m.group(1).strip("( ") for m in PATTERNS[suffix].finditer(t)})
        if found:
            out[p.relative_to(REPO).as_posix()] = found
    return out


def rel(p: Path) -> str:
    return p.relative_to(REPO).as_posix()


def py_closure(entries: list[Path]) -> dict[str, str]:
    """入口沿 import 能加载到的同目录 .py：文件 → 第一次从哪个文件加载到。只跟同目录（引擎脚本都平铺在一个目录里）。"""
    seen: dict[str, str] = {}
    todo = [(e, "入口") for e in entries if e.is_file()]
    while todo:
        p, via = todo.pop()
        if rel(p) in seen:
            continue
        seen[rel(p)] = via
        for m in imported(p.read_text(encoding="utf-8", errors="replace")):
            q = p.parent / (m.split(".")[0] + ".py")
            if q.is_file() and rel(q) not in seen:
                todo.append((q, rel(p)))
    return seen


def const(path: Path, name: str):
    """取模块级常量（runner.SCRIPTS 等），不 import 产品代码也能读。"""
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return ast.literal_eval(node.value)
                if isinstance(t, ast.Tuple) and name in [e.id for e in t.elts if isinstance(e, ast.Name)]:
                    vals = ast.literal_eval(node.value)
                    return vals[[e.id for e in t.elts].index(name)]
    return None


def reachable() -> dict[str, str]:
    """工作台调用入口能加载到的文件 → 来路。"""
    out: dict[str, str] = {}
    scripts = const(RUNNER, "SCRIPTS") or ()
    out.update(py_closure([INVOICE_DIR / "invoke.py"] + [INVOICE_DIR / s for s in scripts]))
    drv = RETAINER_DIR / "tools" / "ocr-driver" / "driver.py"
    out.update(py_closure([drv]))
    html = RETAINER_DIR / "启动.html"
    if html.is_file():
        for src in re.findall(r'<script[^>]*\bsrc="([^"]+)"', html.read_text(encoding="utf-8", errors="replace")):
            p = RETAINER_DIR / src
            if p.is_file() and "vendor" not in p.parts:
                out[rel(p)] = "启动.html"
    return out


def check_flags(spec: dict) -> list[str]:
    """flags 护栏：runner.assert_allowed 必须拒绝登记的参数和子命令。"""
    sys.path.insert(0, str(REPO / "service"))
    try:
        from lawbench.invoice import runner  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        return [f"导入 runner 失败：{type(e).__name__}"]
    bad = []
    for flag in spec.get("禁止参数", []):
        for argv in (["workflow.py", "run", "--job", "j", "--batch=b", "--ledger", "l", "--src", "s", flag],
                     ["workflow.py", "plan", "--job", "j", flag, "x"]):
            try:
                runner.assert_allowed(argv)
                bad.append(f"assert_allowed 放行了 {flag}")
                break
            except Exception:  # noqa: BLE001 拒绝即对
                pass
    for sub in spec.get("禁止子命令", []):
        try:
            runner.assert_allowed(["workflow.py", sub, "--job", "j"])
            bad.append(f"assert_allowed 放行了子命令 {sub}")
        except Exception:  # noqa: BLE001
            pass
    return bad


def check_loopback(path: Path, spec: dict) -> list[str]:
    """loopback 护栏：地址常量是 127.0.0.1，fetch 都以它开头；驱动由工作台以 --host 127.0.0.1 启动。"""
    t = path.read_text(encoding="utf-8", errors="replace")
    bad = []
    name = spec.get("地址常量")
    if name:
        m = re.search(rf"\b{re.escape(name)}\s*=\s*['\"]([^'\"]+)['\"]", t)
        if not m or not re.match(r"https?://127\.0\.0\.1(:\d+)?/?$", m.group(1)):
            bad.append(f"{name} 不是 127.0.0.1：{m.group(1) if m else '没找到'}")
        for call in re.findall(r"fetch\s*\(\s*([^,)]+)", t):
            if not call.strip().startswith(name):
                bad.append(f"fetch 没用 {name}：{call.strip()[:40]}")
    if spec.get("工作台传入 host"):
        if const(RETAINER, "HOST") != "127.0.0.1" or '"--host", HOST' not in RETAINER.read_text(encoding="utf-8"):
            bad.append("工作台起驱动时没有传 --host 127.0.0.1")
    return bad


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-known", action="store_true", help="用当前扫描结果重写 files 清单（需主编排同意）")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    r = Report("engine_net_inventory", "Spec 13.3、13.5、14.3；上线必过第 24、25 项", a.out)
    inv = inventory()
    r.log("## 引擎里的联网代码")
    for f, apis in inv.items():
        r.log(f"  {f}：{', '.join(apis)}")
    known_all = json.loads(KNOWN_FILE.read_text(encoding="utf-8")) if KNOWN_FILE.exists() else {}
    if a.write_known:
        known_all["files"] = inv
        KNOWN_FILE.write_text(json.dumps(known_all, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        r.log(f"已写入 {KNOWN_FILE.name}")
    known = known_all.get("files", {})
    new = [f for f in inv if f not in known]
    changed = [f for f in inv if f in known and set(inv[f]) - set(known[f])]
    if new or changed:
        r.finish(FAIL, "清单外的联网代码：" + "、".join(new + changed))
    if not RUNNER.exists() or not RETAINER.exists():
        r.finish(UNMET, f"联网代码与已知清单一致（{len(inv)} 个文件）；发票 / 委托材料调用代码（T25）还没有，调用入口待核")

    reach = reachable()
    hits = {f: reach[f] for f in inv if f in reach}
    allowed = known_all.get("入口可达", {})
    r.log("## 工作台调用入口能加载到的联网文件")
    problems = []
    for f, via in hits.items():
        spec = allowed.get(f)
        if spec is None:
            r.log(f"  {f}（经 {via}）← 清单没登记为可达")
            problems.append(f"{f} 新可达")
            continue
        bad = check_flags(spec) if spec.get("护栏") == "flags" else check_loopback(REPO / f, spec)
        r.log(f"  {f}（经 {via}）护栏 {spec.get('护栏')}：{'成立' if not bad else '；'.join(bad)}")
        r.log(f"    登记说明：{spec.get('说明', '')}")
        problems += [f"{f}：{b}" for b in bad]
    for f in allowed:
        if f not in hits:
            r.log(f"  （只记）清单登记为可达、现在入口加载不到：{f}")
    for f in inv:
        if f not in hits:
            r.log(f"  无调用入口：{f}")
    if problems:
        r.finish(FAIL, "；".join(problems))
    r.finish(PASS, f"联网代码与已知清单一致（{len(inv)} 个文件）；入口可达的 {len(hits)} 个都在清单里且护栏成立，"
                   f"其余 {len(inv) - len(hits)} 个没有调用入口")


if __name__ == "__main__":
    main()
