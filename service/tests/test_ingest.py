"""材料解析（Spec 5.1–5.4）：tests\\fixtures\\ 全部案件逐份导入；cite-cases.json 每条落在正确的位置标记下；
新增 / 变化 / 删除；失败清单；LibreOffice 转换后 工作区\\临时\\ 为空；原件 sha256 不变。

样本一律先复制到临时目录再操作，不在 tests\\fixtures\\ 里导入。
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

import pytest

from lawbench.config import REPO_ROOT
from lawbench.ingest import REASONS, libreoffice
from lawbench.ingest import pdf as pdf_mod

from conftest import IS_WIN, make_junction
from fakes import minimal_ole

sys.path.insert(0, str(REPO_ROOT / "contracts"))
from check_examples import validator  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures"
CASES = ["criminal-01", "civil-01", "contract-01", "attack-01", "broken", "closed-01", "tender-01", "invoices-01"]
CITE = json.loads((FIXTURES / "cite-cases.json").read_text(encoding="utf-8"))
HAS_LO = libreoffice.find_soffice() is not None
needs_lo = pytest.mark.skipif(not HAS_LO, reason="本机没有 LibreOffice")


def tree_hashes(root: pathlib.Path) -> dict[str, str]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def ok(r, schema: str) -> dict:
    assert r.status_code == 200, r.text
    body = r.json()
    errs = list(validator(f"api/{schema}.schema.json", "#/$defs/response").iter_errors(body))
    assert not errs, [e.message for e in errs]
    assert body["ok"] is True, body
    return body["value"]


def fixture_hashes() -> dict[str, str]:
    h = {}
    for c in CASES:
        for k, v in tree_hashes(FIXTURES / c).items():
            h[f"{c}/{k}"] = v
    return h


@pytest.fixture(scope="module")
def fixtures_before():
    return fixture_hashes()


def open_case(client, root: pathlib.Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    return ok(client.post("/api/case/open", json={"path": str(root)}), "case_open")["case_id"]


def index_of(root: pathlib.Path) -> dict:
    data = json.loads((root / "工作区" / "材料" / "index.json").read_text(encoding="utf-8"))
    assert not list(validator("files/material_index.schema.json").iter_errors(data))
    return data


def by_name(root: pathlib.Path) -> dict[str, dict]:
    return {m["name"]: m for m in index_of(root)["materials"]}


def blocks(text: str) -> dict[str, str]:
    """{位置标记内容: 块正文}。"""
    out: dict[str, str] = {}
    parts = re.split(r"^【([^】\n]+)】\n?", text, flags=re.M)
    for i in range(1, len(parts), 2):
        out[parts[i]] = parts[i + 1]
    return out


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def cite_hit(text: str, loc: dict, want: str) -> bool:
    bl = blocks(text)
    if loc["unit"] == "page":
        return squash(want) in squash(bl.get(f"第{loc['from']}页", ""))
    if loc["unit"] == "para":
        return squash(want) in squash(bl.get(f"第{loc['from']}段", ""))
    if loc["unit"] == "line":
        n = loc["from"]
        start = (n - 1) // 50 * 50 + 1
        lines = bl.get(f"第{start}行", "").split("\n")
        return (n - start) < len(lines) and want in lines[n - start]
    if loc["unit"] == "cell":
        row = int(re.search(r"[0-9]+", loc["ref"]).group(0))
        for line in bl.get(f"表:{loc['sheet']}", "").split("\n"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and cells[0] == str(row):
                col = col_index(loc["ref"])
                return col < len(cells) and want in cells[col]
    return False


@pytest.fixture(scope="module")
def imported(tmp_path_factory, fixtures_before):
    """把全部样本复制到临时目录，每个案件新建一个空案件后从临时副本导入；返回 {案件: (root, case_id, 导入结果)}。"""
    from starlette.testclient import TestClient

    from lawbench.app import create_app
    from lawbench.case import gate
    from lawbench.config import Config

    base = tmp_path_factory.mktemp("t5")
    src = base / "样本副本"
    for c in CASES:
        shutil.copytree(FIXTURES / c, src / c, symlinks=True)
    src_before = tree_hashes(src)
    saved = gate._registry_onedrive_folders
    gate._registry_onedrive_folders = lambda: []
    env_saved = {v: os.environ.pop(v, None) for v in gate.SYNC_ENV_VARS}
    appdata = pathlib.Path(tempfile.mkdtemp(prefix="lbad-"))  # 短路径，同 conftest 的 appdata 夹具
    app = create_app(Config(token="k" * 32, appdata=appdata), key_getter=lambda: None)
    client = TestClient(app, raise_server_exceptions=False)
    client.headers["Authorization"] = "Bearer " + "k" * 32
    out = {}
    for c in CASES:
        root = base / "cases" / c
        cid = open_case(client, root)
        v = ok(client.post("/api/materials/import", json={"case_id": cid, "paths": [str(src / c)], "target": None,
                                                         "unzip": False}), "materials_import")
        out[c] = (root, cid, v)
    yield {"cases": out, "client": client, "src": src, "src_before": src_before, "base": base}
    client.close()
    gate._registry_onedrive_folders = saved
    for k, v in env_saved.items():
        if v is not None:
            os.environ[k] = v


def test_fixtures_unchanged(imported, fixtures_before):
    assert fixture_hashes() == fixtures_before              # tests\fixtures\ 原件一个字节都没动
    assert tree_hashes(imported["src"]) == imported["src_before"]  # 导入源（临时副本）也没动


def test_import_summary(imported):
    lines = []
    for c, (root, cid, v) in imported["cases"].items():
        mats = index_of(root)["materials"]
        lines.append(f"{c}: 复制 {len(v['copied'])}，跳过 {len(v['skipped'])}，新增 {v['scan']['added']}，"
                     f"失败 {v['scan']['failed']}")
        for m in mats:
            lines.append(f"  {m['material_id']} {m['name']} [{m['type']}] {m['status']} {m['unit_count']}"
                         f"{m['unit']} 需识别页={m['pages_need_ocr']} 图文混排页={m['pages_mixed']}"
                         + (f" 原因={m['error']}" if m["error"] else "") + (f" 注={m['note']}" if m["note"] else ""))
        assert v["scan"]["added"] == len(mats)
    out = os.environ.get("LB_T5_SUMMARY")
    if out:
        pathlib.Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_list_contract(imported):
    client = imported["client"]
    for c, (root, cid, _) in imported["cases"].items():
        v = ok(client.get("/api/materials", params={"case_id": cid}), "materials_list")
        assert {m["material_id"] for m in v["materials"]} == {m["material_id"] for m in index_of(root)["materials"]}


@pytest.mark.parametrize("case", CITE, ids=[c["citation"] for c in CITE])
def test_cite_cases(imported, case):
    root = imported["cases"][case["case"]][0]
    m = by_name(root)[case["material"]]
    text = (root / m["text_path"]).read_text(encoding="utf-8")
    assert cite_hit(text, case["loc"], case["text"]), case["citation"]


def test_text_format(imported):
    root = imported["cases"]["civil-01"][0]
    m = by_name(root)["借条"]
    text = (root / m["text_path"]).read_text(encoding="utf-8")
    head = text.split("\n")
    assert head[0] == "# 借条" and head[1] == ""
    assert head[2] == f"> Source: {m['rel_path']}（文字版，{m['unit_count']}段）"
    assert re.fullmatch(r"> Collected: \d{4}-\d{2}-\d{2}", head[3])
    assert head[4] == "> Note: 含修订，已按修订后文本" and m["note"] == "含修订，已按修订后文本"
    assert "【第1段】" in text and "页眉：" in text and "页脚：" in text
    x = by_name(root)["银行流水"]
    assert (root / x["text_path"]).read_text(encoding="utf-8").split("\n")[2].endswith("（文字版，2个工作表）")
    assert m["text_path"] == f"工作区/材料/文本/{m['rel_path']}.md"


def test_revisions(imported):
    root = imported["cases"]["contract-01"][0]
    mats = by_name(root)
    assert mats["采购合同"]["note"] is None
    rev = mats["采购合同-含未处理修订"]
    assert rev["note"] == "含修订，已按修订后文本"
    bl = blocks((root / rev["text_path"]).read_text(encoding="utf-8"))
    assert "六十" in bl["第27段"] and "九十" not in bl["第27段"]  # 保留插入、去掉删除


def test_pdf_page_types(imported):
    root = imported["cases"]["criminal-01"][0]
    mats = by_name(root)
    x = mats["讯问笔录"]
    assert x["status"] == "needs_ocr" and x["pages_need_ocr"] == [1, 2, 3]
    bl = blocks((root / x["text_path"]).read_text(encoding="utf-8"))
    assert all(bl[f"第{i}页"].strip() == "（本页需识别）" for i in (1, 2, 3))
    assert mats["现场勘验图文"]["pages_mixed"] == [1] and mats["现场勘验图文"]["status"] == "parsed"
    assert mats["起诉意见书"]["pages_need_ocr"] == [] and mats["起诉意见书"]["unit_count"] == 5
    img = mats["转账截图"]
    assert img["type"] == "image" and img["status"] == "needs_ocr" and img["pages_need_ocr"] == [1]


def test_page_kind_thresholds():
    assert pdf_mod.page_kind("字" * 29, 0.0) == "needs_ocr"
    assert pdf_mod.page_kind("字" * 30, 0.30) == "text"
    assert pdf_mod.page_kind("字" * 30, 0.31) == "mixed"
    assert pdf_mod.page_kind(" \n\t" * 50, 0.0) == "needs_ocr"   # 空白不算字


def test_broken_failed_chinese(imported):
    root = imported["cases"]["broken"][0]
    mats = {pathlib.PurePosixPath(m["rel_path"]).name: m for m in index_of(root)["materials"]}
    assert {k: (m["status"], m["error"]) for k, m in mats.items()} == {
        "加密.pdf": ("failed", REASONS["encrypted"]),
        "加密.docx": ("failed", REASONS["encrypted"]),
        "截断.pdf": ("failed", REASONS["corrupt"]),
    }
    assert all(re.search(r"[一-鿿]", m["error"]) for m in mats.values())
    status = (root / "工作区" / "材料" / "_处理状态.md").read_text(encoding="utf-8")
    assert "处理失败" in status and "文件已加密" in status


def test_attack_not_followed(imported):
    root = imported["cases"]["attack-01"][0]
    rels = {m["rel_path"] for m in index_of(root)["materials"]}
    assert not any("/.dsh/" in r or r.startswith(".dsh") for r in rels)   # 以 . 开头的不当材料
    assert any(r.endswith("AGENTS.md") for r in rels)                     # AGENTS.md 只是材料内容


def test_ignored_lock_file(imported):
    root = imported["cases"]["closed-01"][0]
    rels = [m["rel_path"] for m in index_of(root)["materials"]]
    assert not any("~$" in r for r in rels) and len(rels) == 9


def test_names_unique_and_rules(imported):
    root = imported["cases"]["broken"][0]
    names = {pathlib.PurePosixPath(m["rel_path"]).name: m["name"] for m in index_of(root)["materials"]}
    # 两个"加密"重名 → 去扩展名的相对路径仍重名 → 带扩展名的相对路径
    assert names["加密.pdf"] == "broken/加密.pdf" and names["加密.docx"] == "broken/加密.docx"
    assert names["截断.pdf"] == "截断"


@needs_lo
def test_libreoffice_temp_empty(imported):
    for c, (root, _, _) in imported["cases"].items():
        assert list((root / "工作区" / "临时").iterdir()) == [], c
    root = imported["cases"]["civil-01"][0]
    bl = blocks((root / by_name(root)["银行流水"]["text_path"]).read_text(encoding="utf-8"))
    assert "| 4 | 已收利息 | 2200 |" in bl["表:汇总"]  # 无缓存值的公式经 LibreOffice 重算
    formulas = (root / "工作区" / "材料" / "公式" / (by_name(root)["银行流水"]["rel_path"] + ".txt"))
    assert "汇总!B4\t=SUM(" in formulas.read_text(encoding="utf-8")


# ---------- 新增 / 变化 / 删除 ----------

@pytest.fixture
def small_case(make_client, cases_dir):
    client = make_client()
    root = cases_dir / "小案"
    (root / "证据").mkdir(parents=True)
    shutil.copy(FIXTURES / "civil-01" / "情况说明.txt", root / "证据" / "情况说明.txt")
    shutil.copy(FIXTURES / "civil-01" / "还款记录.csv", root / "还款记录.csv")
    cid = open_case(client, root)
    return client, root, cid


def scan(client, cid) -> dict:
    return ok(client.post("/api/materials/scan", json={"case_id": cid}), "materials_scan")


def test_scan_added_unchanged_changed_deleted(small_case):
    client, root, cid = small_case
    assert scan(client, cid) == {"added": 2, "changed": 0, "removed": 0, "failed": 0, "review_needed": True}
    assert scan(client, cid) == {"added": 0, "changed": 0, "removed": 0, "failed": 0, "review_needed": False}
    m = by_name(root)["情况说明"]
    f = root / "证据" / "情况说明.txt"
    f.write_text(f.read_text(encoding="utf-8") + "新增一行 LBTEST-CHANGED\n", encoding="utf-8")
    assert scan(client, cid) == {"added": 0, "changed": 1, "removed": 0, "failed": 0, "review_needed": True}
    m2 = by_name(root)["情况说明"]
    assert m2["material_id"] == m["material_id"] and m2["sha256"] != m["sha256"]
    assert "LBTEST-CHANGED" in (root / m2["text_path"]).read_text(encoding="utf-8")
    f.unlink()
    assert scan(client, cid)["removed"] == 1
    m3 = by_name(root)["情况说明"]
    assert m3["status"] == "source_deleted" and (root / m3["text_path"]).is_file()  # 保留文本
    lst = ok(client.get("/api/materials", params={"case_id": cid}), "materials_list")["materials"]
    assert [x["status"] for x in lst if x["name"] == "情况说明"] == ["source_deleted"]
    assert scan(client, cid)["removed"] == 0  # 已标删除的不重复计数


def test_touch_without_change(small_case):
    client, root, cid = small_case
    scan(client, cid)
    f = root / "还款记录.csv"
    os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 100))
    assert scan(client, cid)["changed"] == 0  # 修改时间变了但哈希没变


def test_move_is_delete_plus_add(small_case):
    client, root, cid = small_case
    scan(client, cid)
    old = by_name(root)["还款记录"]
    (root / "证据" / "新目录").mkdir()
    os.rename(root / "还款记录.csv", root / "证据" / "新目录" / "还款记录.csv")
    s = scan(client, cid)
    assert s["added"] == 1 and s["removed"] == 1
    mats = index_of(root)["materials"]
    ids = [m["material_id"] for m in mats]
    assert len(ids) == len(set(ids)) and index_of(root)["next_seq"] == 4   # 编号不复用
    new = [m for m in mats if m["rel_path"] == "证据/新目录/还款记录.csv"][0]
    assert new["material_id"] != old["material_id"]


def test_name_collision_renames_existing(small_case):
    client, root, cid = small_case
    scan(client, cid)
    first = by_name(root)["情况说明"]
    (root / "补充").mkdir()
    shutil.copy(FIXTURES / "attack-01" / "案情材料.txt", root / "补充" / "情况说明.txt")
    scan(client, cid)
    names = {m["rel_path"]: m["name"] for m in index_of(root)["materials"]}
    assert names["证据/情况说明.txt"] == "证据/情况说明" and names["补充/情况说明.txt"] == "补充/情况说明"
    text = (root / first["text_path"]).read_text(encoding="utf-8")
    assert text.startswith("# 证据/情况说明\n")  # 已有材料的名字改长，文本标题同步


def test_name_spaces_replaced(make_client, cases_dir):
    client = make_client()
    root = cases_dir / "空格"
    root.mkdir()
    (root / "一审 起诉状、附件.txt").write_text("x", encoding="utf-8")
    cid = open_case(client, root)
    scan(client, cid)
    assert list(by_name(root)) == ["一审_起诉状_附件"]


@pytest.mark.skipif(not IS_WIN, reason="junction")
def test_scan_skips_junction(make_client, cases_dir, tmp_path):
    client = make_client()
    root = cases_dir / "链接案"
    root.mkdir()
    outside = tmp_path / "案外"
    outside.mkdir()
    (outside / "秘密.txt").write_text("LBTEST-OUTSIDE", encoding="utf-8")
    make_junction(root / "外部目录链接", outside)
    cid = open_case(client, root)
    assert scan(client, cid)["added"] == 0


def test_too_large(small_case, monkeypatch):
    client, root, cid = small_case
    from lawbench.case import materials
    monkeypatch.setattr(materials, "MAX_BYTES", 1000)
    shutil.copy(FIXTURES / "criminal-01" / "起诉意见书.pdf", root / "大.pdf")
    scan(client, cid)
    m = by_name(root)["大"]
    assert m["status"] == "failed" and m["error"] == REASONS["too_large"]


def test_too_many_pages(small_case, monkeypatch):
    client, root, cid = small_case
    monkeypatch.setattr(pdf_mod, "MAX_PAGES", 3)
    shutil.copy(FIXTURES / "criminal-01" / "起诉意见书.pdf", root / "多页.pdf")
    scan(client, cid)
    m = by_name(root)["多页"]
    assert m["status"] == "failed" and m["error"] == REASONS["too_large"]


def test_corrupt_text_and_image(small_case):
    client, root, cid = small_case
    (root / "坏图.jpg").write_bytes(b"not an image")
    (root / "二进制.txt").write_bytes(b"\x00\x01\x02" * 10)
    (root / "坏表.xlsx").write_bytes(b"PK\x03\x04 broken")
    scan(client, cid)
    mats = by_name(root)
    for n in ("坏图", "二进制", "坏表"):
        assert mats[n]["status"] == "failed" and mats[n]["error"] == REASONS["corrupt"], n


def test_gb18030_csv(small_case):
    client, root, cid = small_case
    scan(client, cid)
    m = by_name(root)["还款记录"]
    assert "手机银行" in (root / m["text_path"]).read_text(encoding="utf-8")


def test_lines_marked_every_50(make_client, cases_dir):
    client = make_client()
    root = cases_dir / "长文本"
    root.mkdir()
    (root / "长.txt").write_text("\n".join(f"第{i}行内容" for i in range(1, 121)) + "\n", encoding="utf-8")
    cid = open_case(client, root)
    scan(client, cid)
    m = by_name(root)["长"]
    bl = blocks((root / m["text_path"]).read_text(encoding="utf-8"))
    assert list(bl) == ["第1行", "第51行", "第101行"] and m["unit_count"] == 120
    assert cite_hit((root / m["text_path"]).read_text(encoding="utf-8"), {"unit": "line", "from": 77}, "第77行内容")


# ---------- doc / xls：LibreOffice 转换 ----------

@needs_lo
def test_doc_and_xls_converted(make_client, cases_dir, tmp_path, lo_base):
    work = tmp_path / "conv"
    work.mkdir()
    # 样本用产品自己的转换器生成（配置目录在短路径下；测试放在很深的目录里也能跑）
    with libreoffice.Converter(tmp_path / "gen", lo_base=lo_base).session() as s:
        (work / "通知.doc").write_bytes(s.convert(FIXTURES / "tender-01" / "补充通知.docx", "doc").read_bytes())
        (work / "流水.xls").write_bytes(s.convert(FIXTURES / "civil-01" / "银行流水.xlsx", "xls").read_bytes())
    client = make_client()
    root = cases_dir / "转换"
    root.mkdir()
    shutil.copy(work / "通知.doc", root / "通知.doc")
    shutil.copy(work / "流水.xls", root / "流水.xls")
    cid = open_case(client, root)
    assert scan(client, cid)["failed"] == 0
    mats = by_name(root)
    assert mats["通知"]["note"] == "由 doc 转换" and mats["通知"]["type"] == "doc" and mats["通知"]["unit"] == "para"
    assert "2026年10月27日" in (root / mats["通知"]["text_path"]).read_text(encoding="utf-8")
    assert mats["流水"]["note"] == "由 xls 转换" and mats["流水"]["unit"] == "cell"
    assert "【表:流水】" in (root / mats["流水"]["text_path"]).read_text(encoding="utf-8")
    assert list((root / "工作区" / "临时").iterdir()) == []
    assert not list(root.glob(".~lock*")) and not list(root.glob("*.~lock*"))  # 原件旁不留锁文件


def test_converter_missing(make_client, cases_dir, monkeypatch):
    monkeypatch.setattr(libreoffice, "find_soffice", lambda: None)
    client = make_client()
    root = cases_dir / "无转换器"
    root.mkdir()
    minimal_ole(root / "旧.doc", {"WordDocument": b"LBFX"})
    cid = open_case(client, root)
    scan(client, cid)
    m = by_name(root)["旧"]
    assert m["status"] == "failed" and m["error"] == REASONS["no_converter"]
    assert list((root / "工作区" / "临时").iterdir()) == []
