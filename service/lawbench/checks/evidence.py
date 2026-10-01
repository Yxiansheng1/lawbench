"""引语逐字核对（由 wiki 测试的 check_evidence.py 改成库函数；Spec 9.4）。

- 候选：引号（“”、""、「」）内的原文、引用块（> 开头的行）的正文，归一化、去掉全部空白后至少 QUOTE_MIN 字。
  wiki 脚本定的是 15 字（为压误报）；律师草稿里加引号就是声称原样，短引语也核，阈值见注记 1123 第 1 条。
- 比较：两边都用 T9 的 normalize（全角半角、千分位、汉字间空白），再去掉全部空白和换行
  （PDF 取文字时折行处有换行，tests/fixtures/README.md cite-cases 段）。
- 在所标位置找不到：所引材料别处找到报 B，哪里都没有报 C（裁决 2）。原脚本的"未被引用的 raw 文件"清单不搬。
- 引语里有识别不清的 ■ 的不核（照抄识别结果是对的写法，由 A 类管补全）。
"""
from __future__ import annotations

import re

from ..search.normalize import normalize
from .parse import QUOTE, Material

QUOTE_MIN = 6
_WS = re.compile(r"\s+")
# 各种引号比较时算同一个字符：引文里再套引文时内层换单引号是排版惯例（复核 P2-1，大卷宗赵刚引语）
_QUOTES = re.compile(r"[“”‘’\"'「」『』]")


def squash(s: str) -> str:
    """归一化（全角半角，＂＇已由 NFKC 变成 "'）、去掉全部空白、引号统一成一个字符。"""
    return _QUOTES.sub('"', _WS.sub("", normalize(s)))


def quotes_in(fact: str, blockquote: bool) -> list[str]:
    """一段事实文字里要核的引语（原样）。"""
    if blockquote:
        found = [fact.strip()]
    else:
        found = [m.group(0)[1:-1] for m in QUOTE.finditer(fact)]
    return [q for q in found if len(squash(q)) >= QUOTE_MIN and "■" not in q]


def locate(quote: str, targets: list[tuple[Material, dict]]) -> tuple[bool, list[str]]:
    """(在所标位置找到了, 所引材料里别处找到的位置)。"""
    q = squash(quote)
    if any(q in squash(m.text_at(loc)) for m, loc in targets):
        return True, []
    elsewhere = []
    seen = set()
    for m, _ in targets:
        if m.name in seen:
            continue
        seen.add(m.name)
        elsewhere += [f"{m.name} {label}" for label, text in m.per_place("squash", squash) if q in text]
    return False, elsewhere
