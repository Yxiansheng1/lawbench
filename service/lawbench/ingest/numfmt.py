"""Excel 数字格式：把单元格的原始值按 number_format 套成律师在 Excel 里看到的样子（Spec 5.2，N27；T5 返修 X13）。

套得出来的：常规（General）、整数与固定小数位（0、0.00、#,##0.00…）、千分位、百分比（0%、0.00%）、
正负零分节（`正;负;零;文本`，含括号负数、[Red] 等颜色标记）、货币符号与会计格式（`_(`、`* ` 填充、`"-"` 零值）、
文本格式（@）、日期和时间（yyyy、yy、m、mm、d、dd、h、hh、mm（分）、ss、AM/PM，及"年月日"等原样文字）。

套不出来、写原始值的（format() 返回 None，由调用方退回原始值写法）：科学计数（E+）、分数（# ?/?）、
带条件的分节（[>100]）、以千为单位缩放（数字后的逗号）、月份和星期的名称（mmm、mmmm、ddd、dddd）、
累计时长（[h]、[mm]、[ss]）、秒的小数（ss.0）、本地化日期代码（[$-F800] 等）。
"""
from __future__ import annotations

import datetime as dt
import re
from decimal import ROUND_HALF_UP, Decimal

_COLOR = re.compile(r"\[(?:Black|Blue|Cyan|Green|Magenta|Red|White|Yellow|Color\s*\d+)\]", re.I)
_CURRENCY = re.compile(r"\[\$([^\]-]*)(?:-[0-9A-Fa-f]+)?\]")
_DATE_TOKENS = ("yyyy", "yy", "mmmm", "mmm", "mm", "m", "dddd", "ddd", "dd", "d", "hh", "h", "ss", "s")


class Unsupported(Exception):
    pass


def _sections(fmt: str) -> list[str]:
    out, cur, q, i = [], "", False, 0
    while i < len(fmt):
        c = fmt[i]
        if c == '"':
            q = not q
        elif c == "\\" and i + 1 < len(fmt) and not q:
            cur += fmt[i:i + 2]
            i += 2
            continue
        elif c == ";" and not q:
            out.append(cur)
            cur = ""
            i += 1
            continue
        cur += c
        i += 1
    out.append(cur)
    return out


def _clean(sec: str) -> str:
    sec = _COLOR.sub("", sec)
    sec = _CURRENCY.sub(lambda m: '"' + m.group(1) + '"' if m.group(1) else "", sec)
    if re.search(r"\[[^\]]*\]", sec):  # 条件、累计时长、本地化代码等
        raise Unsupported(sec)
    return sec


def _tokens(sec: str):
    """把一节拆成 ("lit", 文字) 和 ("code", 格式字符) 两种。"""
    i = 0
    while i < len(sec):
        c = sec[i]
        if c == '"':
            j = sec.find('"', i + 1)
            if j < 0:
                raise Unsupported(sec)
            yield "lit", sec[i + 1:j]
            i = j + 1
        elif c == "\\" and i + 1 < len(sec):
            yield "lit", sec[i + 1]
            i += 2
        elif c == "_" and i + 1 < len(sec):
            i += 2           # 占一个字符宽的空白：文本里不写
        elif c == "*" and i + 1 < len(sec):
            i += 2           # 填满列宽的重复字符：文本里不写
        else:
            yield "code", c
            i += 1


# ---------- 数字 ----------

def _number(value: float, sec: str, signed: bool) -> str:
    parts = list(_tokens(sec))
    codes = "".join(t for k, t in parts if k == "code")
    if any(ch in codes for ch in "Ee/"):
        raise Unsupported(sec)
    if "@" in codes:
        raise Unsupported(sec)
    pct = codes.count("%")
    num_chars = set("0#?.,")   # ? 是占位（对齐用的空格），文本里按 # 处理
    # 数字占位的那一段（第一个 0/# 到最后一个 0/#，中间可含 , 和 .）
    idx = [i for i, (k, t) in enumerate(parts) if k == "code" and t in "0#?"]
    if not idx:
        text = "".join(t for k, t in parts)   # 没有数字占位：整节是文字（如会计格式零值的 "-"）
        return text.replace("%", "")
    a, b = idx[0], idx[-1]
    # 小数点可能在最后一个占位之后（"0."）：并进来
    while b + 1 < len(parts) and parts[b + 1] == ("code", "."):
        b += 1
    body = "".join(t for k, t in parts[a:b + 1] if k == "code" and t in num_chars).replace("?", "#")
    if any(k == "lit" for k, _ in parts[a:b + 1]):
        raise Unsupported(sec)
    tail_codes = "".join(t for k, t in parts[b + 1:] if k == "code")
    if tail_codes.startswith(","):
        raise Unsupported(sec)   # 数字后的逗号：以千为单位缩放
    int_pat, _, dec_pat = body.partition(".")
    thousands = "," in int_pat
    int_pat = int_pat.replace(",", "")
    min_int = int_pat.count("0")
    max_dec = len(dec_pat)
    min_dec = len(dec_pat.rstrip("#"))
    v = Decimal(repr(abs(value))) * (Decimal(100) ** pct)
    q = v.quantize(Decimal(1).scaleb(-max_dec), rounding=ROUND_HALF_UP)
    s = f"{q:f}"
    ip, _, dp = s.partition(".")
    if max_dec:
        dp = dp[:max_dec]
        while len(dp) > min_dec and dp.endswith("0"):
            dp = dp[:-1]
    ip = ip.lstrip("0")
    ip = ip.rjust(min_int, "0") if min_int else ip
    if thousands and ip:
        ip = f"{int(ip):,}"
    num = ip + ("." + dp if dp else ("." if dec_pat and max_dec == 0 else ""))
    if not num or num == ".":
        num = "0" if min_int else ""
    sign = "-" if signed and value < 0 and q != 0 else ""
    before = "".join(t for k, t in parts[:a])
    after = "".join(t for k, t in parts[b + 1:])
    return sign + before + num + after


