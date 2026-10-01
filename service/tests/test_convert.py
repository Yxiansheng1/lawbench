"""Word 转 PDF 的调度（Spec 12.3、14.3；工单 T23 第 1 步与两条补充）。

开发机装有 Word（没有 WPS）；用例默认不动真 Word：调度、超时、杀进程用假 COM 子进程（fake_com_worker.py）测，
LibreOffice 真跑。真 Word 实测另见 docs/plan/evidence/T23/printer.txt（LAWBENCH_REAL_WORD=1 时本文件最后一条也跑）。
"""
from __future__ import annotations

import http.server
import io
import os
import pathlib
import shutil
import sys
import threading
import time
import zipfile

import docx as pydocx
import pytest
from PIL import Image
from pypdf import PdfReader

from lawbench.case import gate
from lawbench.errors import ApiError
from lawbench.ingest import libreoffice as lo
from lawbench.office import convert as C

from conftest import short_dir

FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "tests" / "fixtures"
COMPLAINT = FIXTURES / "closed-01" / "03一审" / "我方文件" / "民事起诉状.docx"
HAS_LO = lo.find_soffice() is not None
needs_lo = pytest.mark.skipif(not HAS_LO, reason="本机没有 LibreOffice")


@pytest.fixture
def case(tmp_path):
    root = tmp_path / "案件"
    (root / "工作区" / "临时").mkdir(parents=True)
    gate.mkdir_work(str(root), "工作区/临时/j")
    return root


@pytest.fixture
def lo_base():
    with short_dir("lblo-") as d:
        yield pathlib.Path(d)


@pytest.fixture
def fake(tmp_path, monkeypatch):
    log, pids = tmp_path / "com.log", tmp_path / "com.pids"
    log.write_text("", encoding="utf-8")
    pids.write_text("", encoding="utf-8")
    monkeypatch.setattr(C, "WORKER_CMD", [sys.executable, str(pathlib.Path(__file__).with_name("fake_com_worker.py"))])
    monkeypatch.setenv("FAKE_COM_LOG", str(log))
    monkeypatch.setenv("FAKE_COM_PIDS", str(pids))
    monkeypatch.setattr(C, "QUIT_WAIT", 0.5)

    class F:
        def calls(self):
            return log.read_text(encoding="utf-8").split()

        def pids(self):
            return [int(x) for x in pids.read_text(encoding="utf-8").split()]

        def set(self, **modes):
            for k, v in modes.items():
                monkeypatch.setenv(f"FAKE_COM_{k.upper()}", v)
    return F()


def pages(p: pathlib.Path) -> int:
    return len(PdfReader(str(p)).pages)


# ---------------------------------------------------------------- 调度

@needs_lo
def test_libreoffice_real(case, lo_base):
    out, used = C.OfficeConverter(lo_base).to_pdf(str(case), COMPLAINT, "工作区/临时/j", "libreoffice")
    assert used == "libreoffice" and pages(out) >= 1
    assert out.parent.parent == case / "工作区" / "临时" / "j"           # 只在本次的临时目录里
    assert sorted(p.name for p in out.parent.iterdir()) == ["in.docx", "out.pdf"]


def test_word_ok_is_first(case, lo_base, fake):
    fake.set(word="ok")
    out, used = C.OfficeConverter(lo_base).to_pdf(str(case), COMPLAINT, "工作区/临时/j")
    assert used == "word" and fake.calls() == ["Word.Application"] and pages(out) == 1


def test_word_missing_then_wps(case, lo_base, fake):
    fake.set(word="none", kwps="none", wps="ok")
    out, used = C.OfficeConverter(lo_base).to_pdf(str(case), COMPLAINT, "工作区/临时/j")
    assert used == "wps" and fake.calls() == ["Word.Application", "KWPS.Application", "WPS.Application"]


@needs_lo
def test_hang_times_out_kills_and_falls_through(case, lo_base, fake, monkeypatch):
    """Word 卡住不返回（如"等待打印机连接"）：超时后子进程和它起的进程都已结束，换 WPS，再换 LibreOffice。"""
    monkeypatch.setattr(C, "TIMEOUT", 3)
    fake.set(word="hang", kwps="none", wps="none")
    t0 = time.monotonic()
    out, used = C.OfficeConverter(lo_base).to_pdf(str(case), COMPLAINT, "工作区/临时/j")
    assert used == "libreoffice" and pages(out) >= 1
    assert time.monotonic() - t0 < 60
    worker, child = fake.pids()
    alive = C.processes()
    assert worker not in alive and child not in alive


