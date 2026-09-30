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
    # 本机没开 Windows 长路径支持时，材料文本的路径（案件路径 + 工作区\材料\文本\ + 原件相对路径 + .md）超过 260 字符
    "path_too_long": "文件所在的文件夹层级太深、路径太长，无法处理；请把案件文件夹移到路径较短的位置（如 D:\\案件\\）后重新打开",
    # 注记 致B-ORCH-注记-LibreOffice三件事-20260929-2218 第 1 节
    "appdata_too_long": "软件的数据目录路径太长，无法转换；请联系技术支持",
    "converter_crashed": "转换程序异常退出，没有完成转换；请重试，多次出现请在 Word 或 WPS 中另存为 docx / xlsx 后放入案件文件夹",
    # Spec 14.3 ②a；措辞按注记 致B-ORCH-注记-doc外链图片要拒绝-20260929-2106
    "external_link": "文档里有指向外部地址的图片，为避免联网没有解析；请在 Word 或 WPS 里断开链接（或另存为 docx）后再导入",
    # T5 第一轮返修 X2：外链检查、加密判断出错时不放行
    "unchecked": "无法检查文件里有没有指向外部的链接，为避免联网没有解析；请在 Word、WPS 或 Excel 中另存为 docx / xlsx 后放入案件文件夹",
    # X8：被占用、没有读取权限
    "unreadable": "文件无法读取（可能正被其他程序占用，或没有读取权限）；关闭占用它的程序后重新打开案件会自动重试",
    # X9：超时、找不到转换程序原来都报 convert_failed，拆开后才能分出"跟环境有关、要重试"的
    "convert_timeout": "转换超时，没有完成转换；重新打开案件会自动重试，多次出现请在 Word、WPS 或 Excel 中另存为 docx / xlsx 后放入案件文件夹",
    "no_converter": "本机没有可用的转换程序，无法转换该文件；请联系技术支持，或在 Word、WPS 或 Excel 中另存为 docx / xlsx 后放入案件文件夹",
    # N44 ①（用户定）：扩展名是 .doc/.wps/.xls、内容其实是 HTML、RTF 等：不解析，文件本身的失败，不重试
    "not_office": "文件内容不是 Excel/Word 格式（常见于银行导出的表格），请用 Excel 或 Word 打开后另存为 .xlsx / .docx 再导入",
}

# X9：跟环境有关的失败，每次扫描都重试；其余（加密、过大、损坏、有外链被拒、无法检查、转换不出结果）
# 跟文件本身有关，原件没变就不重试
RETRY_REASONS = frozenset({"converter_crashed", "convert_timeout", "no_converter", "path_too_long",
                           "appdata_too_long", "unreadable"})
RETRY_MESSAGES = frozenset(REASONS[r] for r in RETRY_REASONS)

# X4：压缩包里单个部件解压后超过这个大小按"文件过大"，不解压（沿用 Spec 5.2"超大"的数）
MAX_PART_BYTES = MAX_BYTES
# X4：一个工作表写进材料文本的格子数上限（有内容的行数 × 列宽），超过按"文件过大"
MAX_SHEET_CELLS = 2_000_000
# T5 第二轮 B-P2-4：docx 建树之前先流式数 document.xml 里的段落，超过这个数按"文件过大"，不建树。
# 与格子数上限同一数量级；一个段落在 lxml 树里比一个单元格重得多，取格子数上限的四分之一
MAX_DOCX_PARAS = 500_000


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
