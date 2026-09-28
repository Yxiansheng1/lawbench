# -*- coding: utf-8 -*-
"""
合同版本差异对照

把「已弃用的重复版本」与「本次采用的基准版本」逐段比对，输出 Markdown 对照表，
供人工判断弃用版中是否有应当保留的条文。

用法（项目根目录）： python tools/compare-contracts.py
输出： docs/template-refactor/合同版本差异对照.md
"""
import difflib
import os
import re
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PAIRS = [
    (
        "个人委托合同",
        os.path.join(ROOT, "_deprecated-templates", "1、民事委托代理合同.docx"),
        os.path.join(ROOT, "original-skill", "templates", "个人委托", "1 民事委托代理合同.docx"),
    ),
]
OUT = os.path.join(ROOT, "docs", "template-refactor", "合同版本差异对照.md")


def paragraphs(path):
    """按文档顺序提取段落文本（用 python-docx，避免正则跨段误匹配混入 XML 标记）"""
    from docx import Document
    return [p.text for p in Document(path).paragraphs]


def main():
    lines = ["# 合同版本差异对照", ""]
    lines.append("> 由 `tools/compare-contracts.py` 生成，逐段比对两个版本的实际文本，不做任何判断。")
    lines.append("> 「弃用版」为本次改造中移出的重复文件（存于 `_deprecated-templates/`），")
    lines.append("> 「采用版」为现行基准（存于 `original-skill/templates/`）。")
    lines.append("")

    for title, old_path, new_path in PAIRS:
        lines.append("## " + title)
        lines.append("")
        if not (os.path.exists(old_path) and os.path.exists(new_path)):
            lines.append("- 跳过：文件缺失（弃用版存在=%s，采用版存在=%s）" % (os.path.exists(old_path), os.path.exists(new_path)))
            lines.append("")
            continue

        a, b = paragraphs(old_path), paragraphs(new_path)
        lines.append("| 项 | 弃用版 | 采用版 |")
        lines.append("|---|---|---|")
        lines.append("| 文件 | `%s` | `%s` |" % (
            os.path.relpath(old_path, ROOT).replace("\\", "/"),
            os.path.relpath(new_path, ROOT).replace("\\", "/")))
        lines.append("| 段落数 | %d | %d |" % (len(a), len(b)))
        lines.append("")

        the_same = difflib.SequenceMatcher(None, a, b).ratio()
        lines.append("文本相似度：**%.1f%%**" % (the_same * 100))
        lines.append("")

        lines.append("### 逐段差异")
        lines.append("")
        diff = list(difflib.unified_diff(a, b, fromfile="弃用版", tofile="采用版", lineterm="", n=0))
        if not diff:
            lines.append("两版逐段完全一致。")
        else:
            lines.append("```diff")
            for d in diff:
                lines.append(d[:300])
            lines.append("```")
        lines.append("")

        # 仅出现在弃用版中的段落（最需要人工确认的部分）
        only_old = [x for x in a if x.strip() and x not in b]
        lines.append("### 仅存在于「弃用版」的段落（请确认是否有应保留的条文）")
        lines.append("")
        if only_old:
            for i, t in enumerate(only_old, 1):
                lines.append("%d. %s" % (i, t[:300]))
        else:
            lines.append("无。弃用版的所有实义段落均在采用版中有对应内容。")
        lines.append("")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("已生成：" + OUT)
    print("共 %d 组对照" % len(PAIRS))


if __name__ == "__main__":
    main()
