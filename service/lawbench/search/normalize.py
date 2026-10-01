r"""检索用的归一化（Spec 第 11 节）：全角转半角、去掉数字中的千分位逗号、统一空白、去掉控制字符。查询词做同样处理。

- NFKC：全角字母数字、全角标点转半角；
- `(?<=\d),(?=\d{3})` 的逗号去掉；
- 连续空白换成一个空格；两个汉字（或中文标点）之间的空白去掉——PDF、OCR 的材料文本常在句子中间硬换行，
  "下图\n为书桌位置" 要能用"下图为书桌位置"搜到（T9 返修 P3-4，主编排定的规则）。拉丁字母、数字之间的空白保留。
  是不是汉字、中文标点按原文的字判断（NFKC 会把全角逗号、冒号变成半角）；
- 控制字符（NUL 之类，Unicode 类别 Cc 且不是空白）去掉（T9 返修 P3-3）；格式字符（类别 Cf：零宽空格、BOM 等）
  也去掉（T10 令附 T9 小项）。

normalize_with_map 另给出"归一化后第 i 个字来自原文第几个字"，命中片段从原文截取，律师看到的是原文。
"""
from __future__ import annotations

import re
import unicodedata

_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3})")
_CJK_PUNCT = set("‘’“”—…·")


def is_cjk(ch: str) -> bool:
    """汉字（CJK 统一表意文字及扩展区、兼容表意文字）或中文标点。"""
    o = ord(ch)
    if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0x20000 <= o <= 0x3134F or 0xF900 <= o <= 0xFAFF:
        return True
    if 0x3001 <= o <= 0x303F:                      # 中文标点、符号（。、「」【】〔〕等；0x3000 是全角空格，不算）
        return True
    if 0xFF01 <= o <= 0xFF65:                      # 全角标点（全角字母、数字不算）
        return not unicodedata.normalize("NFKC", ch).isalnum()
    return ch in _CJK_PUNCT


def normalize(s: str, thousands: bool = True) -> str:
    return normalize_with_map(s, thousands)[0]


def normalize_with_map(s: str, thousands: bool = True) -> tuple[str, list[int]]:
    chars: list[str] = []
    where: list[int] = []
    for i, ch in enumerate(s):
        for c in unicodedata.normalize("NFKC", ch):
            if unicodedata.category(c) in ("Cc", "Cf") and not c.isspace():
                continue                           # 控制字符、格式字符（零宽空格、BOM）
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
    # 两个汉字（中文标点）之间的空白去掉
    keep = [k for k, c in enumerate(out_c)
            if not (c == " " and 0 < k < len(out_c) - 1 and is_cjk(s[out_w[k - 1]]) and is_cjk(s[out_w[k + 1]]))]
    if len(keep) < len(out_c):
        out_c = [out_c[k] for k in keep]
        out_w = [out_w[k] for k in keep]
    text = "".join(out_c)
    # 数字中的千分位逗号
    drop = {m.start() for m in _THOUSANDS.finditer(text)} if thousands else set()
    if drop:
        out_c = [c for k, c in enumerate(out_c) if k not in drop]
        out_w = [w for k, w in enumerate(out_w) if k not in drop]
        text = "".join(out_c)
    return text, out_w
