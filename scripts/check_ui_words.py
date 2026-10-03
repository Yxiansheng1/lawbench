"""界面用语检查（T13 第 5 步；Spec 3.4 U-1、PRD：界面用律师的话，不出现 token、context 这类词）。

扫 dsh-ext\\ui\\ 下源码里律师能看到的文字——字符串字面量、JSX 文本、词条表——找出不该出现的词。
注释、import 路径、对象键名、标识符不算（只看字符串和 JSX 文本）。
英文词连同复数按整词、不分大小写匹配（sessionId 这类标识符在字符串外，不受影响）；中文词按子串匹配。
代码里恰好等于禁用词的标识符字符串（如 cordis 的服务名 'sessions'）在该行写注释 `ui-words: 标识符` 豁免，并写明是什么；
豁免只管该行上整串恰好等于禁用词的字符串，同一行的其他文字照查。

用法：python scripts\\check_ui_words.py [目录，默认 dsh-ext\\ui] [--out 报告文件]
退出码：0 = 零命中；1 = 有命中；2 = 参数错误。
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

# 词表只放这一处（T13 执行令 0357 Q12 裁决：初稿再加 上下文、embedding、schema、payload、endpoint、runtime、workspace；
# "Skill"和"Key"不禁用）。"上下文"已包含初稿的"模型上下文""上下文窗口"。英文词的复数（加 s）自动一并禁用。
BANNED_EN = ["token", "context", "prompt", "LLM", "API", "agent", "preset", "session", "JSON",
             "embedding", "schema", "payload", "endpoint", "runtime", "workspace"]
BANNED_ZH = ["上下文", "提示词"]
# T14 联调派修 3（执行令 2026-10-03 15:41）：律师看得到的 DSH 原版字样（品牌、编程用语）。我方界面源码照查；
# 另扫 DSH 的中文词条表（下面 DSH_LOCALES，补丁打上后的工作区），只查这几条——DSH 词条里本来就有"上下文"这类词，不能整表套用
BANNED_BRAND = ["探索未至之境", "预览版", "深度求索", "描述你想要构建的内容", "DSH 本地构建"]
BANNED_ZH += BANNED_BRAND
DSH_LOCALES = ["packages/client/ui-conversation/src/client/locales.ts", "packages/client/ui-chat/src/client/locale.ts",
               "packages/client/locale/src/locales/zh.ts"]

EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".json"}
SKIP_DIRS = {"node_modules", "lib", "fixtures", "tests", "__tests__"}
IGNORE_MARK = "ui-words: 标识符"

_WORDS = "(?:" + "|".join(re.escape(w) for w in BANNED_EN) + ")s?"
_EN = re.compile(r"(?<![A-Za-z0-9_])(" + _WORDS + r")(?![A-Za-z0-9_])", re.IGNORECASE)
_EN_EXACT = re.compile(_WORDS, re.IGNORECASE)
_STRING = re.compile(r"""(?P<q>['"`])(?P<body>(?:\\.|(?!(?P=q)).)*)(?P=q)""", re.DOTALL)
# JSX 文本：> 与 < 之间，去掉其中的 {…} 表达式后剩下的文字（返修 P3-1："Token 用量：{n}" 这类紧挨表达式的文字）
_JSX_RUN = re.compile(r">([^<>]*)<")
# 第二次返修 F3：单独的分号不算代码（"Token 上限; 请调小"是文字）；HTML 实体先换成空格再判断
_CODEISH = re.compile(r"[{}]|=>|&&|\|\||===|!==")
_ENTITY = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#x[0-9A-Fa-f]+);")
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
        # 像模块路径、CSS 类名、事件名这类只有 ASCII 且不含空格的短标识不算律师可见文字；
        # 但恰好等于禁用词（或其复数）的照查——{'Prompt'}、aria-label="agent"、() => 'Session' 律师都看得见（返修 P3-1）
        if re.fullmatch(r"[\w./:@#\-]*", body) and not re.search(r"[一-鿿]", body) and not _EN_EXACT.fullmatch(body):
            continue
        yield clean.count("\n", 0, m.start()) + 1, body
    if suffix in {".tsx", ".jsx"}:
        for m in _JSX_RUN.finditer(clean):
            run = _ENTITY.sub(" ", m.group(1))
            prev = None
            while prev != run:  # 由内向外去掉 {…}
                prev, run = run, re.sub(r"\{[^{}]*\}", " ", run)
            if _CODEISH.search(run):  # 剩下的像代码（比较运算、箭头函数体），不是 JSX 文本
                continue
            text = run.strip()
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
        ignored = {i + 1 for i, line in enumerate(src.split("\n")) if IGNORE_MARK in line}
        for line, text in visible_texts(src, path.suffix):
            # 豁免只管"整串恰好等于禁用词"的那个字符串（第二次返修一并做），同一行上的其他文字照查
            if line in ignored and _EN_EXACT.fullmatch(text.strip()):
                continue
            words = [m.group(1) for m in _EN.finditer(text)] + [w for w in BANNED_ZH if w in text]
            for w in words:
                hits.append((path.relative_to(root).as_posix(), line, w, text.strip()[:60]))
    return hits


def scan_dsh_locales(dsh: pathlib.Path):
    """DSH 中文词条表里的原版品牌字样（只查 BANNED_BRAND）；文件不在（dsh 子模块没检出）报一条。"""
    hits = []
    for rel in DSH_LOCALES:
        path = dsh / rel
        if not path.is_file():
            hits.append((f"dsh/{rel}", 0, "文件不在", "dsh 子模块没检出或补丁没打"))
            continue
        for line, text in visible_texts(path.read_text(encoding="utf-8", errors="replace"), path.suffix):
            for w in BANNED_BRAND:
                if w in text:
                    hits.append((f"dsh/{rel}", line, w, text.strip()[:60]))
    return hits


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=str(pathlib.Path(__file__).resolve().parents[1] / "dsh-ext" / "ui"))
    ap.add_argument("--out", help="把报告写到这个文件（UTF-8）")
    ap.add_argument("--dsh", default=str(pathlib.Path(__file__).resolve().parents[1] / "dsh"), help="DSH 工作区（补丁已打），查其中文词条表的原版品牌字样")
    ap.add_argument("--no-dsh", action="store_true", help="不查 DSH 词条表")
    a = ap.parse_args(argv)
    root = pathlib.Path(a.root)
    if not root.is_dir():
        print(f"目录不存在：{root}", file=sys.stderr)
        return 2
    hits = scan(root)
    if not a.no_dsh:
        hits += scan_dsh_locales(pathlib.Path(a.dsh))
    lines = [f"界面用语检查：{root}", f"词表（英文按整词、不分大小写，含复数）：{', '.join(BANNED_EN)}；中文：{', '.join(BANNED_ZH)}", ""]
    lines += [f"{f}:{ln}  「{w}」  …{ctx}…" for f, ln, w, ctx in hits]
    lines += ["", f"命中 {len(hits)} 处" if hits else "零命中"]
    report = "\n".join(lines) + "\n"
    if a.out:
        pathlib.Path(a.out).write_text(report, encoding="utf-8")
    sys.stdout.buffer.write(report.encode("utf-8"))
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
