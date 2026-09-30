"""T9 全文检索（Spec 第 11 节；工单 T9）：G-9 检索验证集、契约、耗时、归一化、扩展、短词、按需建索引。"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
import tempfile
import time

import pytest
from starlette.testclient import TestClient

from lawbench import logs
from lawbench.app import create_app
from lawbench.case import gate
from lawbench.config import REPO_ROOT, Config
from lawbench.search import expand, fts
from lawbench.search.normalize import normalize, normalize_with_map

from t8_helpers import ok, validator

FIXTURES = REPO_ROOT / "tests" / "fixtures"
CASES = ("civil-01", "criminal-01", "contract-01", "closed-01", "tender-01")
TOKEN = "s" * 40
UNIT_WORD = {"page": "页", "para": "段", "line": "行"}


def test_sqlite_version():
    """trigram 分词要 SQLite ≥ 3.34（工单 T9 第 4 步）。"""
    assert tuple(int(x) for x in sqlite3.sqlite_version.split(".")) >= (3, 34, 0), sqlite3.sqlite_version
    con = sqlite3.connect(":memory:")
    con.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")
    con.close()


def tree_hashes(p: pathlib.Path) -> dict:
    return {str(f.relative_to(p)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(p.rglob("*")) if f.is_file() and f.relative_to(p).parts[0] not in ("工作区", "成果")}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    base = tmp_path_factory.mktemp("t9")
    saved = gate._registry_onedrive_folders
    gate._registry_onedrive_folders = lambda: []
    appdata = pathlib.Path(tempfile.mkdtemp(prefix="lbad-"))
    client = TestClient(create_app(Config(token=TOKEN, appdata=appdata), key_getter=lambda: None),
                        raise_server_exceptions=False)
    client.headers["Authorization"] = f"Bearer {TOKEN}"
    cases = {}
    for c in CASES:
        root = base / c
        shutil.copytree(FIXTURES / c, root)
        cid = ok(client.post("/api/case/open", json={"path": str(root)}), "api/case_open.schema.json")["case_id"]
        ok(client.post("/api/materials/scan", json={"case_id": cid}), "api/materials_scan.schema.json")
        cases[c] = (root, cid, tree_hashes(root))
    yield {"client": client, "cases": cases, "appdata": appdata}
    client.close()
    gate._registry_onedrive_folders = saved
    logs.close()
    shutil.rmtree(appdata, ignore_errors=True)


def search(world, case: str, q: str) -> dict:
    return ok(world["client"].get("/api/search", params={"case_id": world["cases"][case][1], "q": q}),
              "api/search.schema.json")


def expected_citation(item: dict) -> str:
    loc = item["expect_loc"]
    if loc["unit"] == "cell":
        return f"〔{item['expect_material']} {loc['sheet']}!{loc['ref']}〕"
    return f"〔{item['expect_material']} 第{loc['from']}{UNIT_WORD[loc['unit']]}〕"


G9 = json.loads((FIXTURES / "search-cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("item", G9, ids=[f"{x['case']}:{x['query']}" for x in G9])
def test_g9(world, item):
    v = search(world, item["case"], item["query"])
    want = expected_citation(item)
    hits = [h for h in v["hits"] if h["citation"] == want]
    assert hits, (want, [h["citation"] for h in v["hits"]])
    expect_match = "expanded" if "found_as" in item else "exact"
    assert hits[0]["match"] == expect_match, hits[0]
    if "found_as" in item:
        assert normalize(item["found_as"]) in normalize(hits[0]["snippet"])
    else:
        assert normalize(item["query"]) in normalize(hits[0]["snippet"])


def test_g9_report_and_speed(world):
    """g9.txt：逐条列出命中情况；criminal-01 上 20 次查询的平均耗时（含本进程第一次查询时的建索引）。"""
    lines = []
    hit = 0
    for item in G9:
        v = search(world, item["case"], item["query"])
        want = expected_citation(item)
        h = next((h for h in v["hits"] if h["citation"] == want), None)
        hit += h is not None
        lines.append(f"{'命中' if h else '未命中'}\t{item['kind']}\t{item['case']}\t{item['query']}\t期望 {want}\t"
                     f"{('匹配 ' + h['match']) if h else ''}\t共 {v['total']} 条")
    queries = ["吴某", "郑某", "王某", "某某投资", "2025-03-10", "8万", "虚公刑诉字〔2026〕417号", "起诉意见书",
               "犯罪嫌疑人", "经审查", "2025年3月10日", "80000", "被害人", "公安局", "诈骗", "银行", "转账", "某", "案",
               "2025.3.10"]
    fts._state.clear()                                   # 从本进程第一次查询算起，含建索引
    t0 = time.perf_counter()
    for q in queries:
        search(world, "criminal-01", q)
    avg_ms = (time.perf_counter() - t0) * 1000 / len(queries)
    lines.append(f"\n命中率：{hit}/{len(G9)}")
    lines.append(f"criminal-01 上 {len(queries)} 次查询平均耗时：{avg_ms:.1f} ms（含第一次查询时整案建索引）")
    out = os.environ.get("LB_T9_G9")
    if out:
        pathlib.Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert hit == len(G9)
    assert avg_ms < 200, avg_ms


def test_originals_untouched(world):
    for c, (root, _, before) in world["cases"].items():
        search(world, c, "某某")
        assert tree_hashes(root) == before, c


def test_query_not_logged(world):
    search(world, "civil-01", "借款人王某丙")
    logs.close()
    text = "".join(p.read_text(encoding="utf-8") for p in (world["appdata"] / "logs").glob("*"))
    logs.setup(world["appdata"])
    assert "借款人王某丙" not in text and '"module": "search"' in text


def test_bad_requests(world):
    c = world["client"]
    cid = world["cases"]["civil-01"][1]
    assert c.get("/api/search", params={"case_id": cid, "q": ""}).json()["error"]["code"] == "INVALID_ARGUMENT"
    assert c.get("/api/search", params={"case_id": cid, "q": "x" * 101}).json()["error"]["code"] == "INVALID_ARGUMENT"
    assert c.get("/api/search", params={"case_id": cid}).json()["error"]["code"] == "INVALID_ARGUMENT"
    assert c.get("/api/search", params={"case_id": cid, "q": "   "}).json()["error"]["code"] == "INVALID_ARGUMENT"


def test_max_hits_and_truncated(world):
    root, cid, _ = world["cases"]["criminal-01"]
    index = world["client"].app.state.lb.materials.index(cid)
    v = fts.search(str(gate.check_root(str(root))), cid, index, "某", max_hits=2)
    errs = list(validator("tools/case_search.schema.json", "#/$defs/result").iter_errors(v))
    assert not errs and len(v["hits"]) == 2 and v["total"] > 2 and v["truncated"] is True


# ---------- 归一化 ----------

def test_normalize_rules():
    assert normalize("ＡＢＣ１２３，") == "ABC123,"                     # 全角转半角
    assert normalize("80,000.00 元") == "80000.00 元"                    # 去千分位
    assert normalize("甲　\t\n 乙") == "甲 乙"                        # 统一空白
    text = "金额：８０,０００元"
    norm, where = normalize_with_map(text)
    assert norm == "金额:80000元"
    k = norm.find("80000")
    assert text[where[k]:where[k + 4] + 1] == "８０,０００"                # 位置能换回原文


# ---------- 扩展 ----------

@pytest.mark.parametrize("q,must", [
    ("2025年3月10日", {"2025-03-10", "2025.3.10"}),
    ("2025-03-10", {"2025年3月10日", "2025.3.10"}),
    ("2025.3.10", {"2025年3月10日", "2025-03-10"}),
    ("8万", {"80000"}),
    ("80000", {"8万"}),
    ("80,000", {"8万"}),
    ("8.5万元", {"85000"}),
])
def test_expand(q, must):
    vs = expand.variants(q)
    assert vs[0][1] == "exact" and all(k == "expanded" for _, k in vs[1:])
    assert must <= {v for v, _ in vs[1:]}


def test_expand_nothing_for_plain_text():
    assert expand.variants("王某") == [("王某", "exact")]


# ---------- 短词、边界、大小写、按需建索引 ----------

@pytest.fixture
def small(make_client, cases_dir):
    client = make_client()
    root = cases_dir / "小案"
    root.mkdir()
    (root / "说明.txt").write_text("甲\n借款180000元\n借款8万元整\n案号XG-ZB-2026-0931\n电话13812345678\n",
                                   encoding="utf-8")
    cid = ok(client.post("/api/case/open", json={"path": str(root)}), "api/case_open.schema.json")["case_id"]
    ok(client.post("/api/materials/scan", json={"case_id": cid}), "api/materials_scan.schema.json")
    return client, root, cid


def q(client, cid, text):
    return ok(client.get("/api/search", params={"case_id": cid, "q": text}), "api/search.schema.json")


def test_one_char_query_uses_instr(small):
    client, _, cid = small
    v = q(client, cid, "甲")
    assert [h["citation"] for h in v["hits"]] == ["〔说明 第1行〕"]


def test_expanded_numbers_have_digit_boundaries(small):
    client, _, cid = small
    v = q(client, cid, "80000")          # 扩展成"8万"：命中第 3 行；"180000" 里的 80000 是原样查询，照常命中
    got = {(h["citation"], h["match"]) for h in v["hits"]}
    assert ("〔说明 第3行〕", "expanded") in got and ("〔说明 第2行〕", "exact") in got
    v = q(client, cid, "8万")            # 扩展成"80000"：不命中"180000"
    assert {h["citation"] for h in v["hits"]} == {"〔说明 第3行〕"}


def test_partial_digits_found(small):
    client, _, cid = small
    assert [h["citation"] for h in q(client, cid, "5678")["hits"]] == ["〔说明 第5行〕"]   # 不静默搜不到


def test_case_insensitive(small):
    client, _, cid = small
    assert [h["citation"] for h in q(client, cid, "xg-zb-2026-0931")["hits"]] == ["〔说明 第4行〕"]


def test_index_follows_material_changes(small):
    client, root, cid = small
    assert q(client, cid, "新写的一句")["total"] == 0
    (root / "说明.txt").write_text("新写的一句\n", encoding="utf-8")
    ok(client.post("/api/materials/scan", json={"case_id": cid}), "api/materials_scan.schema.json")
    assert [h["citation"] for h in q(client, cid, "新写的一句")["hits"]] == ["〔说明 第1行〕"]
    assert q(client, cid, "13812345678")["total"] == 0                # 旧内容已从索引里删掉
    (root / "说明.txt").unlink()
    (root / "另一份.txt").write_text("另一份的内容\n", encoding="utf-8")
    ok(client.post("/api/materials/scan", json={"case_id": cid}), "api/materials_scan.schema.json")
    assert [h["name"] for h in q(client, cid, "另一份的内容")["hits"]] == ["另一份"]


def test_index_written_to_case_db(small):
    client, root, cid = small
    q(client, cid, "借款")
    con = sqlite3.connect(root / "工作区" / "case.db")
    units = con.execute("SELECT material_id, unit, loc_from, loc_to FROM search_units").fetchall()
    hits = con.execute("SELECT rowid FROM search_fts WHERE search_fts MATCH '\"XG-ZB\"'").fetchall()
    con.close()
    assert units == [("M0001", "line", 1, 5)] and len(hits) == 1


def test_snippet_from_original_text(make_client, cases_dir):
    client = make_client()
    root = cases_dir / "全角"
    root.mkdir()
    (root / "a.txt").write_text("前面" + "字" * 60 + "金额８０，０００元" + "尾" * 60 + "\n", encoding="utf-8")
    cid = ok(client.post("/api/case/open", json={"path": str(root)}), "api/case_open.schema.json")["case_id"]
    ok(client.post("/api/materials/scan", json={"case_id": cid}), "api/materials_scan.schema.json")
    h = q(client, cid, "80000")["hits"][0]
    assert "８０，０００" in h["snippet"]                                   # 片段是原文
    assert h["snippet"] == "字" * 38 + "金额" + "８０，０００" + "元" + "尾" * 39   # 命中处前后各 40 字，取原文


def test_material_leaving_index_is_removed(small):
    """材料不在索引里了（例如重解析失败、没有材料文本）：它的检索单元删掉。"""
    client, root, cid = small
    real_root = client.app.state.lb.cases.root_of(cid)
    index = client.app.state.lb.materials.index(cid)
    assert fts.search(real_root, cid, index, "借款")["total"] > 0
    gone = dict(index, materials=[dict(m, status="failed") for m in index["materials"]])
    assert fts.search(real_root, cid, gone, "借款")["total"] == 0
    con = sqlite3.connect(root / "工作区" / "case.db")
    assert con.execute("SELECT count(*) FROM search_units").fetchone() == (0,)
    con.close()
    assert fts.search(real_root, cid, index, "借款")["total"] > 0          # 回来了照常重建


def test_exact_ranked_before_expanded(make_client, cases_dir):
    client = make_client()
    root = cases_dir / "排序"
    root.mkdir()
    (root / "a.txt").write_text("借款8万元\n金额80000元\n", encoding="utf-8")
    cid = ok(client.post("/api/case/open", json={"path": str(root)}), "api/case_open.schema.json")["case_id"]
    ok(client.post("/api/materials/scan", json={"case_id": cid}), "api/materials_scan.schema.json")
    v = q(client, cid, "80000")
    assert [(h["citation"], h["match"]) for h in v["hits"]] == [("〔a 第2行〕", "exact"), ("〔a 第1行〕", "expanded")]


# ---------- 裁决 1548 第 1 条：扫描完就建索引，出错不影响扫描 ----------

def test_index_built_at_scan(make_client, cases_dir):
    client = make_client()
    root = cases_dir / "扫描即建"
    root.mkdir()
    (root / "a.txt").write_text("扫描完就该有索引\n", encoding="utf-8")
    cid = ok(client.post("/api/case/open", json={"path": str(root)}), "api/case_open.schema.json")["case_id"]
    ok(client.post("/api/materials/scan", json={"case_id": cid}), "api/materials_scan.schema.json")
    con = sqlite3.connect(root / "工作区" / "case.db")
    n = con.execute("SELECT count(*) FROM search_units").fetchone()[0]
    fts_hits = con.execute("SELECT count(*) FROM search_fts WHERE search_fts MATCH '\"就该有\"'").fetchone()[0]
    con.close()
    assert n == 1 and fts_hits == 1                                    # 还没检索过，索引已经在了


def test_index_failure_does_not_break_scan(make_client, cases_dir, appdata, monkeypatch):
    client = make_client()
    root = cases_dir / "建索引出错"
    root.mkdir()
    (root / "a.txt").write_text("内容\n", encoding="utf-8")
    cid = ok(client.post("/api/case/open", json={"path": str(root)}), "api/case_open.schema.json")["case_id"]

    def boom(*a, **k):
        raise RuntimeError("坏了")

    monkeypatch.setattr(fts, "refresh", boom)
    v = ok(client.post("/api/materials/scan", json={"case_id": cid}), "api/materials_scan.schema.json")
    assert v["added"] == 1
    monkeypatch.undo()
    assert [h["citation"] for h in q(client, cid, "内容")["hits"]] == ["〔a 第1行〕"]   # 检索前按需补，自愈
    logs.close()
    text = "".join(p.read_text(encoding="utf-8") for p in (appdata / "logs").glob("*"))
    assert '"op": "index", "status": "fail"' in text and "RuntimeError" in text


# ---------- 裁决 1548 第 2 条：case_search 工具用 T9 ----------

def test_case_search_tool_uses_t9(small):
    client, root, cid = small
    tid = ok(client.post("/core/task/begin", json={"session_id": "s-t9", "cwd": str(root)}),
             "core/task_begin.schema.json")["task_id"]
    v = ok(client.post("/core/tool", json={"task_id": tid, "tool": "case_search", "args": {"query": "8万"}}),
           "core/tool.schema.json")
    errs = list(validator("tools/case_search.schema.json", "#/$defs/result").iter_errors(v))
    assert not errs
    assert [(h["citation"], h["match"]) for h in v["hits"]] == [("〔说明 第3行〕", "exact")]
    v = ok(client.post("/core/tool", json={"task_id": tid, "tool": "case_search", "args": {"query": "80000"}}),
           "core/tool.schema.json")
    assert ("〔说明 第3行〕", "expanded") in {(h["citation"], h["match"]) for h in v["hits"]}   # 扩展：T8 临时实现没有
