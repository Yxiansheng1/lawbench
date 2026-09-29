"""格式互转（Spec 13.2）：每种转换一个样本成功、原文件 sha256 不变；找不到程序时给中文提示。"""
from __future__ import annotations

import shutil
import subprocess
import zipfile

import pytest

from conftest import FIXTURES, sha256
from convert import core, finder

SOFFICE = finder.find_soffice()
PANDOC = finder.find_pandoc()
need_lo = pytest.mark.skipif(SOFFICE is None, reason="本机没有 LibreOffice")
need_pandoc = pytest.mark.skipif(PANDOC is None, reason="本机没有 pandoc")


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    """把 tests\\fixtures 的样本复制出来；doc、wps、xls 由 LibreOffice 从 docx / xlsx 转出。"""
    d = tmp_path_factory.mktemp("convert-src")
    m = {
        "docx": FIXTURES / "civil-01" / "借条.docx",
        "md": FIXTURES / "civil-01" / "案情摘要.md",
        "pdf": FIXTURES / "criminal-01" / "起诉意见书.pdf",
        "scan": FIXTURES / "criminal-01" / "讯问笔录.pdf",
        "jpg": FIXTURES / "criminal-01" / "转账截图.jpg",
        "xlsx": FIXTURES / "civil-01" / "银行流水.xlsx",
    }
    out = {}
    for k, p in m.items():
        out[k] = d / p.name
        shutil.copyfile(p, out[k])
    if SOFFICE:
        legacy = tmp_path_factory.mktemp("legacy")
        profile = (legacy / "profile").as_uri()
        for src, fmt in ((out["docx"], "doc"), (out["xlsx"], "xls")):
            subprocess.run([str(SOFFICE), "--headless", "--norestore", f"-env:UserInstallation={profile}",
                            "--convert-to", fmt, "--outdir", str(d), str(src)], check=True, timeout=180,
                           capture_output=True)
        out["doc"] = d / "借条.doc"
        out["xls"] = d / "银行流水.xls"
        # WPS 文字的 .wps 与 .doc 同为 OLE 复合文档，LibreOffice 按内容识别；这里用 .doc 改扩展名代替
        out["wps"] = d / "借条-wps.wps"
        shutil.copyfile(out["doc"], out["wps"])
    return out


def check_unchanged_and_clean(src, before):
    assert sha256(src) == before
    # 源文件所在目录只多出"转换结果"文件夹，没有锁文件、临时文件
    extras = [p.name for p in src.parent.iterdir() if p.name.startswith((".~lock", "~$", "lawbench-convert"))]
    assert extras == []


CASES = [
    pytest.param("doc2docx", "doc", marks=need_lo, id="doc→docx"),
    pytest.param("doc2docx", "wps", marks=need_lo, id="wps→docx"),
    pytest.param("xls2xlsx", "xls", marks=need_lo, id="xls→xlsx"),
    pytest.param("word2pdf", "docx", marks=need_lo, id="docx→pdf"),
    pytest.param("word2pdf", "doc", marks=need_lo, id="doc→pdf"),
    pytest.param("pdf2docx", "pdf", marks=need_pandoc, id="pdf→docx"),
    pytest.param("md2docx", "md", marks=need_pandoc, id="md→docx"),
    pytest.param("docx2md", "docx", marks=need_pandoc, id="docx→md"),
    pytest.param("img2pdf", "jpg", id="jpg→pdf"),
]


@pytest.mark.parametrize("kind,sample", CASES)
def test_each_conversion(samples, kind, sample):
    src = samples[sample]
    before = sha256(src)
    out = core.convert_file(kind, src)
    assert out.is_file() and out.parent == src.parent / core.OUT_DIR_NAME
    assert out.suffix == core.BY_KEY[kind].output
    assert_valid_output(out)
    check_unchanged_and_clean(src, before)


