"""读材料文本（formats.md 第 2 节）：拆成位置单元，供 case_read_material、case_search、覆盖清单共用。

材料文本的路径不直接信 index.json 里的 text_path：先把 rel_path 按 AI 参数的同一套规则过闸门（证明它是原件区里
合法的相对路径），再由服务端自己拼出 工作区/材料/文本/<rel_path>.md，经 resolve_internal 读取
（返修令 2145 第 5 节：resolve_internal 不接收 AI 能影响的值）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..errors import ApiError
from . import gate

TEXT_DIR = "工作区/材料/文本"
# 位置标记只认我方写的几种（formats.md 第 2 节），且必须独占一行、按材料的定位方式只认对应的一种：
# 材料原文里以【开头的行（微信、短信导出的"【2025-03-10 21:14】周立新：…"）一律是正文（注记 20261001-1221）
_MARKS = {
    "page": re.compile(r"^【(第[0-9]+页)】(?:\n|$)", re.M),
    "para": re.compile(r"^【(第[0-9]+段)】(?:\n|$)", re.M),
    "line": re.compile(r"^【(第[0-9]+行)】(?:\n|$)", re.M),
    "cell": re.compile(r"^【(表:[^\n]+)】(?:\n|$)", re.M),
}
_NUM = re.compile(r"^第(\d+)(页|段|行)$")


@dataclass
class Unit:
    """一个可定位的单元：页 / 段 / 行 / 表格行（Excel）。"""
    no: int            # 页号、段号、行号；Excel 为全材料内的表格行序号（从 1 起，跨工作表连续）
    text: str          # 这一单元的原文
    header: str        # 页、段：本单元的位置标记；行：块首那一行的"【第N行】"，其余为空；Excel：该表的表头两行
    sheet: str | None = None
    row: int | None = None      # Excel：工作表内的行号
    is_ocr: bool = False        # 识别所得（页首有 "> 识别所得"）


def text_rel(material: dict) -> str:
    gate.check_ai_rel(material["rel_path"], op="material_text")
    return f"{TEXT_DIR}/{material['rel_path']}.md"


def read_text(root: str, material: dict) -> str:
    path = gate.resolve_internal(root, text_rel(material), op="material_text")
    if not path.is_file():
        raise ApiError("MATERIAL_NOT_READY", "text_missing")
    return path.read_text(encoding="utf-8")


def split_units(text: str, unit: str) -> list[Unit]:
    mark = _MARKS.get(unit)
    if mark is None:
        return []
    parts = mark.split(text)
    out: list[Unit] = []
    for i in range(1, len(parts), 2):
        label, body = parts[i], parts[i + 1].rstrip("\n")
        m = _NUM.match(label)
        if unit in ("page", "para") and m:
            out.append(Unit(int(m.group(1)), body, f"【{label}】", is_ocr=body.startswith("> 识别所得")))
        elif unit == "line" and m:
            start = int(m.group(1))
            for k, line in enumerate(body.split("\n")):
                out.append(Unit(start + k, line, f"【第{start + k}行】" if k == 0 else ""))
        elif unit == "cell" and label.startswith("表:"):
            sheet = label[2:]
            lines = body.split("\n")
            head = "\n".join(lines[:2]) if len(lines) >= 2 and lines[1].startswith("|---") else ""
            for line in lines[2:] if head else lines:
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                row = int(cells[0]) if cells and cells[0].isdigit() else None
                if row is None:
                    continue
                out.append(Unit(len(out) + 1, line, head, sheet=sheet, row=row))
    return out


PENDING_OCR = "（本页需识别）"


def readable(units: list[Unit]) -> bool:
    """至少有一个单元不是"本页需识别"的占位。"""
    return any(u.text.strip() != PENDING_OCR for u in units)


def render(units: list[Unit], unit: str) -> str:
    """把一串连续单元还原成带位置标记的文本（formats.md 第 2 节的写法）。"""
    out: list[str] = []
    prev_sheet = None
    for i, u in enumerate(units):
        if unit in ("page", "para"):
            out.append(f"{u.header}\n{u.text}" if u.text else u.header)
        elif unit == "line":
            # 每行都标行号（T18 实测：只在块首标时模型要自己数行，常差一行，出处核对报 B 类）；存储文件仍按 formats.md 每 50 行一标
            out.append(f"【第{u.no}行】\n{u.text}")
        else:
            if u.sheet != prev_sheet:
                out.append(f"【表:{u.sheet}】\n{u.header}\n{u.text}" if u.header else f"【表:{u.sheet}】\n{u.text}")
                prev_sheet = u.sheet
            else:
                out.append(u.text)
    sep = "\n\n" if unit in ("page", "para") else "\n"
    return sep.join(out)


def total_units(units: list[Unit]) -> int:
    return len(units)
