"""查询扩展（Spec 第 11 节）：日期、金额的几种写法同时查，结果合并。

- 日期：2025年3月10日 ↔ 2025-03-10 ↔ 2025.3.10（另含 2025/3/10、不补零 / 补零的写法）；
- 金额：8万 ↔ 80000 ↔ 80,000（归一化后千分位逗号已去掉，80,000 与 80000 是同一个串）；带"元"的去掉"元"再比。

返回 [(归一化后的查询串, "exact" | "expanded")]，第一个是原查询本身；其余是扩展出来的、与它不同的写法。
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .normalize import normalize

_DATE = re.compile(r"^\s*(\d{4})\s*(?:年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?|[-./](\d{1,2})[-./](\d{1,2}))\s*$")
_WAN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(万|亿)\s*元?\s*$")
_NUM = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*元?\s*$")


def _dates(q: str) -> list[str]:
    m = _DATE.match(q)
    if not m:
        return []
    y = int(m.group(1))
    mo = int(m.group(2) or m.group(4))
    d = int(m.group(3) or m.group(5))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return []
    return [f"{y}年{mo}月{d}日", f"{y}-{mo:02d}-{d:02d}", f"{y}.{mo}.{d}", f"{y}.{mo:02d}.{d:02d}",
            f"{y}/{mo}/{d}", f"{y}/{mo:02d}/{d:02d}", f"{y}-{mo}-{d}", f"{y}年{mo:02d}月{d:02d}日"]


def _plain(n: Decimal) -> str:
    s = f"{n:f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _amounts(q: str) -> list[str]:
    try:
        m = _WAN.match(q)
        if m:
            n = Decimal(m.group(1)) * (Decimal(10000) if m.group(2) == "万" else Decimal(100000000))
        else:
            m = _NUM.match(q)
            if not m:
                return []
            n = Decimal(m.group(1))
    except InvalidOperation:
        return []
    if n <= 0:
        return []
    out = [_plain(n)]
    if n % 10000 == 0 or (n * 100) % 10000 == 0:  # 能写成整数万或两位小数万
        out.append(_plain(n / 10000) + "万")
    if n % 100000000 == 0:
        out.append(_plain(n / 100000000) + "亿")
    return out


def variants(query: str) -> list[tuple[str, str]]:
    """原查询（exact）在前，其余扩展写法（expanded）去重后跟在后面。都已归一化。"""
    q = normalize(query).strip()
    out = [(q, "exact")]
    seen = {q}
    for v in _dates(q) + _amounts(q):
        nv = normalize(v)
        if nv not in seen:
            seen.add(nv)
            out.append((nv, "expanded"))
    return out


def is_numeric(v: str) -> bool:
    """纯数字的查询串：匹配时要求前后不是数字（80000 不命中 180000）。"""
    return bool(re.fullmatch(r"\d+(?:\.\d+)?", v))
