"""格式互转（Spec 13.2）：每种转换一个样本成功、原文件 sha256 不变；找不到程序时给中文提示。"""
from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

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
    import tempfile
    assert sha256(src) == before
    # 源文件所在目录没有锁文件、临时文件
    extras = [p.name for p in src.parent.iterdir() if p.name.startswith((".~lock", "~$"))]
    assert extras == []
    # 系统临时目录里没有本工具留下的工作目录（复核 P2-1：原先查错了目录）
    left = [p.name for p in Path(tempfile.gettempdir()).glob(core.TEMP_PREFIX + "*")]
    assert left == [], left


@pytest.fixture(autouse=True)
def isolated_temp(tmp_path, monkeypatch):
    """每个测试用自己的系统临时目录，才能断言"没有留下 lawbench-convert-*"。"""
    import tempfile
    t = tmp_path / "systemp"
    t.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(t))
    return t


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


def _alive(pid: int) -> bool:
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                       encoding="mbcs", errors="replace")
    return str(pid) in r.stdout


def test_hung_converter_killed_with_children(samples, tmp_path, monkeypatch):
    """转换程序卡住（例如弹出"等待打印机连接"）：到超时结束它和它启动的子进程，给中文原因，原文件不动。"""
    import sys
    import time
    pidfile = tmp_path / "pids.txt"
    script = tmp_path / "hang.py"
    script.write_text(
        "import os, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
        f"open(r'{pidfile}', 'w').write(f'{{os.getpid()}} {{child.pid}}')\n"
        "time.sleep(600)\n", encoding="utf-8")
    fake = tmp_path / "soffice.cmd"
    fake.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="mbcs")
    monkeypatch.setattr(core, "_soffice", lambda: fake)
    monkeypatch.setattr(core, "TIMEOUT_S", 3)
    before = sha256(samples["docx"])
    t0 = time.time()
    with pytest.raises(core.ConvertError, match="转换超时"):
        core.convert_file("word2pdf", samples["docx"])
    assert time.time() - t0 < 30
    pids = [int(x) for x in pidfile.read_text().split()]
    time.sleep(0.5)
    assert not any(_alive(p) for p in pids), "卡住的转换程序或其子进程还在"
    check_unchanged_and_clean(samples["docx"], before)


def test_no_print_calls_in_converter():
    src = (core.__file__)
    text = open(src, encoding="utf-8").read()
    for bad in ("PrintOut", "print_to", "-p ", "--print-to-file", "--pt ", "SetDefaultPrinter"):
        assert bad not in text


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


# ---------------------------------------------------------------- 不联网（复核 P1-1）

@pytest.fixture
def listener():
    """本机 127.0.0.1 随机端口的 HTTP 监听，记录收到的请求数。"""
    import http.server
    import threading
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(_png())

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1], hits
    srv.shutdown()


def _png() -> bytes:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 0, 0)).save(buf, "PNG")
    return buf.getvalue()


def _docx_with_external_image(path, url):
    """docx 里一张以外部链接引用（r:link、TargetMode=External）的图片。"""
    import io
    import re
    from docx import Document
    doc = Document()
    doc.add_paragraph("外部链接图片测试（虚构）")
    doc.add_picture(io.BytesIO(_png()))
    tmp = path.with_suffix(".tmp.docx")
    doc.save(tmp)
    with zipfile.ZipFile(tmp) as zin, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = data.replace(b'r:embed="', b'r:link="')
            elif item.filename == "word/_rels/document.xml.rels":
                data = re.sub(rb'Target="media/image1\.png"', f'Target="{url}" TargetMode="External"'.encode(), data)
            zout.writestr(item, data)
    tmp.unlink()


@need_lo
@need_pandoc
def test_conversions_do_not_fetch_remote_resources(tmp_path, listener):
    port, hits = listener
    md = tmp_path / "远程图片.md"
    md.write_text(f"# 测试\n\n![图](http://127.0.0.1:{port}/md.png)\n\n正文（虚构）\n", encoding="utf-8")
    dx = tmp_path / "外链图片.docx"
    _docx_with_external_image(dx, f"http://127.0.0.1:{port}/docx.png")
    core.convert_file("md2docx", md)
    core.convert_file("word2pdf", dx)
    core.convert_file("docx2md", dx)
    assert hits == [], f"转换时访问了网络：{hits}"


@need_lo
@pytest.mark.xfail(strict=True, reason="已知：LibreOffice 导入 .doc 时仍会取外链图片，配置项挡不住；已报主编排")
def test_doc_with_external_image_does_not_fetch(tmp_path, listener):
    port, hits = listener
    dx = tmp_path / "外链图片.docx"
    _docx_with_external_image(dx, f"http://127.0.0.1:{port}/docx.png")
    doc = _as_doc(dx, tmp_path)
    assert hits == []                     # 另存 .doc 这一步本身不联网
    core.convert_file("doc2docx", doc)
    assert hits == [], f"转换时访问了网络：{hits}"