def test_all_three_fail(case, lo_base, fake):
    fake.set(word="fail", kwps="none", wps="none")
    conv = C.OfficeConverter(lo_base, soffice=str(case / "没有" / "soffice.exe"))
    with pytest.raises(ApiError) as e:
        conv.to_pdf(str(case), COMPLAINT, "工作区/临时/j")
    assert e.value.code == "CONVERTER_UNAVAILABLE"


def test_explicit_choice_only_that_one(case, lo_base, fake):
    """设置里选了 libreoffice：不碰 Word / WPS（律所为避免留痕改的设置不能被悄悄绕过）；选了 word 而 Word 失败：不换。"""
    fake.set(word="ok")
    conv = C.OfficeConverter(lo_base, soffice=str(case / "没有" / "soffice.exe"))
    with pytest.raises(ApiError):
        conv.to_pdf(str(case), COMPLAINT, "工作区/临时/j", "libreoffice")
    assert fake.calls() == []
    fake.set(word="fail", kwps="ok")
    with pytest.raises(ApiError):
        conv.to_pdf(str(case), COMPLAINT, "工作区/临时/j", "word")
    assert fake.calls() == ["Word.Application"]


def test_spreadsheet_only_libreoffice(case, lo_base, fake, tmp_path):
    fake.set(word="ok")
    x = tmp_path / "表.xlsx"
    shutil.copy(FIXTURES / "civil-01" / "银行流水.xlsx", x)
    conv = C.OfficeConverter(lo_base, soffice=str(case / "没有" / "soffice.exe"))
    with pytest.raises(ApiError):
        conv.to_pdf(str(case), x, "工作区/临时/j")
    assert fake.calls() == []                                          # Word 不打开表格


def test_doc_with_external_picture_not_given_to_libreoffice(case, lo_base, fake, monkeypatch, tmp_path):
    monkeypatch.setattr(C.links, "has_external_picture", lambda p: True)
    started = []
    monkeypatch.setattr(C.lo.Converter, "session", lambda self: started.append(1))
    d = tmp_path / "旧.doc"
    d.write_bytes(b"\xd0\xcf\x11\xe0" + b"\0" * 100)
    with pytest.raises(ApiError):
        C.OfficeConverter(lo_base).to_pdf(str(case), d, "工作区/临时/j", "libreoffice")
    assert started == []


def test_com_started_only_ours():
    before = {1: (0, "system"), 10: (0, "svchost.exe"), 20: (0, "explorer.exe"), 30: (20, "winword.exe")}
    after = dict(before)
    after.update({40: (20, "winword.exe"),       # 律师刚双击打开的 Word（父进程 explorer）
                  50: (10, "winword.exe"),       # 本次 COM 启动的
                  60: (10, "excel.exe")})
    assert C.com_started(before, after, ("winword.exe",)) == [50]


def test_original_untouched(case, lo_base, fake):
    fake.set(word="ok")
    import hashlib
    h = hashlib.sha256(COMPLAINT.read_bytes()).hexdigest()
    C.OfficeConverter(lo_base).to_pdf(str(case), COMPLAINT, "工作区/临时/j")
    assert hashlib.sha256(COMPLAINT.read_bytes()).hexdigest() == h


# ---------------------------------------------------------------- 14.3：外链图片不取

class _Counter(http.server.BaseHTTPRequestHandler):
    hits: list = []

    def do_GET(self):  # noqa: N802
        type(self).hits.append(self.path)
        self.send_response(404)
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture
def listener():
    _Counter.hits = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Counter)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", _Counter.hits
    srv.shutdown()
    srv.server_close()


