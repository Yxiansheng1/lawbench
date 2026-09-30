"""T5 补充（Spec 12.3、14.3）：转换不联网取图、.doc/.wps 外链图片拒绝、超时只结束自己启动的进程树、
失败 / 超时后 工作区\\临时\\ 和系统临时目录不留材料副本。外链一律指向 127.0.0.1 本机监听（端口 0）。
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

import pytest

from lawbench.config import REPO_ROOT
from lawbench.ingest import REASONS, links
from lawbench.ingest import libreoffice as lo

from conftest import short_dir
from fakes import CountingListener, linked_image_docx, linked_image_xlsx, minimal_ole

FIXTURES = REPO_ROOT / "tests" / "fixtures"
needs_lo = pytest.mark.skipif(lo.find_soffice() is None, reason="本机没有 LibreOffice")


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def open_scan(client, root: pathlib.Path) -> dict:
    cid = client.post("/api/case/open", json={"path": str(root)}).json()["value"]["case_id"]
    r = client.post("/api/materials/scan", json={"case_id": cid}).json()
    assert r["ok"], r
    idx = json.loads((root / "工作区" / "材料" / "index.json").read_text(encoding="utf-8"))
    return {m["name"]: m for m in idx["materials"]}


# ---------- docx：python 自己解析，不跟随外部链接 ----------

def test_docx_linked_image_no_request(make_client, cases_dir):
    with CountingListener() as lis:
        root = cases_dir / "外链docx"
        root.mkdir()
        linked_image_docx(root / "对方意见.docx", lis.url)
        mats = open_scan(make_client(), root)
        assert lis.count == 0
    m = mats["对方意见"]
    assert m["status"] == "parsed"
    assert "正文里有一张外链图片" in (root / m["text_path"]).read_text(encoding="utf-8")


# ---------- LibreOffice：独立配置目录里关掉按链接取图（先红后绿） ----------

@needs_lo
def test_libreoffice_block_setting_red_then_green(tmp_path, monkeypatch, lo_base):
    with CountingListener() as lis:
        src = tmp_path / "外链.docx"
        linked_image_docx(src, lis.url)
        # 红：不写 BlockUntrustedRefererLinks，LibreOffice 会去取图
        monkeypatch.setattr(lo, "write_profile", lambda p: (p / "user").mkdir(parents=True, exist_ok=True))
        with lo.Converter(tmp_path / "t-red", lo_base=lo_base).session() as s:
            s.convert(src, "odt")
        red = lis.count
        monkeypatch.undo()
        lis.count = 0
        # 绿：写了设置，转换照常成功，监听收到 0 次请求
        with lo.Converter(tmp_path / "t-green", lo_base=lo_base).session() as s:
            assert s.convert(src, "odt").stat().st_size > 0
        green = lis.count
    assert red > 0 and green == 0, (red, green)


# ---------- .doc / .wps：查到外链图片就不交给 LibreOffice ----------

@pytest.fixture(scope="module")
def doc_samples(tmp_path_factory):
    """用 LibreOffice（已关掉取图）把 docx 另存为 .doc：一份带外链图片，一份只有普通网址文字。"""
    if lo.find_soffice() is None:
        pytest.skip("本机没有 LibreOffice")
    base = tmp_path_factory.mktemp("doc")
    lis = CountingListener().__enter__()
    linked_image_docx(base / "linked.docx", lis.url)
    shutil.copy(FIXTURES / "tender-01" / "补充通知.docx", base / "plain.docx")
    out = {}
    with short_dir("lblo-") as lb, lo.Converter(base / "t", lo_base=lb).session() as s:
        for n in ("linked", "plain"):
            out[n] = base / f"{n}.doc"
            out[n].write_bytes(s.convert(base / f"{n}.docx", "doc").read_bytes())
    out["switch_first"] = base / "switch_first.doc"
    _make_switch_first(out["linked"], out["switch_first"])
    lis.count = 0
    yield out, lis
    lis.__exit__(None, None, None)


def _make_switch_first(src: pathlib.Path, dst: pathlib.Path) -> None:
    """只靠域指令检查才能拦住的样本（注记 2218 第 3 节）：以 LibreOffice 生成的 .doc 为底，
    按原长度把域指令改成"开关在前"，并把 Data 流里单字节存放的地址前缀改掉。"""
    import olefile
    shutil.copy(src, dst)
    with olefile.OleFileIO(str(dst), write_mode=True) as ole:
        wd = ole.openstream("WordDocument").read()
        head = ' INCLUDEPICTURE  "'.encode("utf-16-le")
        tail = '" \\d'.encode("utf-16-le")
        start = wd.find(head)
        assert start >= 0, "LibreOffice 生成的 .doc 里没找到 INCLUDEPICTURE 域"
        end = wd.find(tail, start) + len(tail)
        old = wd[start:end].decode("utf-16-le")                  # ' INCLUDEPICTURE  "http://…/pic.png" \d'
        url = re.search(r'"[^"]+"', old).group(0)
        new = f" INCLUDEPICTURE \\d {url} "                         # 开关写在网址前面，长度不变
        assert len(new) == len(old)
        ole.write_stream("WordDocument", wd[:start] + new.encode("utf-16-le") + wd[end:])
        data = ole.openstream("Data").read()
        assert b"http://" in data
        ole.write_stream("Data", data.replace(b"http://", b"zzzz://"))


def test_detector(doc_samples):
    docs, _ = doc_samples
    assert links.has_external_picture(docs["linked"]) is True
    assert links.has_external_picture(docs["plain"]) is False


def test_detector_switch_first_needs_field_check(doc_samples, monkeypatch):
    """开关在前、Data 流地址被改掉的样本：域指令检查拦得住；去掉域指令检查就拦不住（证明样本只靠这一条）。"""
    docs, _ = doc_samples
    assert links.has_external_picture(docs["switch_first"]) is True
    assert links._data_stream_has_url(docs["switch_first"]) is False
    monkeypatch.setattr(links, "_field_has_link", lambda text: False)
    assert links.has_external_picture(docs["switch_first"]) is False


@pytest.mark.parametrize("data,expect", [
    (b"\x00\x00\x1ehttp://127.0.0.1:1/pic.png\x00", True),
    (b"\x00\x1e\\\\server\\share\\a.png\x00", True),
    (b"\x00ftp://x.example/a.png", True),
    (b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
     b'<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">',
     False),                                                   # 内嵌 JPEG 自带的 XMP 元数据
    ("http://127.0.0.1:1/x".encode("utf-16-le"), False),       # UTF-16 的地址（超链接）不在 Data 流单字节检查范围
])
def test_data_bytes(data, expect):
    assert links.data_bytes_have_url(data) is expect


def test_detector_data_stream_alone(doc_samples, monkeypatch):
    """Data 流里单字节存放的地址前缀，单独也能拦住。"""
    docs, _ = doc_samples
    monkeypatch.setattr(links, "_field_has_link", lambda text: False)
    assert links.has_external_picture(docs["linked"]) is True


# (域指令内容, 是否算外链)。域指令 = 0x13 与 0x14 / 0x15 之间的文字（注记 2218 第 3 节）
FIELD_CASES = [
    (' INCLUDEPICTURE "http://127.0.0.1:1/a.png" \\d ', True),
    (' INCLUDEPICTURE \\d "https://x.example/a.png" ', True),
    (' INCLUDEPICTURE \\* MERGEFORMAT \\d "http://x.example/a.png" ', True),   # 开关写在网址前面
    (' INCLUDEPICTURE "\\\\server\\share\\a.png" ', True),                      # UNC
    (' includepicture "HTTP://X/A.PNG" ', True),
    (' INCLUDETEXT "http://x.example/t.docx" ', True),
    (' LINK Excel.Sheet.12 "ftp://x.example/b.xlsx" "Sheet1!R1C1" \\a ', True),
    (' IMPORT "file://x.example/p.wmf" ', True),
    (' DDEAUTO Excel "http://x.example/b.xlsx" ', True),
    (' DDE Excel "\\\\server\\b.xlsx" ', True),
    (' INCLUDEPICTURE "C:\\\\图片\\\\a.png" ', False),                          # 本机路径
    (' HYPERLINK "https://example.invalid/" ', False),                         # 超链接不是链接类域
    (' PAGE \\* MERGEFORMAT ', False),
]


def _field_doc(path: pathlib.Path, instr: str, enc: str, pad: int = 64) -> None:
    body = ("正文 see the link http://example.invalid/ 开头" + "\x13" + instr + "\x14结果\x15" + "结尾").encode(enc)
    minimal_ole(path, {"WordDocument": b"\x00" * pad + body})  # 真的 OLE 容器：打不开的容器按"无法检查"拒绝（X2）


@pytest.mark.parametrize("instr,expect", FIELD_CASES, ids=range(len(FIELD_CASES)))
def test_detector_field_forms(tmp_path, instr, expect):
    for enc in ("utf-16-le", "gb18030"):
        for pad in (64, 65):  # UTF-16 文字落在偶数、奇数字节偏移上
            p = tmp_path / f"x-{enc}-{pad}.doc"
            _field_doc(p, instr, enc, pad)
            assert links.has_external_picture(p) is expect, (instr, enc, pad)


@pytest.mark.parametrize("text", [
    "正文里写了网址 http://example.invalid/ 和 \\\\server\\share",
    "see the link http://example.invalid/page and ftp://x.example/",
    "INCLUDEPICTURE http://x.example/a.png 这几个字写在正文里，不在域指令里",
])
def test_detector_plain_text_not_triggered(tmp_path, text):
    for enc in ("utf-16-le", "gb18030"):
        p = tmp_path / f"plain-{enc}.doc"
        minimal_ole(p, {"WordDocument": b"\x00" * 64 + text.encode(enc)})
        assert links.has_external_picture(p) is False, (text, enc)


def test_linked_doc_rejected_no_request(make_client, cases_dir, doc_samples):
    docs, lis = doc_samples
    root = cases_dir / "外链doc"
    root.mkdir()
    shutil.copy(docs["linked"], root / "对方证据说明.doc")
    shutil.copy(docs["plain"], root / "补充通知.doc")
    before = sha(root / "对方证据说明.doc")
    lis.count = 0
    mats = open_scan(make_client(), root)
    assert lis.count == 0
    bad = mats["对方证据说明"]
    assert bad["status"] == "failed" and bad["error"] == REASONS["external_link"]
    assert sha(root / "对方证据说明.doc") == before
    good = mats["补充通知"]
    assert good["status"] == "parsed" and good["note"] == "由 doc 转换"
    assert list((root / "工作区" / "临时").iterdir()) == []


@needs_lo
def test_linked_doc_would_fetch_without_detector(make_client, cases_dir, doc_samples, monkeypatch):
    """红测：去掉检测，LibreOffice 的设置拦不住 .doc 里的外链图片（Spec 14.3 ②a 的依据）。"""
    docs, lis = doc_samples
    monkeypatch.setattr(links, "has_external_picture", lambda p: False)
    root = cases_dir / "去掉检测"
    root.mkdir()
    shutil.copy(docs["linked"], root / "a.doc")
    lis.count = 0
    open_scan(make_client(), root)
    assert lis.count > 0


@needs_lo
def test_xls_no_request(make_client, cases_dir):
    """扩展名 .xls、内容是带外链图片的 xlsx（Y8：换成有区分力的样本——关掉检查时转换程序确实会去取图，
    见 test_xls_disguised_would_fetch_without_check）：按文件头走 xlsx 的检查，不交给 LibreOffice，0 次请求。"""
    with CountingListener() as lis:
        root = cases_dir / "xls"
        root.mkdir()
        linked_image_xlsx(root / "流水.xls", lis.url)
        mats = open_scan(make_client(), root)
        assert lis.count == 0
    m = mats["流水"]
    assert m["status"] == "parsed" and m["note"] == "有外部链接，未重算公式"   # 没经过转换；契约 1.2 N21
    text = (root / m["text_path"]).read_text(encoding="utf-8")
    assert "| 2 |  | =B1*2 |" in text                         # 没有缓存值：只写公式，没有交给 LibreOffice 重算


@needs_lo
def test_xls_disguised_would_fetch_without_check(make_client, cases_dir, monkeypatch):
    """红测（X1 的依据）：同一个样本，去掉外链检查后交给 LibreOffice，监听收到请求。"""
    monkeypatch.setattr(links, "xlsx_has_external_rels", lambda p: False)
    with CountingListener() as lis:
        root = cases_dir / "去掉检查"
        root.mkdir()
        linked_image_xlsx(root / "流水.xls", lis.url)
        open_scan(make_client(), root)
        time.sleep(0.5)
        assert lis.count > 0


# ---------- 超时：只结束本次启动的进程树；不留材料副本 ----------

FAKE_SOFFICE = r'''
import os, pathlib, shutil, sys, time
pathlib.Path(os.environ["LB_FAKE_PID_FILE"]).write_text(str(os.getpid()))
src = pathlib.Path(sys.argv[-1])
shutil.copyfile(src, pathlib.Path(os.environ["TEMP"]) / ("LBFAKECOPY-" + src.name))  # 像 LibreOffice 一样在 TEMP 留副本
time.sleep(600)
'''


def _alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                         encoding="gbk", errors="ignore").stdout
    return str(pid) in out


@pytest.mark.skipif(os.name != "nt", reason="Windows 进程树")
def test_timeout_kills_own_tree_and_cleans(make_client, cases_dir, tmp_path, monkeypatch):
    script = tmp_path / "fake_soffice.py"
    script.write_text(FAKE_SOFFICE, encoding="utf-8")
    cmd = tmp_path / "fake_soffice.cmd"
    cmd.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="mbcs")  # cmd.exe 按系统代码页读批处理
    pid_file = tmp_path / "pid.txt"
    monkeypatch.setenv("LB_FAKE_PID_FILE", str(pid_file))
    monkeypatch.setattr(lo, "find_soffice", lambda: str(cmd))
    monkeypatch.setattr(lo, "TIMEOUT", 3)
    # 一个"律师自己开着的"同名进程：不能被误杀
    bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        root = cases_dir / "卡住"
        root.mkdir()
        minimal_ole(root / "旧格式.doc", {"WordDocument": b"LBFX"})  # 内容是 OLE 才走 LibreOffice（X1 按文件头分流）
        t0 = time.monotonic()
        mats = open_scan(make_client(), root)
        assert time.monotonic() - t0 < 60
        m = mats["旧格式"]
        assert m["status"] == "failed" and m["error"] == REASONS["convert_timeout"]
        pid = int(pid_file.read_text())
        assert not _alive(pid)                                           # 本次启动的进程树已结束
        assert bystander.poll() is None                                  # 别的进程不受影响
        assert list((root / "工作区" / "临时").iterdir()) == []            # 案件临时目录不留副本
        assert not list(pathlib.Path(tempfile.gettempdir()).glob("LBFAKECOPY-*"))  # 系统临时目录也没有
    finally:
        bystander.kill()


def test_convert_failure_cleans_temp(make_client, cases_dir, monkeypatch):
    monkeypatch.setattr(lo, "find_soffice", lambda: sys.executable)  # 能启动但不会产出文件
    root = cases_dir / "转换失败"
    root.mkdir()
    minimal_ole(root / "坏.doc", {"WordDocument": b"LBFX"})
    mats = open_scan(make_client(), root)
    assert mats["坏"]["status"] == "failed"
    assert list((root / "工作区" / "临时").iterdir()) == []


def test_no_print_interface():
    """只用 --convert-to 导出；代码里没有任何打印入口（Spec 12.3）。"""
    src = pathlib.Path(lo.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#") and '"""' not in line)
    assert "--convert-to" in code
    for bad in ("--print-to-file", "--pt", "-p ", "PrintOut", "--printer-name"):
        assert bad not in code, bad
