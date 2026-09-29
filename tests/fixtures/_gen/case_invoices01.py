"""invoices-01：5 张虚构电子发票 PDF 和 1 个装着其中 2 张的 ZIP。

版式参照 engines\\invoice-ledger\\scripts\\tests\\ 的合成方法：横排文字版，
"发票号码：<20位>""开票日期：YYYY年MM月DD日""购买方名称：…""价税合计（大写）…（小写）￥…"。
购买方为虚构律所"某某虚构律师事务所"；发票04 与发票01 重复（号码、金额、日期均相同）；
发票05 购买方不符。
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import common as C

CASE = "invoices-01"
FEAT = C.FEATURE[CASE]
BUYER = "某某虚构律师事务所"
BUYER_ID = "91999900MA0LBFX001"

INVOICES = [
    # 文件名, 号码, 日期, 购买方, 销售方, 项目, 金额(价税合计), 大写
    ("发票01-办公用品.pdf", "26999000000000410001", "2026年08月03日", BUYER, "虚构市某某文具有限公司",
     "*文具*打印纸", "356.00", "叁佰伍拾陆元整"),
    ("发票02-差旅住宿.pdf", "26999000000000410002", "2026年08月11日", BUYER, "虚构市某某酒店有限公司",
     "*住宿服务*住宿费", "1280.00", "壹仟贰佰捌拾元整"),
    ("发票03-交通.pdf", "26999000000000410003", "2026年08月12日", BUYER, "虚构市某某出行科技有限公司",
     "*运输服务*客运服务费", "86.50", "捌拾陆元伍角"),
    ("发票04-办公用品-重复.pdf", "26999000000000410001", "2026年08月03日", BUYER, "虚构市某某文具有限公司",
     "*文具*打印纸", "356.00", "叁佰伍拾陆元整"),
    ("发票05-购买方不符.pdf", "26999000000000410005", "2026年08月20日", "某某虚构科技有限公司",
     "虚构市某某餐饮管理有限公司", "*餐饮服务*餐费", "420.00", "肆佰贰拾元整"),
]
ZIP_NAME = "邮件附件-发票两张.zip"
ZIP_MEMBERS = ["发票02-差旅住宿.pdf", "发票03-交通.pdf"]

FILES = [i[0] for i in INVOICES] + [ZIP_NAME]


def invoice_text(no, date, buyer, seller, item, amount, upper) -> str:
    buyer_id = BUYER_ID if buyer == BUYER else "91999900MA0XXXX002"
    return f"""电子发票（普通发票）
发票号码：{no}
开票日期：{date}
购买方名称：{buyer}　统一社会信用代码/纳税人识别号：{buyer_id}
销售方名称：{seller}　统一社会信用代码/纳税人识别号：91999900MA0SELL003
项目名称：{item}　数量：1　金额：{amount}　税率：免税
价税合计（大写）{upper}　（小写）￥{amount}
备注：{FEAT}
开票人：虚构开票员"""


def build(root: Path) -> None:
    d = root / CASE
    d.mkdir(parents=True, exist_ok=True)
    for name, *fields in INVOICES:
        C.text_pdf(d / name, [invoice_text(*fields)], FEAT)
    with zipfile.ZipFile(d / ZIP_NAME, "w", zipfile.ZIP_DEFLATED) as z:
        for m in ZIP_MEMBERS:
            info = zipfile.ZipInfo(m, date_time=(2026, 8, 15, 10, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.flag_bits |= 0x800  # 文件名 UTF-8
            z.writestr(info, (d / m).read_bytes())