def linked_picture_docx(path: pathlib.Path, url: str) -> None:
    """一张"链接到文件"的图片：r:embed 改成 r:link，关系指向外部地址。"""
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, "PNG")
    d = pydocx.Document()
    d.add_paragraph("正文")
    d.add_picture(io.BytesIO(buf.getvalue()))
    tmp = io.BytesIO()
    d.save(tmp)
    zin = zipfile.ZipFile(io.BytesIO(tmp.getvalue()))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in zin.namelist():
            data = zin.read(n)
            if n == "word/document.xml":
                data = data.replace(b"r:embed=", b"r:link=")
            elif n == "word/_rels/document.xml.rels":
                s = data.decode()
                i = s.index('Target="media/')
                j = s.index('"', i + 8)
                s = s[:i] + f'Target="{url}/linked.png" TargetMode="External"' + s[j + 1:]
                data = s.encode()
            zout.writestr(n, data)


@needs_lo
def test_libreoffice_no_fetch(case, lo_base, listener, tmp_path):
    url, hits = listener
    p = tmp_path / "外链图片.docx"
    linked_picture_docx(p, url)
    out, used = C.OfficeConverter(lo_base).to_pdf(str(case), p, "工作区/临时/j", "libreoffice")
    assert used == "libreoffice" and pages(out) >= 1 and hits == []


def field_picture_docx(path: pathlib.Path, url: str) -> None:
    """正文里一个 INCLUDEPICTURE 域，地址指向外部。"""
    d = pydocx.Document()
    p = d.add_paragraph()
    for kind, text in (("begin", None), (None, f' INCLUDEPICTURE "{url}/f.png" \\d '), ("separate", None),
                       (None, None), ("end", None)):
        r = p.add_run()
        if kind:
            fc = r._r.makeelement(pydocx.oxml.ns.qn("w:fldChar"), {pydocx.oxml.ns.qn("w:fldCharType"): kind})
            r._r.append(fc)
        elif text:
            it = r._r.makeelement(pydocx.oxml.ns.qn("w:instrText"), {})
            it.text = text
            r._r.append(it)
    d.save(str(path))


def test_word_has_external(tmp_path):
    a, b, c = tmp_path / "链接图.docx", tmp_path / "域.docx", tmp_path / "普通.docx"
    linked_picture_docx(a, "http://127.0.0.1:9")
    field_picture_docx(b, "http://127.0.0.1:9")
    pydocx.Document().save(str(c))
    assert C.word_has_external(a) and C.word_has_external(b) and not C.word_has_external(c)
    assert not C.word_has_external(COMPLAINT)
    bad = tmp_path / "坏.docx"
    bad.write_bytes(b"PK\x03\x04 not a zip")
    assert C.word_has_external(bad)                                    # 查不了按有外链：不交 Word


@needs_lo
def test_external_link_skips_word_and_wps(case, lo_base, fake, tmp_path, listener):
    """auto：带外链图片的 docx 不交给 Word / WPS（它们会去取图），直接用 LibreOffice；选了 word 的转不了。"""
    url, hits = listener
    fake.set(word="ok", kwps="ok")
    p = tmp_path / "外链图片.docx"
    linked_picture_docx(p, url)
    out, used = C.OfficeConverter(lo_base).to_pdf(str(case), p, "工作区/临时/j")
    assert used == "libreoffice" and fake.calls() == [] and hits == []
    with pytest.raises(ApiError) as e:
        C.OfficeConverter(lo_base).to_pdf(str(case), p, "工作区/临时/j", "word")
    assert e.value.code == "CONVERTER_UNAVAILABLE" and fake.calls() == []


@pytest.mark.skipif(os.environ.get("LAWBENCH_REAL_WORD") != "1", reason="真 Word 实测：设 LAWBENCH_REAL_WORD=1")
def test_real_word(case, lo_base, listener, tmp_path):
    """真 Word：普通 docx 用 Word 转、转完不留 Word 进程；带外链图片的 docx 不交给 Word（监听 0 请求）。"""
    url, hits = listener
    before = C.processes()
    out, used = C.OfficeConverter(lo_base).to_pdf(str(case), COMPLAINT, "工作区/临时/j", "word")
    assert used == "word" and pages(out) >= 1
    assert C.com_started(before, C.processes(), C.SERVER_EXE["word"]) == []
    p = tmp_path / "外链图片.docx"
    linked_picture_docx(p, url)
    out, used = C.OfficeConverter(lo_base).to_pdf(str(case), p, "工作区/临时/j")
    assert used == "libreoffice" and hits == []
