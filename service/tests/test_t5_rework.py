"""T5 第一轮返修（执行令 致B-ORCH-执行令-T3第三轮及T5返修-20260930-0136 第 3 节）逐条测试。编号与返修令一致。"""
from __future__ import annotations

import io
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import time
import tracemalloc
import zipfile

import openpyxl
import pytest

from lawbench.case import gate, materials as mat_mod
from lawbench.case.materials import Materials, assign_names
from lawbench.config import REPO_ROOT
from lawbench.ingest import REASONS, ParseError, detect, docx, links, text, xlsx
from lawbench.ingest import libreoffice as lo

from conftest import IS_WIN, make_junction
from fakes import CountingListener, linked_image_docx, linked_image_xlsx, minimal_ole

FIXTURES = REPO_ROOT / "tests" / "fixtures"
SERVICE_DIR = pathlib.Path(__file__).resolve().parents[1]


def open_case(client, root: pathlib.Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    r = client.post("/api/case/open", json={"path": str(root)}).json()
    assert r["ok"], r
    return r["value"]["case_id"]


def scan(client, cid: str) -> dict:
    r = client.post("/api/materials/scan", json={"case_id": cid}).json()
    assert r["ok"], r
    return r["value"]


def do_import(client, cid: str, paths: list, target=None, unzip=False) -> dict:
    r = client.post("/api/materials/import", json={"case_id": cid, "paths": [str(p) for p in paths],
                                                   "target": target, "unzip": unzip}).json()
    assert r["ok"], r
    return r["value"]


def index_of(root: pathlib.Path) -> dict:
    return json.loads((root / "工作区" / "材料" / "index.json").read_text(encoding="utf-8"))


def by_rel(root: pathlib.Path) -> dict:
    return {m["rel_path"]: m for m in index_of(root)["materials"]}


def status_md(root: pathlib.Path) -> str:
    return (root / "工作区" / "材料" / "_处理状态.md").read_text(encoding="utf-8")


def files_under(p: pathlib.Path) -> list[str]:
    return sorted(str(x.relative_to(p)).replace("\\", "/") for x in p.rglob("*") if x.is_file())


@pytest.fixture
def no_soffice_start(monkeypatch):
    """记下有没有启动转换程序（只记，不拦）。"""
    started = []
    real = lo.subprocess.Popen
    monkeypatch.setattr(lo.subprocess, "Popen", lambda *a, **k: started.append(a) or real(*a, **k))
    return started


# ---------- X1：按文件头分流 ----------

def test_x1_content_kind():
    assert detect.content_kind(FIXTURES / "civil-01" / "借条.docx") == "zip"
    assert detect.content_kind(FIXTURES / "civil-01" / "情况说明.txt") == "other"


def test_x1_doc_with_docx_content_parsed_directly(make_client, cases_dir, no_soffice_start):
    """扩展名 .doc、内容是带外链图片的 docx：直接读 XML，不交给 LibreOffice，0 次请求。"""
    with CountingListener() as lis:
        root = cases_dir / "x1doc"
        root.mkdir()
        linked_image_docx(root / "说明.doc", lis.url)
        client = make_client()
        scan(client, open_case(client, root))
        assert lis.count == 0
    m = by_rel(root)["说明.doc"]
    assert m["status"] == "parsed" and m["note"] is None
    assert no_soffice_start == []


@pytest.mark.parametrize("name", ["网页.doc", "网页.wps", "网页.xls"])
def test_x1_other_content_not_given_to_converter(make_client, cases_dir, no_soffice_start, name):
    """扩展名是旧版 Office、内容既不是 OLE 也不是压缩包（HTML、RTF 冒充）：查不了外链，不交给 LibreOffice。"""
    with CountingListener() as lis:
        root = cases_dir / "x1html"
        root.mkdir()
        (root / name).write_text(f'<html><body><img src="{lis.url}/a.png">正文</body></html>', encoding="utf-8")
        client = make_client()
        scan(client, open_case(client, root))
        assert lis.count == 0
    m = by_rel(root)[name]
    assert m["status"] == "failed" and m["error"] == REASONS["unchecked"]
    assert no_soffice_start == []


def test_x1_docx_with_ole_content_goes_through_ole_checks(make_client, cases_dir, no_soffice_start):
    """扩展名 .docx、内容是 OLE（加密的新版 Office 就是这样）：走 OLE 那条，先查加密。"""
    root = cases_dir / "x1ole"
    root.mkdir()
    minimal_ole(root / "加密.docx", {"EncryptionInfo": b"x", "EncryptedPackage": b"y"})
    minimal_ole(root / "加密表.xlsx", {"EncryptionInfo": b"x", "EncryptedPackage": b"y"})
    client = make_client()
    scan(client, open_case(client, root))
    mats = by_rel(root)
    assert mats["加密.docx"]["error"] == REASONS["encrypted"]
    assert mats["加密表.xlsx"]["error"] == REASONS["encrypted"]
    assert no_soffice_start == []


# ---------- X2：检查出错即拒绝 ----------

def _xlsx_bad_rels_first(path: pathlib.Path, url: str) -> None:
    """复核员 A 的 P1-2 样本：压缩包里先放一个没人引用的坏关系文件，后面才是带外链图片的关系。"""
    linked_image_xlsx(path.with_suffix(".src"), url)
    with zipfile.ZipFile(path.with_suffix(".src")) as zin, zipfile.ZipFile(path, "w") as zout:
        zout.writestr("xl/_rels/aaa.xml.rels", b"<Relationships><broken")
        for info in zin.infolist():
            zout.writestr(info, zin.read(info))
    path.with_suffix(".src").unlink()


def test_x2_bad_rels_rejected_not_passed(make_client, cases_dir, no_soffice_start):
    with CountingListener() as lis:
        root = cases_dir / "x2"
        root.mkdir()
        _xlsx_bad_rels_first(root / "报表.xlsx", lis.url)
        with pytest.raises(ParseError) as ei:
            links.xlsx_has_external_rels(root / "报表.xlsx")
        assert ei.value.reason == "unchecked"
        client = make_client()
        scan(client, open_case(client, root))
        assert lis.count == 0
    m = by_rel(root)["报表.xlsx"]
    assert m["status"] == "failed" and m["error"] == REASONS["unchecked"]
    assert no_soffice_start == []


def test_x2_every_rels_checked_not_only_xl(tmp_path):
    """关系文件不在 xl/ 下、名字大小写不同，也要查。"""
    p = tmp_path / "a.xlsx"
    linked_image_xlsx(p, "http://127.0.0.1:9")
    q = tmp_path / "b.xlsx"
    with zipfile.ZipFile(p) as zin, zipfile.ZipFile(q, "w") as zout:
        for info in zin.infolist():
            name = info.filename
            if name == "xl/drawings/_rels/drawing1.xml.rels":
                name = "XL/Drawings/_RELS/drawing1.xml.RELS"
            zout.writestr(name, zin.read(info))
    assert links.xlsx_has_external_rels(q) is True


def test_x2_rels_with_doctype_rejected(tmp_path):
    p = tmp_path / "d.xlsx"
    wb = openpyxl.Workbook()
    wb.save(p)
    with zipfile.ZipFile(p, "a") as z:
        z.writestr("xl/_rels/x.rels", '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY e "x">]><Relationships/>')
    with pytest.raises(ParseError) as ei:
        links.xlsx_has_external_rels(p)
    assert ei.value.reason == "unchecked"


def test_x2_ole_checks_fail_closed(tmp_path):
    bad = tmp_path / "坏.doc"
    bad.write_bytes(detect.OLE_MAGIC + b"\x00" * 600)   # 文件头是 OLE，容器本身坏的
    for check in (detect.ole_encrypted, links._data_stream_has_url):
        with pytest.raises(ParseError) as ei:
            check(bad)
        assert ei.value.reason == "unchecked", check


def test_x2_broken_ole_scan_rejected(make_client, cases_dir, no_soffice_start):
    root = cases_dir / "x2ole"
    root.mkdir()
    (root / "坏.doc").write_bytes(detect.OLE_MAGIC + b"\x00" * 600)
    (root / "坏.xls").write_bytes(detect.OLE_MAGIC + b"\x00" * 600)
    client = make_client()
    scan(client, open_case(client, root))
    mats = by_rel(root)
    assert mats["坏.doc"]["error"] == REASONS["unchecked"]
    assert mats["坏.xls"]["error"] == REASONS["unchecked"]
    assert no_soffice_start == []


# ---------- X3：把案件文件夹本身或它的上级拖进来 ----------

@pytest.fixture
def case_with_work(make_client, cases_dir):
    client = make_client()
    root = cases_dir / "父" / "案件"
    cid = open_case(client, root)
    (root / "证据.txt").write_text("证据", encoding="utf-8")
    scan(client, cid)
    (cases_dir / "父" / "别的.txt").write_text("别的", encoding="utf-8")
    return client, root, cid


def test_x3_import_case_root_itself(case_with_work):
    client, root, cid = case_with_work
    before = files_under(root)
    v = do_import(client, cid, [root])
    assert v["copied"] == []
    after = files_under(root)
    assert [f for f in after if not f.startswith("工作区/")] == [f for f in before if not f.startswith("工作区/")]
    assert not any("工作区" in c["to"] or "case.db" in c["to"] for c in v["copied"])


def test_x3_import_parent_skips_case_branch(case_with_work, cases_dir):
    client, root, cid = case_with_work
    v = do_import(client, cid, [cases_dir / "父"])
    assert [c["to"] for c in v["copied"]] == ["父/别的.txt"]
    assert not (root / "父" / "案件").exists()
    assert not [f for f in files_under(root) if f.startswith("父/") and f != "父/别的.txt"]


# ---------- X4：资源上界 ----------

def _big_part_docx(path: pathlib.Path, size: int) -> None:
    with zipfile.ZipFile(FIXTURES / "civil-01" / "借条.docx") as zin, \
            zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            if info.filename != "word/document.xml":
                zout.writestr(info, zin.read(info))
        with zout.open("word/document.xml", "w", force_zip64=True) as f:
            chunk = b" " * (1 << 20)
            for _ in range(size // len(chunk) + 1):
                f.write(chunk)


def test_x4_docx_part_over_limit_not_decompressed(tmp_path):
    p = tmp_path / "炸.docx"
    _big_part_docx(p, 301 * 1024 * 1024)
    assert p.stat().st_size < 2 * 1024 * 1024
    tracemalloc.start()
    t0 = time.monotonic()
    with pytest.raises(ParseError) as ei:
        docx.parse(p)
    elapsed = time.monotonic() - t0
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert ei.value.reason == "too_large"
    assert elapsed < 2 and peak < 20 * 1024 * 1024, (elapsed, peak)


def test_x4_xlsx_part_over_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(links, "MAX_PART_BYTES", 1000)   # 同一道检查，用小上限省时间
    with pytest.raises(ParseError) as ei:
        xlsx.parse(FIXTURES / "civil-01" / "银行流水.xlsx")
    assert ei.value.reason == "too_large"


@pytest.mark.parametrize("coord", [(2000, 1000), (1048576, 16384)])
def test_x4_xlsx_far_cell_fast(tmp_path, coord):
    """复核员 B 的 e8：远处一个单元格。只遍历实际存在的单元格：时间、内存都有上限。"""
    p = tmp_path / "远.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "表头"
    ws.cell(row=coord[0], column=coord[1]).number_format = "0.00"   # 带格式的空单元格
    if coord[0] < 100000:
        ws.cell(row=coord[0], column=coord[1], value=1)
    wb.save(p)
    tracemalloc.start()
    t0 = time.monotonic()
    out = xlsx.parse(p)
    elapsed = time.monotonic() - t0
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert elapsed < 5 and peak < 100 * 1024 * 1024, (elapsed, peak)
    assert "| 1 | 表头 |" in out.blocks[0].text


def test_x4_xlsx_too_many_cells_rendered(tmp_path):
    """有内容的行多、又有一格在很远的列：写出来的格子数超过上限，按过大，不硬写。"""
    p = tmp_path / "宽.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in range(1, 201):
        ws.cell(row=r, column=1, value=r)
    ws.cell(row=1, column=16384, value="远")
    wb.save(p)
    with pytest.raises(ParseError) as ei:
        xlsx.parse(p)
    assert ei.value.reason == "too_large"


# ---------- X5 + X6：强行结束后的残留 ----------

KILL_DURING_COPY = r'''
import os, sys, shutil
sys.path.insert(0, sys.argv[1])
from lawbench import logs
from lawbench.case import gate
logs.setup(sys.argv[4])
def half_then_die(inp, out, *a, **k):
    out.write(inp.read(4096)); out.flush(); os._exit(9)   # 像被任务管理器结束：finally 不会执行
shutil.copyfileobj = half_then_die
gate.copy_original(sys.argv[2], "证据/大.pdf", sys.argv[3])
'''


def test_x5_x6_killed_import_leaves_nothing_in_originals(make_client, cases_dir, tmp_path, appdata):
    client = make_client()
    root = cases_dir / "x5"
    cid = open_case(client, root)
    src = tmp_path / "大.pdf"
    src.write_bytes(os.urandom(64 * 1024))
    script = tmp_path / "kill.py"
    script.write_text(KILL_DURING_COPY, encoding="utf-8")
    real_root = gate.check_root(str(root))
    r = subprocess.run([sys.executable, str(script), str(SERVICE_DIR), real_root, str(src), str(tmp_path / "ad")],
                       capture_output=True, timeout=60)
    assert r.returncode == 9, r.stderr
    originals = [f for f in files_under(root) if not f.startswith("工作区/")]
    assert originals == []                                           # 原件区没有半截文件
    left = list((root / "工作区" / "临时").iterdir())
    assert [p.name[:4] for p in left] == ["imp-"]                    # 半截文件在 工作区/临时/ 里
    scan(client, cid)
    assert list((root / "工作区" / "临时").iterdir()) == []          # 下次扫描清掉（X6）


def test_x5_temp_written_in_work_temp_then_moved(make_client, cases_dir, tmp_path, monkeypatch):
    client = make_client()
    root = cases_dir / "x5b"
    cid = open_case(client, root)
    src = tmp_path / "a.txt"
    src.write_text("甲", encoding="utf-8")
    seen = []
    real = gate._move_no_replace
    monkeypatch.setattr(gate, "_move_no_replace", lambda s, d: seen.append((pathlib.Path(s), pathlib.Path(d))) or real(s, d))
    do_import(client, cid, [src])
    (tmp, dst), = seen
    assert tmp.parent.name == "临时" and tmp.parent.parent.name == "工作区" and tmp.name.startswith("imp-")
    assert dst.read_text(encoding="utf-8") == "甲" and not tmp.exists()


def test_x5_move_never_overwrites(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_text("新", encoding="utf-8")
    b.write_text("旧", encoding="utf-8")
    with pytest.raises(FileExistsError):
        gate._move_no_replace(a, b)
    assert b.read_text(encoding="utf-8") == "旧"


def test_x6_scan_cleans_only_own_prefixes(make_client, cases_dir, tmp_path):
    client = make_client()
    root = cases_dir / "x6"
    cid = open_case(client, root)
    t = root / "工作区" / "临时"
    t.mkdir(parents=True, exist_ok=True)
    (t / "lo-1a2b3c4d" / "1").mkdir(parents=True)
    (t / "lo-1a2b3c4d" / "1" / "in.doc").write_bytes(b"x")
    (t / "unzip-5e6f7a8b").mkdir()
    (t / "unzip-5e6f7a8b" / "0").write_bytes(b"x")
    (t / "imp-0000aaaa").write_bytes(b"x")
    (t / "截图-20260930.png").write_bytes(b"png")        # 界面粘贴的截图
    (t / "委托材料下载").mkdir()
    (t / "委托材料下载" / "lo-不是我的.pdf").write_bytes(b"pdf")
    (t / "log-下载.zip").write_bytes(b"zip")
    outside = tmp_path / "案外"
    outside.mkdir()
    (outside / "keep.txt").write_text("k", encoding="utf-8")
    if IS_WIN:
        make_junction(t / "lo-junction", outside)
    scan(client, cid)
    left = sorted(p.name for p in t.iterdir())
    expect = ["委托材料下载", "截图-20260930.png", "log-下载.zip"] + (["lo-junction"] if IS_WIN else [])
    assert left == sorted(expect)
    assert (t / "委托材料下载" / "lo-不是我的.pdf").exists()
    assert (outside / "keep.txt").exists()


# ---------- X7：导入 工作区 下的文件 ----------

@pytest.fixture
def x7(make_client, cases_dir):
    client = make_client()
    root = cases_dir / "x7"
    cid = open_case(client, root)
    (root / "证据.txt").write_text("证据", encoding="utf-8")
    scan(client, cid)
    t = root / "工作区" / "临时"
    t.mkdir(parents=True, exist_ok=True)
    return client, root, cid, t


def test_x7_non_temp_work_files_not_imported(x7):
    client, root, cid, _ = x7
    text_md = root / "工作区" / "材料" / "文本" / "证据.txt.md"
    db = root / "工作区" / "case.db"
    assert text_md.exists() and db.exists()
    v = do_import(client, cid, [text_md, db])
    assert v["copied"] == []
    assert {s["reason"] for s in v["skipped"]} == {"无法读取"}
    assert text_md.exists() and db.exists()                            # 没被删


def test_x7_temp_file_deleted_only_after_copy(x7, monkeypatch):
    client, root, cid, t = x7
    ok = t / "截图.png"
    ok.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 10)
    big = t / "大.pdf"
    big.write_bytes(b"%PDF-" + b"0" * 100)
    monkeypatch.setattr(mat_mod, "MAX_BYTES", 50)                      # 让"大.pdf"超过大小上限
    v = do_import(client, cid, [ok, big])
    assert [c["to"] for c in v["copied"]] == ["截图.png"] and not ok.exists()
    assert [s["reason"] for s in v["skipped"]] == ["超过大小上限"]
    assert big.exists()                                                # 没复制成功：不删


def test_x7_temp_file_copied_then_deleted(x7):
    client, root, cid, t = x7
    shot = t / "截图.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 100)
    v = do_import(client, cid, [shot], target="证据")
    assert [c["to"] for c in v["copied"]] == ["证据/截图.png"] and not shot.exists()
    shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 100)                 # 同名同内容再来一次
    v = do_import(client, cid, [shot], target="证据")
    assert [s["reason"] for s in v["skipped"]] == ["同名同内容已存在"] and not shot.exists()


# ---------- X8：路径超长、读不了的子文件夹 ----------

def _long(p: pathlib.Path) -> str:
    return "\\\\?\\" + str(p) if IS_WIN else str(p)


@pytest.mark.skipif(not IS_WIN, reason="Windows 路径上限")
def test_x8_too_long_original_registered_as_failed(make_client, cases_dir):
    client = make_client()
    root = cases_dir / "x8"
    cid = open_case(client, root)
    (root / "短.txt").write_text("短", encoding="utf-8")
    deep = pathlib.Path(_long(root / ("深" * 60)))
    os.makedirs(deep, exist_ok=True)
    name = "长" * max(10, 262 - len(str(root / ("深" * 60))) - 5) + ".txt"
    with open(os.path.join(deep, name), "w", encoding="utf-8") as f:
        f.write("长路径")
    assert len(str(root / ("深" * 60) / name)) > 259
    v = scan(client, cid)
    assert v["failed"] == 1
    m = by_rel(root)[f"{'深' * 60}/{name}"]
    assert m["status"] == "failed" and m["error"] == REASONS["path_too_long"]
    assert len(m["sha256"]) == 64 and m["sha256"] != "0" * 64      # 长路径前缀下照样算出了哈希
    assert "共 2 份" in status_md(root) and "失败 1" in status_md(root)


def test_x8_unreadable_folder_keeps_old_entries(make_client, cases_dir, monkeypatch):
    client = make_client()
    root = cases_dir / "x8b"
    cid = open_case(client, root)
    (root / "子").mkdir()
    (root / "子" / "旧.txt").write_text("旧", encoding="utf-8")
    scan(client, cid)
    real_scandir = os.scandir

    def deny(path):
        if str(path).rstrip("\\/").endswith("子"):
            raise PermissionError(13, "拒绝访问")
        return real_scandir(path)

    monkeypatch.setattr(mat_mod.os, "scandir", deny)
    v = scan(client, cid)
    assert v["removed"] == 0
    assert by_rel(root)["子/旧.txt"]["status"] == "parsed"          # 不误标"原件已删除"
    assert "无法读取的文件夹" in status_md(root) and "- 子" in status_md(root)


def test_x8_locked_file_registered_then_retried(make_client, cases_dir, monkeypatch):
    client = make_client()
    root = cases_dir / "x8c"
    cid = open_case(client, root)
    (root / "占用.txt").write_text("被占用", encoding="utf-8")
    real = mat_mod.sha256_file

    def locked(p):
        if str(p).endswith("占用.txt"):
            raise PermissionError(32, "另一个程序正在使用此文件")
        return real(p)

    monkeypatch.setattr(mat_mod, "sha256_file", locked)
    v = scan(client, cid)
    m = by_rel(root)["占用.txt"]
    assert v["failed"] == 1 and m["status"] == "failed" and m["error"] == REASONS["unreadable"]
    assert "失败 1" in status_md(root)
    monkeypatch.setattr(mat_mod, "sha256_file", real)
    v = scan(client, cid)                                              # 跟环境有关：原件没变也重试（X9）
    m = by_rel(root)["占用.txt"]
    assert m["status"] == "parsed" and m["sha256"] != "0" * 64 and v["review_needed"] is True


# ---------- X9：哪些失败要重试 ----------

@pytest.mark.parametrize("reason,retried", [
    ("converter_crashed", True), ("convert_timeout", True), ("path_too_long", True), ("appdata_too_long", True),
    ("unreadable", True), ("no_converter", True),
    ("encrypted", False), ("too_large", False), ("corrupt", False), ("external_link", False),
    ("unchecked", False), ("convert_failed", False),
])
def test_x9_retry_by_reason(make_client, cases_dir, monkeypatch, reason, retried):
    client = make_client()
    root = cases_dir / f"x9-{reason}"
    cid = open_case(client, root)
    (root / "a.txt").write_text("甲", encoding="utf-8")
    real = Materials._parse

    def fail(self, *a, **k):
        raise ParseError(reason)

    monkeypatch.setattr(Materials, "_parse", fail)
    scan(client, cid)
    assert by_rel(root)["a.txt"]["error"] == REASONS[reason]
    monkeypatch.setattr(Materials, "_parse", real)
    v = scan(client, cid)
    m = by_rel(root)["a.txt"]
    assert (m["status"] == "parsed") is retried
    assert v["changed"] == 0 and v["added"] == 0                     # 原件没变：重试不算"变化"
    assert v["review_needed"] is retried


def test_x9_retry_sets_are_disjoint_and_cover_all():
    from lawbench.ingest import RETRY_REASONS
    assert RETRY_REASONS <= set(REASONS)


# ---------- X10：材料名唯一 ----------

def test_x10_names_unique_with_suffix():
    rels = ["x/证据 1.txt", "x/证据_1.txt", "x/证据、1.txt"]
    names = assign_names(sorted(rels))
    assert names == {"x/证据 1.txt": "x/证据_1.txt", "x/证据_1.txt": "x/证据_1.txt_2",
                     "x/证据、1.txt": "x/证据_1.txt_3"}
    assert len({n.casefold() for n in names.values()}) == 3


def test_x10_existing_name_kept_newcomer_suffixed():
    names = assign_names(["a/证据_1.txt", "a/证据 1.txt"])     # 前一个是已有材料
    assert names["a/证据_1.txt"] == "a/证据_1.txt" and names["a/证据 1.txt"] == "a/证据_1.txt_2"


def test_x10_suffix_does_not_collide_with_natural_name():
    names = assign_names(["a/b c.txt", "a/b_c.txt", "a/b_c.txt_2"])
    assert len({n.casefold() for n in names.values()}) == 3


def test_x10_fullwidth_space_kept():
    assert assign_names(["证据　1.txt"]) == {"证据　1.txt": "证据　1"}


def test_x10_scan_names_unique(make_client, cases_dir):
    client = make_client()
    root = cases_dir / "x10"
    cid = open_case(client, root)
    (root / "x").mkdir()
    for n in ("证据 1.txt", "证据_1.txt", "证据、1.txt"):
        (root / "x" / n).write_text(n, encoding="utf-8")
    scan(client, cid)
    names = [m["name"] for m in index_of(root)["materials"]]
    assert len(set(names)) == 3
    for m in index_of(root)["materials"]:
        head = (root / m["text_path"]).read_text(encoding="utf-8").split("\n", 1)[0]
        assert head == f"# {m['name']}"


# ---------- X11：index.json 被删后编号不复用 ----------

def test_x11_ids_not_reused_after_index_deleted(make_client, cases_dir):
    client = make_client()
    root = cases_dir / "x11"
    cid = open_case(client, root)
    for n in ("a.txt", "c.txt"):
        (root / n).write_text(n, encoding="utf-8")
    scan(client, cid)
    ids = {r: m["material_id"] for r, m in by_rel(root).items()}
    assert ids == {"a.txt": "M0001", "c.txt": "M0002"}
    # 旧编号在别处留过痕：识别页目录、wiki 材料页、case.db
    (root / "工作区" / "材料" / "识别页" / "M0002").mkdir(parents=True)
    (root / "工作区" / "wiki" / "材料").mkdir(parents=True)
    (root / "工作区" / "wiki" / "材料" / "M0001.md").write_text("摘要", encoding="utf-8")
    con = sqlite3.connect(root / "工作区" / "case.db")
    con.execute("INSERT INTO ocr_jobs (job_id, material_id, material_version, status, total, created_at, updated_at)"
                " VALUES ('J-1', 'M0007', 'x', 'done', 1, 't', 't')")
    con.commit()
    con.close()
    (root / "工作区" / "材料" / "index.json").unlink()
    (root / "b.txt").write_text("b", encoding="utf-8")
    scan(client, cid)
    new = {r: m["material_id"] for r, m in by_rel(root).items()}
    assert sorted(new.values()) == ["M0008", "M0009", "M0010"]
    assert index_of(root)["next_seq"] == 11


def test_x11_sources_each_count(make_client, cases_dir):
    client = make_client()
    root = cases_dir / "x11b"
    open_case(client, root)
    assert mat_mod._recover_next_seq(str(gate.check_root(str(root)))) == 1
    (root / "工作区" / "材料" / "识别页" / "M0004").mkdir(parents=True)
    assert mat_mod._recover_next_seq(gate.check_root(str(root))) == 5
    (root / "工作区" / "wiki" / "材料").mkdir(parents=True)
    (root / "工作区" / "wiki" / "材料" / "M0012.md").write_text("x", encoding="utf-8")
    assert mat_mod._recover_next_seq(gate.check_root(str(root))) == 13


# ---------- X12：导入时跳过任何层级的点开头项 ----------

def test_x12_dot_items_skipped_at_any_level(make_client, cases_dir, tmp_path):
    client = make_client()
    root = cases_dir / "x12"
    cid = open_case(client, root)
    src = tmp_path / "材料包"
    (src / "sub" / ".git").mkdir(parents=True)
    (src / "sub" / ".git" / "config").write_text("c", encoding="utf-8")
    (src / "sub" / ".env").write_text("SECRET", encoding="utf-8")
    (src / "sub" / "正常.txt").write_text("正常", encoding="utf-8")
    v = do_import(client, cid, [src])
    assert [c["to"] for c in v["copied"]] == ["材料包/sub/正常.txt"]
    skipped = sorted(pathlib.Path(s["path"]).name for s in v["skipped"])
    assert skipped == [".env", ".git"]
    assert not any(".env" in f or ".git" in f for f in files_under(root))


def test_x12_dot_members_in_zip_skipped(make_client, cases_dir, tmp_path):
    client = make_client()
    root = cases_dir / "x12z"
    cid = open_case(client, root)
    z = tmp_path / "包.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("材料/正常.txt", "正常")
        zf.writestr("材料/.env", "SECRET")
        zf.writestr(".hidden/a.txt", "a")
    v = do_import(client, cid, [z], unzip=True)
    assert [c["to"] for c in v["copied"]] == ["材料/正常.txt"]
    assert len(v["skipped"]) == 2


# ---------- Y5：文本框只出现一次；带 DOCTYPE 的部件按失败 ----------

MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WPS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"


def _docx_with(path: pathlib.Path, body: str, prolog: str = "") -> None:
    with zipfile.ZipFile(FIXTURES / "civil-01" / "借条.docx") as zin, zipfile.ZipFile(path, "w") as zout:
        for info in zin.infolist():
            if info.filename == "word/document.xml":
                xml = (f'<?xml version="1.0" encoding="UTF-8"?>{prolog}<w:document xmlns:w="{W}" xmlns:mc="{MC}" '
                       f'xmlns:wps="{WPS}"><w:body>{body}</w:body></w:document>')
                zout.writestr(info, xml.encode("utf-8"))
            else:
                zout.writestr(info, zin.read(info))


def test_y5_textbox_once(tmp_path):
    box = '<w:txbxContent><w:p><w:r><w:t>文本框里的字</w:t></w:r></w:p></w:txbxContent>'
    body = ('<w:p><w:r><w:t>正文</w:t></w:r><w:r><mc:AlternateContent>'
            f'<mc:Choice Requires="wps"><w:drawing><wps:txbx>{box}</wps:txbx></w:drawing></mc:Choice>'
            f'<mc:Fallback><w:pict>{box}</w:pict></mc:Fallback></mc:AlternateContent></w:r></w:p>'
            f'<w:tbl><w:tr><w:tc><w:p><w:r><w:t>格</w:t></w:r><w:r><mc:AlternateContent>'
            f'<mc:Choice Requires="wps"><w:drawing><wps:txbx>{box}</wps:txbx></w:drawing></mc:Choice>'
            f'<mc:Fallback><w:pict>{box}</w:pict></mc:Fallback></mc:AlternateContent></w:r></w:p></w:tc></w:tr></w:tbl>')
    p = tmp_path / "框.docx"
    _docx_with(p, body)
    out = docx.parse(p)
    alltext = "\n".join(b.text for b in out.blocks)
    assert alltext.count("文本框里的字") == 2          # 正文一次、表格一次，各自不重复
    assert out.blocks[0].text.count("文本框里的字") == 1


def test_y5_doctype_fails(tmp_path):
    p = tmp_path / "实体.docx"
    _docx_with(p, '<w:p><w:r><w:t>A&xx;B</w:t></w:r></w:p>', prolog='<!DOCTYPE d [<!ENTITY xx "X">]>')
    with pytest.raises(ParseError) as ei:
        docx.parse(p)
    assert ei.value.reason == "corrupt"


# ---------- Y6：UTF-16 文本 ----------

@pytest.mark.parametrize("enc,bom", [("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff")])
@pytest.mark.parametrize("name", ["记事本.txt", "表.csv"])
def test_y6_utf16(tmp_path, enc, bom, name):
    p = tmp_path / name
    p.write_bytes(bom + "借款人王某丙\r\n金额,80000\r\n".encode(enc))
    out = text.parse(p)
    assert out.unit_count == 2 and out.blocks[0].text == "借款人王某丙\n金额,80000"


# ---------- Y7：重算不成退回写公式 ----------

def test_y7_recalc_failure_falls_back_to_formula(tmp_path):
    def broken(_p):
        raise ParseError("path_too_long")

    out = xlsx.parse(FIXTURES / "civil-01" / "银行流水.xlsx", recalc=broken)
    summary = next(b.text for b in out.blocks if b.label == "表:汇总")
    assert "=SUM(" in summary or "=" in summary


def test_y7_scan_xlsx_parsed_when_recalc_fails(make_client, cases_dir, monkeypatch):
    def broken(self, src, fmt, suffix=None):
        raise ParseError("path_too_long")

    monkeypatch.setattr(lo._Session, "convert", broken)
    client = make_client()
    root = cases_dir / "y7"
    cid = open_case(client, root)
    shutil.copy(FIXTURES / "civil-01" / "银行流水.xlsx", root / "银行流水.xlsx")
    scan(client, cid)
    assert by_rel(root)["银行流水.xlsx"]["status"] == "parsed"


# ---------- Y1、Y4 ----------

def test_y1_lo_base_required():
    with pytest.raises(TypeError):
        lo.Converter(pathlib.Path("x"))   # noqa
    assert not hasattr(lo, "default_lo_base")


def test_y4_no_env_override(monkeypatch, tmp_path):
    fake = tmp_path / "soffice.exe"
    fake.write_bytes(b"")
    monkeypatch.setenv("LB_SOFFICE", str(fake))
    assert lo.find_soffice() != str(fake)