def assert_valid_output(out):
    if out.suffix == ".docx":
        from docx import Document
        text = "".join(p.text for p in Document(out).paragraphs)
        assert len(text) > 10
    elif out.suffix == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(out)
        assert "流水" in wb.sheetnames
    elif out.suffix == ".pdf":
        import pypdfium2 as pdfium
        assert len(pdfium.PdfDocument(str(out))) >= 1
    elif out.suffix == ".md":
        assert "借" in out.read_text(encoding="utf-8")
    with open(out, "rb") as f:
        head = f.read(4)
    if out.suffix in (".docx", ".xlsx"):
        assert zipfile.is_zipfile(out) and head.startswith(b"PK")


@need_pandoc
def test_pdf_to_word_keeps_text_and_paragraphs(samples):
    from docx import Document
    out = core.convert_file("pdf2docx", samples["pdf"])
    paras = [p.text for p in Document(out).paragraphs if p.text.strip()]
    joined = "".join(paras)
    assert "虚公刑诉字〔2026〕417号" in joined
    assert "骗取他人财物共计人民币126,500元" in joined.replace("\n", "")
    assert len(paras) >= 10                         # 按段落组织，不是整页一段


@need_pandoc
def test_scanned_pdf_refused(samples):
    before = sha256(samples["scan"])
    with pytest.raises(core.ConvertError, match="扫描件"):
        core.convert_file("pdf2docx", samples["scan"])
    assert sha256(samples["scan"]) == before


def test_same_name_gets_suffix(samples, tmp_path):
    src = tmp_path / samples["jpg"].name
    shutil.copyfile(samples["jpg"], src)
    a = core.convert_file("img2pdf", src)
    b = core.convert_file("img2pdf", src)
    assert a.name == f"{src.stem}.pdf" and b.name == f"{src.stem}(2).pdf"


def test_wrong_extension_and_batch(samples, tmp_path):
    with pytest.raises(core.ConvertError, match="不是这种转换能处理的格式"):
        core.convert_file("xls2xlsx", samples["md"])
    res = core.convert_many("img2pdf", [samples["jpg"], tmp_path / "不存在.png"])
    assert res[0][1].suffix == ".pdf" and "不存在" in res[1][1]


def test_missing_programs_chinese_message(samples, monkeypatch):
    monkeypatch.setattr(finder, "find_soffice", lambda: None)
    monkeypatch.setattr(finder, "find_pandoc", lambda: None)
    with pytest.raises(core.ConvertError, match="没有找到 LibreOffice"):
        core.convert_file("word2pdf", samples["docx"])
    with pytest.raises(core.ConvertError, match="没有找到 pandoc"):
        core.convert_file("md2docx", samples["md"])
    assert not (samples["md"].parent / core.OUT_DIR_NAME / "案情摘要(9).docx").exists()


def test_finder_order(tmp_path, monkeypatch):
    fake_client = tmp_path / "local"
    exe = fake_client / "Programs" / "lawbench" / "resources" / "libreoffice" / "program" / "soffice.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    pan = fake_client / "Programs" / "lawbench" / "resources" / "pandoc" / "pandoc.exe"
    pan.parent.mkdir(parents=True)
    pan.write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(fake_client))
    monkeypatch.delenv("LAWBENCH_SOFFICE", raising=False)
    assert finder.find_soffice() == exe                 # 客户端内置优先于系统安装
    assert finder.find_pandoc() == pan
    override = tmp_path / "my-soffice.exe"
    override.write_bytes(b"")
    monkeypatch.setenv("LAWBENCH_SOFFICE", str(override))
    assert finder.find_soffice() == override            # 环境变量最先


def test_gui_builds():
    import tkinter as tk
    from convert.app import ConvertApp
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("没有图形界面环境")
    root.withdraw()
    app = ConvertApp(root)
    app.kind.set(core.BY_KEY["pdf2docx"].label)
    app._update_note()
    assert "只保留文字和段落" in app.note["text"]
    root.destroy()
