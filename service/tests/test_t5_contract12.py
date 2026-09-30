"""T5 与契约 1.2（执行令 契约1.2其余各项-20260930-1134、T5返修补X13显示值-20260930-1140）：X13、N21、N26、N28。"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sqlite3

import openpyxl
import pytest

from lawbench.case import materials as mat_mod
from lawbench.config import REPO_ROOT
from lawbench.ingest import numfmt, xlsx

from fakes import CountingListener, linked_image_xlsx

FIXTURES = REPO_ROOT / "tests" / "fixtures"


def open_scan(client, root: pathlib.Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    cid = client.post("/api/case/open", json={"path": str(root)}).json()["value"]["case_id"]
    r = client.post("/api/materials/scan", json={"case_id": cid}).json()
    assert r["ok"], r
    idx = json.loads((root / "工作区" / "材料" / "index.json").read_text(encoding="utf-8"))
    return {m["rel_path"]: m for m in idx["materials"]}, cid


# ---------- X13：按显示值写 ----------

@pytest.mark.parametrize("value,fmt,shown", [
    (0.125, "0.00%", "12.50%"),                                      # 百分比
    (0.5, "0%", "50%"),
    (1234.5, "#,##0.00", "1,234.50"),                                # 千分位、固定小数位
    (80000, "#,##0", "80,000"),
    (3.14159, "0.000", "3.142"),
    (dt.datetime(2025, 3, 10), "yyyy-mm-dd", "2025-03-10"),          # 日期
    (dt.datetime(2025, 3, 10), 'yyyy"年"m"月"d"日"', "2025年3月10日"),
    (dt.datetime(2025, 3, 10, 14, 5), "yyyy/m/d h:mm", "2025/3/10 14:05"),
    (-1234.5, r'_(* #,##0.00_);_(* \(#,##0.00\);_(* "-"??_);_(@_)', "(1,234.50)"),   # 会计负数
    (0, r'_(* #,##0.00_);_(* \(#,##0.00\);_(* "-"??_);_(@_)', "-"),                  # 会计零值
    (-50, '"¥"#,##0.00;"¥"-#,##0.00', "¥-50.00"),                    # 货币
    (1234.5, "[$¥-804]#,##0.00", "¥1,234.50"),
    (-3, "0;[Red]-0", "-3"),
])
def test_x13_numfmt(value, fmt, shown):
    assert numfmt.format(value, fmt) == shown


@pytest.mark.parametrize("value,fmt", [(1.5, "0.00E+00"), (0.5, "# ?/?"), (1234567, "#,##0,"),
                                       (dt.datetime(2025, 3, 10), "d-mmm-yy"), (12, "@"), (1.5, "General")])
def test_x13_unsupported_or_general_falls_back(value, fmt):
    assert numfmt.format(value, fmt) is None


def test_x13_xlsx_written_as_displayed(tmp_path):
    p = tmp_path / "格式.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "表"
    rows = [("利率", 0.125, "0.00%"), ("本金", 1234.5, "#,##0.00"), ("日期", dt.datetime(2025, 3, 10), "yyyy-mm-dd"),
            ("亏损", -1234.5, r'_(* #,##0.00_);_(* \(#,##0.00\);_(* "-"??_);_(@_)'), ("编号", 12, "@"),
            ("文字", "0012", "@"), ("常规", 1234.5, "General")]
    for i, (k, v, f) in enumerate(rows, 1):
        ws.cell(row=i, column=1, value=k)
        c = ws.cell(row=i, column=2, value=v)
        c.number_format = f
    wb.save(p)
    text = xlsx.parse(p).blocks[0].text
    for line in ("| 1 | 利率 | 12.50% |", "| 2 | 本金 | 1,234.50 |", "| 3 | 日期 | 2025-03-10 |",
                 "| 4 | 亏损 | (1,234.50) |", "| 5 | 编号 | 12 |", "| 6 | 文字 | 0012 |", "| 7 | 常规 | 1234.5 |"):
        assert line in text, (line, text)


def test_x13_format_version_triggers_reparse(make_client, cases_dir):
    """原件没变，材料文本格式版本是旧的：重新解析（Excel、PDF、图片）；其他格式不动。"""
    client = make_client()
    root = cases_dir / "x13v"
    root.mkdir()
    for n in ("银行流水.xlsx", "情况说明.txt"):
        src = FIXTURES / "civil-01" / n
        (root / n).write_bytes(src.read_bytes())
    mats, cid = open_scan(client, root)
    status = root / "工作区" / "材料" / "_处理状态.md"
    assert f"材料文本格式版本：{mat_mod.TEXT_FORMAT_VERSION}" in status.read_text(encoding="utf-8")
    xt = root / mats["银行流水.xlsx"]["text_path"]
    tt = root / mats["情况说明.txt"]["text_path"]
    xt.write_text("旧格式", encoding="utf-8")
    tt.write_text("旧格式", encoding="utf-8")
    status.write_text(status.read_text(encoding="utf-8").replace("材料文本格式版本：", "旧："), encoding="utf-8")
    r = client.post("/api/materials/scan", json={"case_id": cid}).json()["value"]
    assert r["changed"] == 0 and r["added"] == 0
    assert xt.read_text(encoding="utf-8") != "旧格式"               # Excel 按新格式重写
    assert tt.read_text(encoding="utf-8") == "旧格式"               # 文本文件不受影响
    xt.write_text("又改了", encoding="utf-8")
    client.post("/api/materials/scan", json={"case_id": cid})
    assert xt.read_text(encoding="utf-8") == "又改了"               # 版本已是新的：原件没变不再重写


# ---------- N21：有外链、没重算的 xlsx 写上 note ----------

def test_n21_external_note(make_client, cases_dir):
    with CountingListener() as lis:
        root = cases_dir / "n21"
        root.mkdir()
        linked_image_xlsx(root / "报表.xlsx", lis.url)
        mats, _ = open_scan(make_client(), root)
        assert lis.count == 0
    m = mats["报表.xlsx"]
    assert m["status"] == "parsed" and m["note"] == "有外部链接，未重算公式"
    assert "> Note: 有外部链接，未重算公式" in (root / m["text_path"]).read_text(encoding="utf-8")


def test_n21_no_note_when_nothing_to_recalc(tmp_path):
    p = tmp_path / "a.xlsx"
    wb = openpyxl.Workbook()
    wb.active["A1"] = 1
    wb.save(p)
    assert xlsx.parse(p, recalc=None, blocked_note="有外部链接，未重算公式").note is None


# ---------- N28：整份待识别 ----------

def test_n28_source_pending_ocr(make_client, cases_dir):
    root = cases_dir / "n28"
    root.mkdir()
    img = next(FIXTURES.rglob("*.png"), None) or next(FIXTURES.rglob("*.jpg"))
    (root / ("扫描" + img.suffix)).write_bytes(img.read_bytes())
    (root / "借条.docx").write_bytes((FIXTURES / "civil-01" / "借条.docx").read_bytes())
    mats, _ = open_scan(make_client(), root)
    scan_text = (root / mats["扫描" + img.suffix]["text_path"]).read_text(encoding="utf-8")
    assert "（待识别，1页）" in scan_text
    doc_text = (root / mats["借条.docx"]["text_path"]).read_text(encoding="utf-8")
    assert "（文字版，" in doc_text
