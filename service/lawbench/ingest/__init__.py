"""材料解析（Spec 5.2–5.4）。

每个解析器把原件读成 Parsed：位置单位 + 一串"位置块"（页 / 段 / 行 / 工作表），由 case/materials.py
按 contracts/formats.md 第 2 节渲染成材料文本。解析器只读原件，不写案件文件夹以外的任何地方；
需要中间文件的（LibreOffice 转换）只写 工作区/临时/，用完即删。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 阈值（Spec 5.2 "无法处理的文件"、5.4 页面类型判断；用 G-8 样本校准）
PDF_MIN_CHARS = 30           # 可提取文字少于这么多字 → 需识别
PDF_MIXED_IMAGE_RATIO = 0.30  # 文字够、图片面积超过页面这个比例 → 图文混排
MAX_BYTES = 300 * 1024 * 1024
MAX_PAGES = 2000
LO_TIMEOUT = 120

REASONS = {
    "encrypted": "文件已加密，请提供未加密版本",
    "corrupt": "文件无法打开，可能已损坏",
    "too_large": "文件过大，请拆分后导入",
    "convert_failed": "无法转换该文件，请在 Word、WPS 或 Excel 中另存为 docx / xlsx 后放入案件文件夹",
}


class ParseError(Exception):
    """解析失败；reason 为 REASONS 的键，写进 index.json 的是对应中文。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason

    @property
    def message(self) -> str:
        return REASONS[self.reason]


@dataclass
class Block:
    """一个位置块。label 是位置标记里的内容（如 "第3页"、"表:流水"）。"""
    label: str
    text: str
    ocr_pending: bool = False


@dataclass
class Parsed:
    unit: str                      # page / para / cell / line
    unit_count: int
    count_word: str                # Source 行里的量词：页 / 段 / 行 / 个工作表
    blocks: list[Block] = field(default_factory=list)
    pages_need_ocr: list[int] = field(default_factory=list)
    pages_mixed: list[int] = field(default_factory=list)
    note: str | None = None
    formulas: str | None = None    # Excel 公式清单（单独存一份）
