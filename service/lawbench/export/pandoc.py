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

_INLINE = re.compile(r"(!?)\[((?:[^\[\]\\]|\\.)*)\]\(\s*<?([^()\s>]*(?:\([^()\s]*\)[^()\s>]*)*)>?(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)")
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
    md = _INLINE.sub(lambda m: m.group(2) if _is_workspace(m.group(3)) else m.group(0), md)

    def ref_use(m):
        key = (m.group(3) or m.group(2)).casefold()
        target = refs.get(key)
        return m.group(2) if target is not None and _is_workspace(target) else m.group(0)
    md = _REFUSE.sub(ref_use, md)
    return _AUTO.sub(lambda m: "" if _looks_path(m.group(1)) and _is_workspace(m.group(1)) else m.group(0), md)


def _looks_path(s: str) -> bool:
    """尖括号里像链接目标（含 / 或 :），不是 HTML 标签（<br>、<b> 之类）。"""
    return "/" in s or ":" in s


# ---------------------------------------------------------------- Word

def to_docx(md: str, reference_doc: pathlib.Path, pandoc: str | None = None) -> bytes:
    exe = pandoc or find_pandoc()
    if not exe:
        raise ApiError("INTERNAL", "pandoc_not_found")
    args = [exe, "--sandbox", "-f", "markdown", "-t", "docx", f"--reference-doc={reference_doc}", "-o", "-"]
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
