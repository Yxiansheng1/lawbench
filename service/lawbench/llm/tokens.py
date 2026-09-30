"""token 计数（Spec 8.2：L1 按窗口的 40% 控制，按 token 计）。

优先用 6000D 上 qwen38-27b 的 tokenizer.json（放在本目录，`tokenizers` 库可用时自动启用）。
取 tokenizer 要 SSH 密码（工单 T8 第 1 步），还没取到时用近似计数，刻意偏大（宁可少装、不超窗口），
算法见 count()：中日韩文字和全角符号每字 1、数字每位 1、连续英文字母每 3 个 1、其他 ASCII 符号每个 1、
连续空白 1、其余非 ASCII 字符每字 2。换成真计数只需把文件放到位并装上 tokenizers。
"""
from __future__ import annotations

import functools
import math
import pathlib

TOKENIZER_PATH = pathlib.Path(__file__).with_name("tokenizer.json")

# 窗口 → token 数（Spec 8.2）
WINDOWS = {"32K": 32768, "64K": 65536, "128K": 131072}
L1_RATIO = 0.40


@functools.lru_cache(maxsize=1)
def _tokenizer():
    if not TOKENIZER_PATH.is_file():
        return None
    try:
        from tokenizers import Tokenizer
    except ImportError:
        return None
    return Tokenizer.from_file(str(TOKENIZER_PATH))


def is_exact() -> bool:
    return _tokenizer() is not None


def _cjk(ch: str) -> bool:
    o = ord(ch)
    return (0x3400 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x2FFFF
            or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF)


def count(text: str) -> int:
    """有 tokenizer 用真计数；没有时近似计数，刻意偏大（它用来控制"不超过窗口的 40%"，少算会超窗口）：
    - 中日韩文字、全角符号：每字 1 token（Qwen 系分词器对常见汉字通常一个字不到 1 token）；
    - 数字：每位 1 token（Qwen 系把数字逐位切开）；
    - 英文字母：连续的一串按每 3 个字母 1 token 向上取整（常见实测约 4 个字母 1 token）；
    - 其他 ASCII 符号：每个 1 token；连续空白算 1 token；
    - 其余非 ASCII 字符（其他文字、表情等）：每字 2 token。
    与真实长度的偏差（T8 交付说明第 13 节实测）：仓库 68 份样本上近似 ÷ 真实为 1.03–1.90，中位数 1.46，没有少算；
    扩展区生僻字（4 字节 UTF-8）会少算（约 0.43），已知限制。"""
    tok = _tokenizer()
    if tok is not None:
        return len(tok.encode(text).ids)
    n = 0
    letters = 0
    prev_space = False
    for c in text:
        if c.isascii() and c.isalpha():
            letters += 1
            prev_space = False
            continue
        if letters:
            n += math.ceil(letters / 3)
            letters = 0
        if c.isspace():
            if not prev_space:
                n += 1
            prev_space = True
            continue
        prev_space = False
        if _cjk(c) or c.isascii():
            n += 1
        else:
            n += 2
    if letters:
        n += math.ceil(letters / 3)
    return n


def l1_budget(window: str) -> int:
    return int(WINDOWS[window] * L1_RATIO)
