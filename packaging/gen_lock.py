r"""生成 packaging\versions.lock 的客户端部分和 packaging\THIRD-PARTY-LICENSES.md（T20 步骤 5）。

用法（仓库根下）：python packaging\gen_lock.py --site <客户端 Python 依赖目录>
  --site  装好我方依赖的 site-packages（打包时是 <构建目录>\python\site-packages；准备阶段可先用开发环境的）。
          从下面 ROOTS 出发按各包声明的依赖求闭包，只记闭包里的包（开发用的 pytest 等不进来）。
版本、哈希都从真实来源读：DSH 子模块提交、DSH 桌面端内置运行时 lock.json、Electron 包、引擎 CHANGELOG、
本仓库 service\pyproject.toml、tokenizer.json 文件本身。读不到的写"候补"，不编。
versions.lock 里原有的 [395] 等由别处维护的段原样保留，只替换 [client*] 段。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
from importlib.metadata import Distribution, PathDistribution

Requirement = None  # main() 里从依赖目录取 packaging.requirements.Requirement

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCK = ROOT / "packaging" / "versions.lock"
LICENSES = ROOT / "packaging" / "THIRD-PARTY-LICENSES.md"
PENDING = "候补"

# 客户端 Python 要装的顶层包：service\pyproject.toml 的依赖 + Spec 14.1 / 13.5 点名的
# （pywin32：Word/WPS 自动化；pypdf、reportlab：归档与 Word 转 PDF；证件识别驱动：rapidocr 及其依赖 onnxruntime、opencv）
EXTRA_ROOTS = ["pywin32", "pypdf", "reportlab", "onnxruntime", "opencv-python-headless", "pyclipper", "shapely", "PyYAML", "omegaconf", "PyMuPDF"]

# 不在 Python 里的组件：版本未定的写候补（T20 步骤 3 选定后补）
OTHER = [
    ("libreoffice", PENDING, PENDING, "documentfoundation.org", "MPL-2.0"),
    ("pandoc", PENDING, PENDING, "github.com/jgm/pandoc releases", "GPL-2.0-or-later"),
]


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def service_roots() -> list[str]:
    text = (ROOT / "service" / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"^dependencies = \[(.*?)^\]", text, re.S | re.M).group(1)
    return [re.match(r"[A-Za-z0-9_.\-]+", s).group(0) for s in re.findall(r'^\s*"([^"]+)"', block, re.M)]


def distributions(site: pathlib.Path) -> dict[str, Distribution]:
    out: dict[str, Distribution] = {}
    for meta in list(site.glob("*.dist-info")):
        d = PathDistribution(meta)
        if d.metadata["Name"]:
            out[norm(d.metadata["Name"])] = d
    return out


TARGET_ENV = {"python_version": "3.12", "python_full_version": "3.12.14", "sys_platform": "win32", "platform_system": "Windows",
              "os_name": "nt", "platform_machine": "AMD64", "implementation_name": "cpython", "platform_python_implementation": "CPython"}


def closure(dists: dict[str, Distribution], roots: list[str]) -> tuple[list[Distribution], list[str]]:
    seen: dict[str, Distribution] = {}
    missing: list[str] = []
    todo = [norm(r) for r in roots]
    while todo:
        n = todo.pop()
        if n in seen or n in missing:
            continue
        d = dists.get(n)
        if d is None:
            missing.append(n)
            continue
        seen[n] = d
        for req in d.requires or []:
            r = Requirement(req)
            # 按客户端环境（Windows x64、CPython 3.12、不带 extra）判断条件依赖
            if r.marker is not None and not r.marker.evaluate({**TARGET_ENV, "extra": ""}):
                continue
            todo.append(norm(r.name))
    return sorted(seen.values(), key=lambda d: norm(d.metadata["Name"])), sorted(missing)


def license_of(d: Distribution) -> str:
    m = d.metadata
    expr = m.get("License-Expression")
    if expr:
        return expr
    lic = (m.get("License") or "").strip()
    if lic and len(lic) < 60 and "\n" not in lic:
        return lic
    classes = [c.split("::")[-1].strip() for c in m.get_all("Classifier") or [] if c.startswith("License ::")]
    return "; ".join(classes) or PENDING


def client_sections(site: pathlib.Path) -> tuple[str, list[tuple[str, str, str]], list[str]]:
    dsh_commit = subprocess.run(["git", "-C", str(ROOT / "dsh"), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() or PENDING
    rt = json.loads((ROOT / "dsh" / "scripts" / "primary-runtime" / "lock.json").read_text(encoding="utf-8"))
    win = rt["targets"]["win-x64"]
    electron = next((p.name.split("@", 1)[1] for p in (ROOT / "dsh" / "node_modules" / ".pnpm").glob("electron@*")), PENDING)
    ver = lambda p: (re.search(r"^## \[([^\]]+)\]", p.read_text(encoding="utf-8"), re.M) or [None, PENDING])[1]
    tok = ROOT / "service" / "lawbench" / "llm" / "tokenizer.json"
    lines = [
        "[client]  # T20 步骤 5，packaging\\gen_lock.py 生成；格式同上：组件  版本  文件  sha256  来源  许可证",
        f"dsh           {dsh_commit}  dsh\\（子模块，补丁见 dsh-patches\\PATCHES.md）  -  github.com/deepseek-ai/dsh  MIT",
        f"electron      {electron}  -  -  npm electron  MIT",
        f"node          {rt['nodeVersion']}  {win['nodeArchive']}  {win['nodeSha256']}  nodejs.org（DSH 内置运行时）  MIT",
        f"python        {rt['pythonVersion']}（python-build-standalone {rt['pythonRelease']}, {win['pythonTarget']}, install_only_stripped）  -  {win['pythonSha256']}  DSH 内置运行时（复用，见 PATCHES.md 结论记录）  PSF-2.0",
        f"invoice-ledger  {ver(ROOT / 'engines' / 'invoice-ledger' / 'CHANGELOG.md')}  engines\\invoice-ledger\\  -  律所提供（周海沺律师），见 CHANGELOG  作者授权",
        f"retainer      {ver(ROOT / 'engines' / 'retainer' / 'CHANGELOG.md')}  engines\\retainer\\  -  律所提供（周海沺律师）  作者授权",
        f"tokenizer     Qwen3  tokenizer.json  {sha256(tok) if tok.is_file() else PENDING}  6000D 同款模型的分词文件（N16）  Apache-2.0",
    ]
    for name, v, sha, src, lic in OTHER:
        lines.append(f"{name:<13} {v}  -  {sha}  {src}  {lic}")
    dists, missing = closure(distributions(site), service_roots() + EXTRA_ROOTS)
    lines += ["", "[client.pip]  # 客户端 Python 依赖闭包（-I -S 隔离运行，不用 DSH 内置运行时自带的 numpy、pandas 等）"]
    rows = []
    for d in dists:
        lines.append(f"{d.metadata['Name']}=={d.version}")
        rows.append((d.metadata["Name"], d.version, license_of(d)))
    if missing:
        lines.append(f"# {PENDING}：依赖目录里没有，打包时装上再生成：{', '.join(missing)}")
    return "\n".join(lines) + "\n", rows, missing


def write_lock(client: str) -> None:
    old = LOCK.read_text(encoding="utf-8") if LOCK.exists() else ""
    kept = re.split(r"(?m)^\[client", old)[0].rstrip() + "\n\n" if old else ""
    LOCK.write_text(kept + client, encoding="utf-8", newline="\n")


def write_licenses(rows: list[tuple[str, str, str]], missing: list[str]) -> None:
    out = [
        "# 第三方组件与许可证（T20 步骤 5）",
        "",
        "由 `packaging\\gen_lock.py` 生成，版本以 `packaging\\versions.lock` 为准。标\"候补\"的是还没选定或还没装进依赖目录的，打包前补齐。",
        "",
        "## 桌面端（DSH）",
        "",
        "- DSH 本身 MIT（`dsh\\LICENSE`）；它的直接依赖、内置 Python 包和 vendored 源码见 `dsh\\THIRD_PARTY_NOTICES.md`（DSH 自带，生成工具 `scripts\\gen-third-party-notices.ts`）；npm 全部传递依赖以 `dsh\\pnpm-lock.yaml` 为准（`pnpm licenses list`）。",
        "- Electron（MIT）、Node.js（MIT）、Python（PSF-2.0）随 DSH 桌面端内置运行时。",
        "",
        "## 其他内置组件",
        "",
        "| 组件 | 许可证 | 说明 |",
        "|---|---|---|",
        "| LibreOffice | MPL-2.0 | 版本候补（T20 步骤 3） |",
        "| pandoc | GPL-2.0-or-later | 版本候补；**作为独立程序随包分发，按 GPL 要附许可证全文并提供对应源码的获取方式**，候主编排确认分发方式 |",
        "| 发票整理引擎（invoice-ledger-db 3.9.4.1） | 作者授权 | 律所周海沺律师提供，原样使用；署名保留 |",
        "| 委托材料网页与证件识别驱动（retainer-offline 3.4.1） | 作者授权 | 同上；驱动内附 RapidOCR 及模型，许可证见驱动目录 |",
        "| Qwen3 分词文件 tokenizer.json | Apache-2.0 | |",
        "",
        "## 客户端 Python 依赖",
        "",
        "| 包 | 版本 | 许可证（取自包自己的元数据） |",
        "|---|---|---|",
    ]
    out += [f"| {n} | {v} | {lic} |" for n, v, lic in rows]
    if missing:
        out += ["", f"{PENDING}：{', '.join(missing)}（依赖目录里没有，打包时装上再生成）。"]
    LICENSES.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True, type=pathlib.Path)
    a = ap.parse_args()
    # 判断条件依赖用依赖目录里的 packaging（构建机的 Python 不一定装了）
    sys.path.insert(0, str(a.site))
    global Requirement
    from packaging.requirements import Requirement
    client, rows, missing = client_sections(a.site)
    write_lock(client)
    write_licenses(rows, missing)
    print(f"[client.pip] {len(rows)} 个包；候补 {len(missing)} 个：{', '.join(missing) or '无'}")


if __name__ == "__main__":
    sys.exit(main())
