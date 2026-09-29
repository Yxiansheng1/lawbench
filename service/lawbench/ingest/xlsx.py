"""xlsx：openpyxl 读两遍——data_only=True 取显示值，data_only=False 取公式（Spec 5.2）。

显示值为空而公式不为空（文件没存计算结果）时，先用 LibreOffice 重算后再读显示值。
每个工作表转成带行号、列字母表头的 md 表格；公式单独存一份。
"""
from __future__ import annotations

import datetime as dt
import pathlib
import zipfile
from typing import Callable

import openpyxl
from openpyxl.utils import get_column_letter

from . import Block, Parsed, ParseError
from .detect import is_ole, ole_encrypted


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d") if v.time() == dt.time() else v.isoformat(sep=" ")
    if isinstance(v, (dt.date, dt.time)):
        return v.isoformat()
    return str(v).replace("\r\n", "\n").replace("|", "\\|").replace("\n", "<br>")


def _load(path: pathlib.Path, data_only: bool):
    try:
        return openpyxl.load_workbook(path, data_only=data_only, read_only=False)
    except (zipfile.BadZipFile, KeyError, OSError, ValueError, TypeError):
        raise ParseError("corrupt")
    except Exception:  # noqa: BLE001 openpyxl 对坏文件抛的异常种类很多
        raise ParseError("corrupt")


def _missing_cache(values, formulas) -> bool:
    for ws in formulas.worksheets:
        wv = values[ws.title]
        for row in ws.iter_rows():
            for c in row:
                if c.data_type == "f" and wv[c.coordinate].value is None:
                    return True
    return False


def parse(path: pathlib.Path, recalc: Callable[[pathlib.Path], pathlib.Path] | None = None,
          note: str | None = None) -> Parsed:
    """recalc(path) 用 LibreOffice 重算并返回重算后的 xlsx 路径（位于 工作区/临时/，调用方负责删除）。"""
    if is_ole(path):
        raise ParseError("encrypted" if ole_encrypted(path) else "corrupt")
    values = _load(path, True)
    formulas = _load(path, False)
    if recalc is not None and _missing_cache(values, formulas):
        values.close()
        values = _load(recalc(path), True)
    out = Parsed(unit="cell", unit_count=len(formulas.worksheets), count_word="个工作表", note=note)
    flist: list[str] = []
    for ws in formulas.worksheets:
        wv = values[ws.title]
        max_row, max_col = ws.max_row, ws.max_column
        rows: list[tuple[int, list[str]]] = []
        for r in range(1, max_row + 1):
            # 没有缓存值又没有重算（没有 LibreOffice，或文档有外链、不交给 LibreOffice）：只写公式
            cells = [_fmt(wv.cell(row=r, column=c).value)
                     or (_fmt(ws.cell(row=r, column=c).value) if ws.cell(row=r, column=c).data_type == "f" else "")
                     for c in range(1, max_col + 1)]
            if any(cells):
                rows.append((r, cells))
            for c in range(1, max_col + 1):
                fc = ws.cell(row=r, column=c)
                if fc.data_type == "f":
                    flist.append(f"{ws.title}!{fc.coordinate}\t{fc.value}")
        if rows:
            header = "| 行 | " + " | ".join(get_column_letter(c) for c in range(1, max_col + 1)) + " |"
            sep = "|---|" + "---|" * max_col
            body = [f"| {r} | " + " | ".join(cells) + " |" for r, cells in rows]
            text = "\n".join([header, sep, *body])
        else:
            text = "（空工作表）"
        out.blocks.append(Block(f"表:{ws.title}", text))
    values.close()
    formulas.close()
    out.formulas = "\n".join(flist) if flist else None
    return out
