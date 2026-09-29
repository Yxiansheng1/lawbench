"""csv / md / txt：编码识别（先 utf-8-sig，再 gb18030），按行，每 50 行标一次【第N行】（Spec 5.2、formats 第 2 节）。"""
from __future__ import annotations

import pathlib

from . import Block, Parsed, ParseError

LINES_PER_MARK = 50
ENCODINGS = ("utf-8-sig", "gb18030")


def decode(data: bytes) -> str:
    for enc in ENCODINGS:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ParseError("corrupt")


def parse(path: pathlib.Path) -> Parsed:
    try:
        data = path.read_bytes()
    except OSError:
        raise ParseError("corrupt")
    if b"\x00" in data[:4096]:
        raise ParseError("corrupt")  # 二进制文件冒充文本
    lines = decode(data).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    out = Parsed(unit="line", unit_count=len(lines), count_word="行")
    for i in range(0, len(lines), LINES_PER_MARK):
        out.blocks.append(Block(f"第{i + 1}行", "\n".join(lines[i:i + LINES_PER_MARK])))
    if not lines:
        out.blocks.append(Block("第1行", ""))
    return out