def _format_number(value: float, fmt: str) -> str:
    secs = [_clean(s) for s in _sections(fmt)]
    if value > 0 or len(secs) == 1:
        return _number(value, secs[0], signed=True)
    if value < 0:
        return _number(value, secs[1], signed=False) if len(secs) >= 2 else _number(value, secs[0], signed=True)
    return _number(value, secs[2] if len(secs) >= 3 else secs[0], signed=True)


# ---------- 日期、时间 ----------

def _format_datetime(value, fmt: str) -> str:
    sec = _clean(_sections(fmt)[0])
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        value = dt.datetime(value.year, value.month, value.day)
    if isinstance(value, dt.time):
        value = dt.datetime(1900, 1, 1, value.hour, value.minute, value.second, value.microsecond)
    ampm = bool(re.search(r"AM/PM|A/P", sec, re.I))
    sec = re.sub(r"AM/PM|A/P", "\0", sec, flags=re.I)
    items: list[tuple[str, str]] = []
    for k, t in _tokens(sec):
        if k == "lit" or t == "\0":
            items.append(("lit", t) if t != "\0" else ("ampm", ""))
            continue
        low = t.lower()
        if items and items[-1][0] == "code" and items[-1][1][0] == low and low in "ymdhs":
            items[-1] = ("code", items[-1][1] + low)
        elif low in "ymdhs":
            items.append(("code", low))
        elif t == "." or t.isdigit():
            raise Unsupported(fmt)   # 秒的小数等
        else:
            items.append(("lit", t))
    out = []
    codes = [i for i, (k, _) in enumerate(items) if k == "code"]
    for n, (k, t) in enumerate(items):
        if k == "lit":
            out.append(t)
            continue
        if k == "ampm":
            out.append("AM" if value.hour < 12 else "PM")
            continue
        if t in ("m", "mm"):
            prev = next((items[i][1] for i in reversed(codes) if i < n), "")
            nxt = next((items[i][1] for i in codes if i > n), "")
            minute = prev.startswith("h") or nxt.startswith("s")
            num = value.minute if minute else value.month
            out.append(f"{num:02d}" if t == "mm" else str(num))
        elif t == "yyyy" or t == "yyy":
            out.append(f"{value.year:04d}")
        elif t == "yy":
            out.append(f"{value.year % 100:02d}")
        elif t in ("d", "dd"):
            out.append(f"{value.day:02d}" if t == "dd" else str(value.day))
        elif t in ("h", "hh"):
            h = value.hour % 12 or 12 if ampm else value.hour
            out.append(f"{h:02d}" if t == "hh" else str(h))
        elif t in ("s", "ss"):
            out.append(f"{value.second:02d}" if t == "ss" else str(value.second))
        else:
            raise Unsupported(fmt)   # mmm、mmmm、ddd、dddd 等名称
    return "".join(out)


def format(value, fmt: str | None) -> str | None:  # noqa: A001 与 Excel 的术语一致
    """按数字格式套出显示文字；原始值写法就够的（常规）或套不出来的返回 None。"""
    if fmt is None or fmt == "General" or value is None or isinstance(value, (bool, str)):
        return None
    try:
        if isinstance(value, (dt.datetime, dt.date, dt.time)):
            return _format_datetime(value, fmt)
        if isinstance(value, (int, float)):
            if _sections(fmt)[0].strip() == "@":
                return None   # 文本格式：原样
            return _format_number(float(value), fmt)
    except (Unsupported, ValueError, ArithmeticError, IndexError):
        return None
    return None
