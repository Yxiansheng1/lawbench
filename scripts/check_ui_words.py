"""界面用语检查（T13 第 5 步；Spec 3.4 U-1、PRD：界面用律师的话，不出现 token、context 这类词）。

扫 dsh-ext\\ui\\ 下源码里律师能看到的文字——字符串字面量、JSX 文本、词条表——找出不该出现的词。
注释、import 路径、对象键名、标识符不算（只看字符串和 JSX 文本）。
英文词按整词、不分大小写匹配（sessionId 这类标识符在字符串外，不受影响）；中文词按子串匹配。

用法：python scripts\\check_ui_words.py [目录，默认 dsh-ext\\ui] [--out 报告文件]
退出码：0 = 零命中；1 = 有命中；2 = 参数错误。
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

# 词表只放这一处（T13 执行令 0357 Q12 裁决：初稿再加 上下文、embedding、schema、payload、endpoint、runtime、workspace；
# "Skill"和"Key"不禁用）。"上下文"已包含初稿的"模型上下文""上下文窗口"。
BANNED_EN = ["token", "tokens", "context", "prompt", "LLM", "API", "agent", "preset", "session", "JSON",
             "embedding", "schema", "payload", "endpoint", "runtime", "workspace"]
BANNED_ZH = ["上下文", "提示词"]

EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".json"}
SKIP_DIRS = {"node_modules", "lib", "fixtures", "tests", "__tests__"}

_EN = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(re.escape(w) for w in BANNED_EN) + r")(?![A-Za-z0-9_])", re.IGNORECASE)
_STRING = re.compile(r"""(?P<q>['"`])(?P<body>(?:\\.|(?!(?P=q)).)*)(?P=q)""", re.DOTALL)
_JSX_TEXT = re.compile(r">([^<>{}]+)<")
_LINE_COMMENT = re.compile(r"(^|[^:\\])//[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_IMPORT = re.compile(r"^\s*(import|export)\b[^\n]*\bfrom\s*['\"][^'\"]+['\"]|^\s*import\s*['\"][^'\"]+['\"]", re.MULTILINE)


def _strip(src: str) -> str:
    """去掉注释和 import 行，但保留行号（替换成等长空白）。"""
    blank = lambda m: re.sub(r"[^\n]", " ", m.group(0))
    src = _BLOCK_COMMENT.sub(blank, src)
    src = _LINE_COMMENT.sub(lambda m: m.group(1) + re.sub(r"[^\n]", " ", m.group(0)[len(m.group(1)):]), src)
    return _IMPORT.sub(blank, src)


def visible_texts(src: str, suffix: str):
    """产出 (行号, 文字)：字符串字面量与 JSX 文本；.json 词条表只取值。"""
    if suffix == ".json":
        for m in re.finditer(r':\s*"((?:\\.|[^"\\])*)"', src):
            yield src.count("\n", 0, m.start()) + 1, m.group(1)
        return
    clean = _strip(src)
    for m in _STRING.finditer(clean):
        body = m.group("body")
        if m.group("q") == "`":
            body = re.sub(r"\$\{[^}]*\}", " ", body)  # 模板字符串里 ${…} 是代码，不是界面文字
        # 像模块路径、CSS 类名、事件名这类只有 ASCII 且不含空格的短标识不算律师可见文字
        if re.fullmatch(r"[\w./:@#\-]*", body) and not re.search(r"[一-鿿]", body):
            continue
        yield clean.count("\n", 0, m.start()) + 1, body
    if suffix in {".tsx", ".jsx"}:
        for m in _JSX_TEXT.finditer(clean):
            text = m.group(1).strip()
            if text:
                yield clean.count("\n", 0, m.start()) + 1, text


def scan(root: pathlib.Path):
    hits = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in EXTS:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        for line, text in visible_texts(src, path.suffix):
            words = [m.group(1) for m in _EN.finditer(text)] + [w for w in BANNED_ZH if w in text]
            for w in words:
                hits.append((path.relative_to(root).as_posix(), line, w, text.strip()[:60]))
    return hits


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=str(pathlib.Path(__file__).resolve().parents[1] / "dsh-ext" / "ui"))
    ap.add_argument("--out", help="把报告写到这个文件（UTF-8）")
    a = ap.parse_args(argv)
    root = pathlib.Path(a.root)
    if not root.is_dir():
        print(f"目录不存在：{root}", file=sys.stderr)
        return 2
    hits = scan(root)
    lines = [f"界面用语检查：{root}", f"词表（英文按整词、不分大小写）：{', '.join(BANNED_EN)}；中文：{', '.join(BANNED_ZH)}", ""]
    lines += [f"{f}:{ln}  「{w}」  …{ctx}…" for f, ln, w, ctx in hits]
    lines += ["", f"命中 {len(hits)} 处" if hits else "零命中"]
    report = "\n".join(lines) + "\n"
    if a.out:
        pathlib.Path(a.out).write_text(report, encoding="utf-8")
    sys.stdout.buffer.write(report.encode("utf-8"))
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
