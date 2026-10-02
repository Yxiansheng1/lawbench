"""草稿 Markdown → Word / Markdown 成果（Spec 12.1、14.3）。

- Word：`pandoc --sandbox -f markdown -t docx --reference-doc=<模板>`，草稿从标准输入进、docx 从标准输出出，
  不落临时文件。`--sandbox` 每次都带（T19 复核：pandoc 会按草稿里的远程图片链接去取图；sandbox 下只读命令行
  给出的文件，不联网、不读本机其他文件）。
- 两种格式都先去掉指向工作区的链接（只留链接文字），出处 〔〕 本来就是纯文本、原样保留。
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import urllib.parse

from ..errors import ApiError
from ..procs import kill_tree

TIMEOUT = 120  # 秒
TEMPLATE_DIR = pathlib.Path(__file__).with_name("templates")
TEMPLATES = ("文书", "合同")


def find_pandoc() -> str | None:
    """查找顺序：环境变量 LAWBENCH_PANDOC → PATH → 用户级安装（%LOCALAPPDATA%\\Pandoc）→ 全机安装。不写死用户名。"""
    env = os.environ.get("LAWBENCH_PANDOC")
    if env:
        return env if os.path.isfile(env) else None
    found = shutil.which("pandoc")
    if found:
        return found
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            c = os.path.join(base, "Pandoc", "pandoc.exe")
            if os.path.isfile(c):
                return c
    return None


def template_path(name: str, settings: dict) -> pathlib.Path:
    """设置里指定了律所模板就用它（文件不在了报 TEMPLATE_MISSING，不悄悄换成占位模板）；没指定用内置占位模板。"""
    custom = (settings.get("templates") or {}).get(name)
    p = pathlib.Path(custom) if custom else TEMPLATE_DIR / f"{name}.docx"
    if not p.is_file() or p.suffix.lower() != ".docx":
        raise ApiError("TEMPLATE_MISSING", "custom" if custom else "builtin")
    return p


# ---------------------------------------------------------------- 去掉指向工作区的链接

_INLINE = re.compile(r"(!?)\[((?:[^\[\]\\]|\\.|!\[(?:[^\[\]\\]|\\.)*\]\([^()\n]*\))*)\]\(\s*(?:<([^<>\n]*)>|([^()\s<>]*(?:\([^()\s]*\)[^()\s<>]*)*))"
                     r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)")
# 原始 HTML：开始标签、结束标签一遍扫出来再配对（T15 第二轮记录项 5：原来的 <a …>(.*?)</a> 遇到大量不闭合的 <a>
# 耗时按平方增长）。[^>]* 遇到 > 就停，整体线性
# 标签和属性长度都设上限（T23 第二轮记录项 8：没有 > 的大量 "<a" 曾要 91 秒）
_HTML_TAG = re.compile(r"<(/?)(a|iframe|object|img|source|embed)\b([^<>]{0,2000})>", re.I)
_HTML_ATTR = re.compile(r"\b(?:href|src|data)\s*=\s*(?:\"([^\"]{0,2000})\"|'([^']{0,2000})'|([^\s>]{1,2000}))", re.I)
_PAIRED = ("a", "iframe", "object")
_AUTO = re.compile(r"<([^<>\s]+)>")
_REFDEF = re.compile(r"^ {0,3}\[([^\]]+)\]:[ \t]*<?(\S+?)>?(?:[ \t]+.*)?$", re.M)
_REFUSE = re.compile(r"(!?)\[((?:[^\[\]\\]|\\.)*)\]\[([^\]]*)\]")


def _is_workspace(target: str) -> bool:
    """链接目标是否指向案件工作区：解码后任一级目录名是"工作区"，或是本机文件（file:、盘符、相对路径的 .md）。"""
    t = urllib.parse.unquote(target).replace("\\", "/")
    if t.lower().startswith(("http://", "https://", "mailto:")):
        return "工作区" in t.split("/")
    if t.startswith("#"):
        return False
    parts = [p for p in t.split("/") if p]
    return "工作区" in parts or t.lower().startswith("file:") or bool(re.match(r"^[a-zA-Z]:", t)) \
        or t.startswith(("./", "../")) or t.lower().endswith(".md")


def strip_workspace_links(md: str) -> str:
    """[文字](工作区/…) → 文字；![说明](工作区/…) → 说明；<工作区/…> → 去掉；引用式链接同样处理。"""
    refs = {m.group(1).casefold(): m.group(2) for m in _REFDEF.finditer(md)}
    md = _REFDEF.sub(lambda m: "" if _is_workspace(m.group(2)) else m.group(0), md)
    while True:                                     # 图片外再套链接 [![图](工作区/a)](工作区/b)：替换到不再变（P3-4）
        new = _INLINE.sub(lambda m: m.group(2) if _is_workspace(m.group(3) if m.group(3) is not None
                                                                  else m.group(4)) else m.group(0), md)
        new = _strip_html(new)
        if new == md:
            break
        md = new

    def ref_use(m):
        key = (m.group(3) or m.group(2)).casefold()
        target = refs.get(key)
        return m.group(2) if target is not None and _is_workspace(target) else m.group(0)
    md = _REFUSE.sub(ref_use, md)
    return _AUTO.sub(lambda m: "" if _looks_path(m.group(1)) and _is_workspace(m.group(1)) else m.group(0), md)


def _strip_html(md: str) -> str:
    """原始 HTML 里指向工作区的：<a href> 去掉开始和配对的结束标签、留链接文字（不闭合的只去开始标签）；
    <iframe>/<object> 连同里面的内容和结束标签整段去掉（记录项 6）；<img>/<source>/<embed> 去掉标签。"""
    cut: list[tuple[int, int]] = []
    stack: dict[str, list] = {t: [] for t in _PAIRED}
    for m in _HTML_TAG.finditer(md):
        closing, tag = m.group(1) == "/", m.group(2).lower()
        if closing:
            if tag in stack and stack[tag]:
                start, end, hit = stack[tag].pop()
                if hit and tag == "a":
                    cut += [(start, end), (m.start(), m.end())]
                elif hit:
                    cut.append((start, m.end()))
            continue
        attr = _HTML_ATTR.search(m.group(3))
        hit = bool(attr) and _is_workspace(next(g for g in attr.groups() if g is not None))
        if tag in _PAIRED:
            stack[tag].append((m.start(), m.end(), hit))
        elif hit:
            cut.append((m.start(), m.end()))
    for tag in _PAIRED:                                # 没有结束标签的：只去开始标签
        cut += [(s, e) for s, e, hit in stack[tag] if hit]
    if not cut:
        return md
    out, pos = [], 0
    for s, e in sorted(cut):
        if s < pos:                                    # 已在整段去掉的 iframe / object 里
            pos = max(pos, e)
            continue
        out.append(md[pos:s])
        pos = e
    out.append(md[pos:])
    return "".join(out)


def _looks_path(s: str) -> bool:
    """尖括号里像链接目标（含 / 或 :），不是 HTML 标签（<br>、<b> 之类）。"""
    return "/" in s or ":" in s


# ---------------------------------------------------------------- Word

def to_docx(md: str, reference_doc: pathlib.Path, pandoc: str | None = None) -> bytes:
    exe = pandoc or find_pandoc()
    if not exe:
        raise ApiError("INTERNAL", "pandoc_not_found")
    # 关掉原始 OpenXML / HTML / TeX 透传：草稿里的 ```{=openxml} 块不原样写进 docx（复核 NOTE-1）
    args = [exe, "--sandbox", "-f", "markdown-raw_attribute-raw_html-raw_tex", "-t", "docx", f"--reference-doc={reference_doc}", "-o", "-"]
    try:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        raise ApiError("INTERNAL", "pandoc_spawn")
    try:
        out, _err = proc.communicate(md.encode("utf-8"), timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        kill_tree(proc, drain=True)
        raise ApiError("INTERNAL", "pandoc_timeout")
    if proc.returncode != 0 or not out.startswith(b"PK"):
        raise ApiError("INTERNAL", f"pandoc_exit_{proc.returncode}")
    return out