def _as_doc(dx, tmp_path):
    """用 LibreOffice 把带外链图片的 docx 另存为 doc（配置同样禁止取外链）。"""
    work = tmp_path / "mkdoc"
    work.mkdir()
    out = core._libreoffice(dx, "doc", work)
    dst = tmp_path / "外链图片.doc"
    shutil.copyfile(out, dst)
    return dst


# ---------------------------------------------------------------- 复核 P1-2、P1-3、P3-5、(e)

def test_batch_survives_unexpected_errors(samples, tmp_path, monkeypatch):
    """批量中间夹一个文件夹和一个超大图：各自给中文原因，前后文件照常转换。"""
    from PIL import Image
    folder = tmp_path / "只读文件夹.png"
    folder.mkdir()
    big = tmp_path / "超大图.png"
    Image.new("RGB", (3000, 3000)).save(big)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 2_000_000)   # 900 万像素 > 2 倍上限，触发"图片过大"
    res = core.convert_many("img2pdf", [samples["jpg"], folder, big, samples["jpg"]])
    assert isinstance(res[0][1], Path) and isinstance(res[3][1], Path)
    for _, r, _ in res[1:3]:
        assert isinstance(r, str) and not any(w in r for w in ("Error", "Traceback", "Exception"))


def test_unexpected_exception_becomes_chinese_reason(samples, monkeypatch):
    def boom(kind, src):
        raise RuntimeError("内部细节 xyz")
    monkeypatch.setattr(core, "convert_file_ex", boom)
    res = core.convert_many("img2pdf", [samples["jpg"]])
    assert res[0][1] == core.INTERNAL and "xyz" not in res[0][1]


def test_failure_and_timeout_leave_no_workdir(samples, tmp_path, monkeypatch):
    bad = tmp_path / "坏.pdf"
    bad.write_bytes(b"%PDF-1.4 broken")
    with pytest.raises(core.ConvertError):
        core.convert_file("pdf2docx", bad)
    check_unchanged_and_clean(bad, sha256(bad))
    import sys
    fake = tmp_path / "soffice.cmd"
    fake.write_text(f'@"{sys.executable}" -c "import time; time.sleep(60)" %*\n', encoding="mbcs")
    monkeypatch.setattr(core, "_soffice", lambda: fake)
    monkeypatch.setattr(core, "TIMEOUT_S", 2)
    with pytest.raises(core.ConvertError, match="转换超时"):
        core.convert_file("word2pdf", samples["docx"])
    check_unchanged_and_clean(samples["docx"], sha256(samples["docx"]))


def test_cleanup_stale_only_old_own_dirs(isolated_temp, tmp_path):
    import os
    import time
    old = isolated_temp / (core.TEMP_PREFIX + "old")
    old.mkdir()
    (old / "src.docx").write_bytes(b"x")
    fresh = isolated_temp / (core.TEMP_PREFIX + "fresh")
    fresh.mkdir()
    other = isolated_temp / "other-old"
    other.mkdir()
    afile = isolated_temp / (core.TEMP_PREFIX + "file")
    afile.write_bytes(b"x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_bytes(b"x")
    link = isolated_temp / (core.TEMP_PREFIX + "junction")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
    past = time.time() - 3600
    for p in (old, other, afile):
        os.utime(p, (past, past))
    assert core.cleanup_stale() == 1
    assert not old.exists() and fresh.exists() and other.exists() and afile.exists()
    assert link.exists() and (outside / "keep.txt").exists()
    os.rmdir(link)


@need_pandoc
def test_mixed_pdf_reports_scan_pages(samples, tmp_path):
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    for f in (samples["pdf"], samples["scan"]):
        for pg in PdfReader(f).pages[:2]:
            w.add_page(pg)
    mixed = tmp_path / "混合.pdf"
    with open(mixed, "wb") as fh:
        w.write(fh)
    res = core.convert_many("pdf2docx", [mixed])
    _, out, notes = res[0]
    assert isinstance(out, Path)
    assert notes == ["第 3 页是扫描页，没有转出文字", "第 4 页是扫描页，没有转出文字"]


def test_gui_notes_and_close_guard(monkeypatch):
    import tkinter as tk
    from convert.app import ConvertApp
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("没有图形界面环境")
    root.withdraw()
    app = ConvertApp(root)
    for key in ("md2docx", "docx2md"):
        app.kind.set(core.BY_KEY[key].label)
        app._update_note()
        assert "不保留图片" in app.note["text"]
    shown = []
    monkeypatch.setattr("convert.app.messagebox.showinfo", lambda *a: shown.append(a))
    app.busy = True
    app.on_close()
    assert shown and root.winfo_exists()        # 转换中不关窗
    app.busy = False
    app.on_close()
