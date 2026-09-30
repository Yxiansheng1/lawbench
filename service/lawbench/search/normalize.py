"""检索用的归一化（Spec 第 11 节）：全角转半角、去掉数字中的千分位逗号、统一空白。查询词做同样处理。

与 T8 临时检索（tools/materials.normalize）的规则相同：NFKC（全角字母数字、全角标点转半角）、
`(?<=\\d),(?=\\d{3})` 的逗号去掉、连续空白换成一个空格。

normalize_with_map 另给出"归一化后第 i 个字来自原文第几个字"，命中片段从原文截取，律师看到的是原文。
"""
from __future__ import annotations

import re
import unicodedata

_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3})")


def normalize(s: str) -> str:
    return normalize_with_map(s)[0]


def normalize_with_map(s: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    where: list[int] = []
    for i, ch in enumerate(s):
        for c in unicodedata.normalize("NFKC", ch):
            chars.append(c)
            where.append(i)
    # 统一空白：连续空白换成一个空格
    out_c: list[str] = []
    out_w: list[int] = []
    for c, w in zip(chars, where):
        if c.isspace():
            if out_c and out_c[-1] == " ":
                continue
            c = " "
        out_c.append(c)
        out_w.append(w)
    text = "".join(out_c)
    # 数字中的千分位逗号
    drop = {m.start() for m in _THOUSANDS.finditer(text)}
    if drop:
        out_c = [c for k, c in enumerate(out_c) if k not in drop]
        out_w = [w for k, w in enumerate(out_w) if k not in drop]
        text = "".join(out_c)
    return text, out_w
