"""token 计数（Spec 8.2：L1 按窗口的 40% 控制，按 token 计）。

优先用 6000D 上 qwen38-27b 的 tokenizer.json（放在本目录，`tokenizers` 库可用时自动启用）。
取 tokenizer 要 SSH 密码（工单 T8 第 1 步），还没取到时用近似计数：中日韩文字每字 1 token，
其余按 UTF-8 字节数 / 4 向上取整。近似值偏大（宁可少装、不超窗口），换成真计数只需把文件放到位。
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
    tok = _tokenizer()
    if tok is not None:
        return len(tok.encode(text).ids)
    cjk = sum(1 for c in text if _cjk(c))
    rest = sum(len(c.encode("utf-8")) for c in text if not _cjk(c))
    return cjk + math.ceil(rest / 4)


def l1_budget(window: str) -> int:
    return int(WINDOWS[window] * L1_RATIO)
