"""8 个 AI 工具（Spec 4.4、20.4；工单 T8 第 4、7 步）：每个工具至少 3 个用例（正常、边界、越权或错误），
返回全部按契约校验；越权参数（路径、..）被拒；草稿同标题再存版本加 1；reads.json 与覆盖清单一致。"""
from __future__ import annotations

import json
import re

import pytest

from lawbench.case import texts

from t8_helpers import CASE_FILES, Env, fail, ok, validator

CITATION = validator("common.schema.json", "#/$defs/citation_text")


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    e = Env(tmp_path_factory.mktemp("t8tools"), CASE_FILES)
    yield e
    e.close()


@pytest.fixture
def tid(env, request):
    return env.begin(f"sess-{request.node.name}")["task_id"]


def names(env) -> dict:
    idx = json.loads((env.root / "工作区" / "材料" / "index.json").read_text(encoding="utf-8"))
    return {m["name"]: m for m in idx["materials"]}


# ---------- 通用 ----------

@pytest.mark.parametrize("tool,args", [
    ("case_no_such", {}), ("case_read_material", {"name": "借条", "path": "C:\\Windows\\win.ini"}),
    ("case_list_materials", {"x": 1}), ("case_read_material", {}), ("case_search", {"query": ""}),
    ("case_save_draft", {"title": "../../evil", "content": "x"}), ("case_save_draft", {"title": "a:b", "content": "x"}),
])
def test_bad_args(env, tid, tool, args):
    fail(env.tool(tid, tool, args), "INVALID_ARGUMENT")


# ---------- case_list_materials ----------

def test_list_materials(env, tid):
    v = env.tool_ok(tid, "case_list_materials", {})
    by = {m["name"]: m for m in v["materials"]}
    assert v["total"] == len(v["materials"]) == len(CASE_FILES)
    assert by["借条"]["unit"] == "para" and by["加密"]["status"] == "failed" and by["加密"]["error"]
    assert all("rel_path" not in m and "path" not in m for m in v["materials"])   # AI 看不到路径


def test_list_materials_empty_case(tmp_path_factory):
    e = Env(tmp_path_factory.mktemp("t8empty"), {})
    try:
        t = e.begin()["task_id"]
        assert e.tool_ok(t, "case_list_materials", {}) == {"materials": [], "total": 0}
    finally:
        e.close()


def test_list_materials_unknown_task(env):
    fail(env.tool("T-20260101000000-0000", "case_list_materials", {}), "TASK_NOT_FOUND")


# ---------- case_read_material ----------

def test_read_para(env, tid):
    v = env.tool_ok(tid, "case_read_material", {"name": "借条"})
    assert v["start"] == 1 and v["unit"] == "para" and "【第1段】" in v["text"] and "【第4段】" in v["text"]
    assert v["has_more"] is False and v["next_start"] is None and v["end"] == names(env)["借条"]["unit_count"]


def test_read_paging_covers_everything(env, tid):
    seen, start, rounds = [], 1, 0
    while True:
        v = env.tool_ok(tid, "case_read_material", {"name": "采购合同", "start": start, "max_chars": 500})
        assert len(v["text"]) <= 500
        seen.append((v["start"], v["end"]))
        rounds += 1
        if not v["has_more"]:
            break
        assert v["next_start"] == v["end"] + 1
        start = v["next_start"]
    assert rounds > 1 and seen[0][0] == 1 and seen[-1][1] == names(env)["采购合同"]["unit_count"]
    reads = env.read_json(tid, "reads.json", "files/reads.schema.json")["reads"]
    assert [(r["from"], r["to"]) for r in reads] == seen
    assert all(r["material_version"] == names(env)["采购合同"]["sha256"] for r in reads)


def test_read_line_and_cell(env, tid):
    v = env.tool_ok(tid, "case_read_material", {"name": "还款记录", "start": 3})
    assert v["unit"] == "line" and v["text"].startswith("【第3行】") and v["start"] == 3
    x = env.tool_ok(tid, "case_read_material", {"name": "银行流水"})
    assert x["unit"] == "cell" and "【表:流水】" in x["text"] and "【表:汇总】" in x["text"]
    assert "| 4 | 已收利息 | 2200 |" in x["text"]


def test_read_page(env, tid):
    v = env.tool_ok(tid, "case_read_material", {"name": "起诉意见书", "start": 2, "max_chars": 800})
    assert v["unit"] == "page" and v["text"].startswith("【第2页】") and v["start"] == 2


@pytest.mark.parametrize("name,code", [("不存在", "MATERIAL_NOT_FOUND"), ("../起诉意见书", "MATERIAL_NOT_FOUND"),
                                       ("C:\\Windows\\win.ini", "MATERIAL_NOT_FOUND"),
                                       ("证据/借条.docx", "MATERIAL_NOT_FOUND"),
                                       ("加密", "MATERIAL_NOT_READY"), ("讯问笔录", "MATERIAL_NOT_READY")])
def test_read_errors(env, tid, name, code):
    fail(env.tool(tid, "case_read_material", {"name": name}), code)


def test_read_tampered_index_rel_path(env, tid):
    """index.json 里的 rel_path 被改成指向 工作区（例如别的途径改写了文件）：拼材料文本路径前先过闸门，拒绝。"""
    p = env.root / "工作区" / "材料" / "index.json"
    before = p.read_bytes()
    data = json.loads(before)
    m = next(x for x in data["materials"] if x["name"] == "情况说明")
    m["rel_path"] = "工作区/wiki/待确认.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    try:
        fail(env.tool(tid, "case_read_material", {"name": "情况说明"}), "OUT_OF_CASE")
    finally:
        p.write_bytes(before)


def test_read_start_out_of_range(env, tid):
    fail(env.tool(tid, "case_read_material", {"name": "借条", "start": 9999}), "INVALID_ARGUMENT")
    fail(env.tool(tid, "case_read_material", {"name": "借条", "max_chars": 9000}), "INVALID_ARGUMENT")


# ---------- case_search ----------

def test_search_hits_with_citation(env, tid):
    v = env.tool_ok(tid, "case_search", {"query": "李某乙"})
    assert v["total"] >= 1 and v["hits"]
    for h in v["hits"]:
        assert not list(CITATION.iter_errors(h["citation"])), h["citation"]
        assert "李某乙" in h["snippet"] and h["match"] == "exact"


def test_search_normalization_and_cells(env, tid):
    v = env.tool_ok(tid, "case_search", {"query": "８０，０００"})      # 全角数字、千分位
    assert any(h["name"] == "银行流水" and re.search(r"!D3〕$", h["citation"]) for h in v["hits"]), v["hits"]


def test_search_limit_and_none(env, tid):
    v = env.tool_ok(tid, "case_search", {"query": "的", "max_hits": 2})
    assert len(v["hits"]) == 2 and v["total"] > 2 and v["truncated"] is True
    assert env.tool_ok(tid, "case_search", {"query": "绝对不会出现的检索词LBX"}) == {"hits": [], "total": 0,
                                                                              "truncated": False}


# ---------- case_read_input ----------

def _task_with_input(env, content: str, session: str) -> str:
    src = env.begin(f"{session}-src")["task_id"]
    path = env.tool_ok(src, "case_save_draft", {"title": f"输入{session}", "content": content})["path"]
    ok(env.client.post("/api/task", json={"case_id": env.case_id, "session_id": session, "entry": None, "skill": None,
                                          "inputs": [path],
                                          "params": {"thinking": "中", "window": "32K", "max_tokens": 4096}}),
       "api/task_create.schema.json")
    return env.begin(session)["task_id"]


def test_read_input_paging(env):
    t = _task_with_input(env, "\n".join(f"第{i}行：前序成果内容" for i in range(1, 401)), "sess-ri")
    v = env.tool_ok(t, "case_read_input", {"index": 1, "max_chars": 500})
    assert v["start"] == 1 and v["has_more"] is True and v["next_start"] == v["end"] + 1 and len(v["text"]) <= 500
    w = env.tool_ok(t, "case_read_input", {"index": 1, "start": 400})
    assert w["text"] == "第400行：前序成果内容" and w["has_more"] is False and w["next_start"] is None


def test_read_input_errors(env):
    t = _task_with_input(env, "一行", "sess-ri2")
    fail(env.tool(t, "case_read_input", {"index": 2}), "INVALID_ARGUMENT")
    fail(env.tool(t, "case_read_input", {"index": 1, "start": 5}), "INVALID_ARGUMENT")
    fail(env.tool(t, "case_read_input", {"index": 1, "path": "x"}), "INVALID_ARGUMENT")


def test_read_input_no_inputs(env, tid):
    fail(env.tool(tid, "case_read_input", {"index": 1}), "INVALID_ARGUMENT")


# ---------- case_read_wiki ----------

def test_read_wiki_missing(env, tid):
    v = env.tool_ok(tid, "case_read_wiki", {"section": "时间线"})
    assert "还没有生成 wiki" in v["text"] and v["updated_at"] is None and v["stale"] is False


def test_read_wiki_section_and_summary(env, tid):
    wiki = env.root / "工作区" / "wiki"
    (wiki / "案件").mkdir(parents=True, exist_ok=True)
    (wiki / "材料").mkdir(parents=True, exist_ok=True)
    (wiki / "案件" / "时间线.md").write_text("# 时间线\n\n2025年3月10日 出借〔借条 第3段〕\n", encoding="utf-8")
    mid = names(env)["借条"]["material_id"]
    (wiki / "材料" / f"{mid}.md").write_text("# 借条\n\n摘要\n", encoding="utf-8")
    v = env.tool_ok(tid, "case_read_wiki", {"section": "时间线"})
    assert "2025年3月10日" in v["text"] and v["updated_at"]
    assert env.tool_ok(tid, "case_read_wiki", {"section": "材料摘要", "name": "借条"})["text"].startswith("# 借条")
    card = env.tool_ok(tid, "case_read_wiki", {"section": "卡片"})
    assert "还没有生成 wiki" in card["text"]


def test_read_wiki_errors(env, tid):
    fail(env.tool(tid, "case_read_wiki", {"section": "材料摘要"}), "INVALID_ARGUMENT")
    fail(env.tool(tid, "case_read_wiki", {"section": "材料摘要", "name": "不存在"}), "MATERIAL_NOT_FOUND")
    fail(env.tool(tid, "case_read_wiki", {"section": "../../证据"}), "INVALID_ARGUMENT")


# ---------- case_save_draft ----------

def test_save_draft_versions(env, tid):
    a = env.tool_ok(tid, "case_save_draft", {"title": "审查意见", "content": "第一版"})
    b = env.tool_ok(tid, "case_save_draft", {"title": "审查意见", "content": "第二版"})
    c = env.tool_ok(tid, "case_save_draft", {"title": "律师函", "content": "另一篇"})
    assert (a["version"], b["version"], c["version"]) == (1, 2, 1)
    assert a["path"] == f"工作区/任务/{tid}/草稿/审查意见-v1.md"
    assert (env.root / a["path"]).read_text(encoding="utf-8") == "第一版"     # 旧版本保留
    res = env.read_json(tid, "result.json", "files/result.schema.json")
    assert [(d["title"], d["version"]) for d in res["drafts"]] == [("审查意见", 1), ("审查意见", 2), ("律师函", 1)]
    assert b["citation_check"] == {"passed": True, "problems": [], "stats": {"citations": 0, "must_fix": 0, "hints": 0}}


def test_save_draft_coverage_matches_reads(env, tid):
    env.tool_ok(tid, "case_read_material", {"name": "借条"})                       # 读完
    env.tool_ok(tid, "case_read_material", {"name": "采购合同", "max_chars": 500})  # 读了一部分
    v = env.tool_ok(tid, "case_save_draft", {"title": "覆盖", "content": "x"})
    cov = v["coverage"]
    assert "借条" in cov["fully_read"]
    part = [p for p in cov["partially_read"] if p["name"] == "采购合同"][0]
    assert 0 < part["read_units"] < part["total_units"]
    assert "起诉意见书" in cov["not_read"] and any(u["name"] == "加密" for u in cov["unreadable"])
    assert set(v["not_fully_read"]) == {p["name"] for p in cov["partially_read"]} | set(cov["not_read"])
    assert "加密" not in v["not_fully_read"]
    assert cov["total"] == len(CASE_FILES)


def test_coverage_ignores_old_version_reads(tmp_path_factory):
    """读完之后原件变了（重扫后 sha256 不同）：旧版本的读取记录不算，覆盖清单里这份材料回到"未读"。"""
    from t8_helpers import FIXTURES
    e = Env(tmp_path_factory.mktemp("t8ver"), {"说明.txt": FIXTURES / "civil-01" / "情况说明.txt"})
    try:
        t = e.begin()["task_id"]
        e.tool_ok(t, "case_read_material", {"name": "说明"})
        assert e.tool_ok(t, "case_save_draft", {"title": "a", "content": "x"})["coverage"]["fully_read"] == ["说明"]
        f = e.root / "说明.txt"
        f.write_text(f.read_text(encoding="utf-8") + "新增一行\n", encoding="utf-8")
        ok(e.client.post("/api/materials/scan", json={"case_id": e.case_id}), "api/materials_scan.schema.json")
        cov = e.tool_ok(t, "case_save_draft", {"title": "a", "content": "y"})["coverage"]
        assert cov["fully_read"] == [] and cov["not_read"] == ["说明"]
    finally:
        e.close()


@pytest.mark.parametrize("title,code", [("NUL.txt", "OUT_OF_CASE"), ("aux.备注", "OUT_OF_CASE"),  # 设备名：闸门拒绝
                                        ("  ", "INVALID_ARGUMENT"), ("x" * 61, "INVALID_ARGUMENT")])
def test_save_draft_bad_titles(env, tid, title, code):
    fail(env.tool(tid, "case_save_draft", {"title": title, "content": "x"}), code)


# ---------- case_suggest_wiki ----------

def test_suggest_wiki(env, tid):
    a = env.tool_ok(tid, "case_suggest_wiki", {"field": "关键事实", "value": "借款8万元", "source": "〔借条 第2段〕"})
    b = env.tool_ok(tid, "case_suggest_wiki", {"field": "时间线", "value": "3月10日出借", "source": "〔推断〕",
                                                "reason": "借条落款"})
    assert int(b["suggestion_id"][1:]) == int(a["suggestion_id"][1:]) + 1
    data = json.loads((env.root / "工作区" / "wiki" / "待确认.json").read_text(encoding="utf-8"))
    assert not list(validator("files/wiki_pending.schema.json").iter_errors(data))
    s = [x for x in data["suggestions"] if x["id"] == b["suggestion_id"]][0]
    assert s["status"] == "pending" and s["task_id"] == tid and s["reason"] == "借条落款"


@pytest.mark.parametrize("args", [
    {"field": "关键事实", "value": "x", "source": "【借条 第2页】"},          # 出处格式错误
    {"field": "改原件", "value": "x", "source": "〔借条 第2段〕"},              # 字段不在枚举里
    {"field": "关键事实", "value": "", "source": "〔借条 第2段〕"},
])
def test_suggest_wiki_invalid(env, tid, args):
    fail(env.tool(tid, "case_suggest_wiki", args), "INVALID_ARGUMENT")


# ---------- case_save_edit_list ----------

def _edits(*items):
    return [dict(id=i, comment="理由", **e) for i, e in enumerate(items, 1)]


def test_edit_list_scope(env, tid):
    edits = _edits(
        {"para": 27, "action": "replace", "find": "九十日", "text": "三十日"},                  # 正常
        {"para": 12, "action": "delete", "find": "HW200"},                                   # 表格
        {"para": 39, "action": "replace", "find": "可在http", "text": "可在"},                 # 跨超链接
        {"para": 27, "action": "delete", "find": "不存在的原文"},                               # 找不到
        {"para": 27, "action": "insert_after", "find": "付款"},                               # 缺新文字
        {"para": 9999, "action": "delete", "find": "x"},                                     # 没有这个段号
    )
    v = env.tool_ok(tid, "case_save_edit_list", {"name": "采购合同", "edits": edits})
    reasons = {o["id"]: o["reason"] for o in v["out_of_scope"]}
    assert v["accepted"] == 1 and 1 not in reasons
    assert "表格" in reasons[2] and "超链接" in reasons[3] and "找不到" in reasons[4]
    assert "新文字" in reasons[5] and "段号" in reasons[6]
    saved = json.loads((env.root / v["path"]).read_text(encoding="utf-8"))
    assert saved["edits"] == edits
    assert not list(validator("tools/case_save_edit_list.schema.json", "#/$defs/args").iter_errors(saved))


def test_edit_list_multi_and_header(env, tid):
    units = texts.split_units(texts.read_text(str(env.root), names(env)["采购合同"]), "para")
    last = units[-1].no                                                  # 页眉页脚那一段
    u, common = next((u, c) for u in units[:-1] if not u.text.startswith("|")
                     for c in u.text if c.strip() and u.text.count(c) > 1)   # 某个正文段里出现多次的字
    v = env.tool_ok(tid, "case_save_edit_list", {"name": "采购合同", "edits": _edits(
        {"para": u.no, "action": "delete", "find": common}, {"para": last, "action": "delete", "find": "x"})})
    reasons = {o["id"]: o["reason"] for o in v["out_of_scope"]}
    assert "多次" in reasons[1] and "页眉页脚" in reasons[2] and v["accepted"] == 0


def test_edit_list_revised_and_errors(env, tid):
    v = env.tool_ok(tid, "case_save_edit_list", {"name": "采购合同-含未处理修订", "edits": _edits(
        {"para": 27, "action": "replace", "find": "日内", "text": "天内"})})
    assert v["accepted"] == 0 and "未处理的修订" in v["out_of_scope"][0]["reason"]
    fail(env.tool(tid, "case_save_edit_list", {"name": "起诉意见书", "edits": _edits(
        {"para": 1, "action": "delete", "find": "x"})}), "INVALID_ARGUMENT")
    fail(env.tool(tid, "case_save_edit_list", {"name": "不存在", "edits": _edits(
        {"para": 1, "action": "delete", "find": "x"})}), "MATERIAL_NOT_FOUND")
    fail(env.tool(tid, "case_save_edit_list", {"name": "采购合同", "edits": []}), "INVALID_ARGUMENT")


def test_line_material_every_line_numbered(tmp_path_factory):
    """T18 后续（T10）：按行定位的材料，读取时每行都带【第N行】，模型不用自己数（只标块首时常差一行，出处核对报 B 类）。"""
    src = tmp_path_factory.mktemp("lines-src") / "笔录.txt"
    src.write_text("".join(f"第{i}句内容\n" for i in range(1, 8)), encoding="utf-8")
    e = Env(tmp_path_factory.mktemp("t18lines"), {"笔录.txt": src})
    try:
        v = e.tool_ok(e.begin()["task_id"], "case_read_material", {"name": "笔录", "start": 3})
        assert v["text"].splitlines() == [x for i in range(3, 8) for x in (f"【第{i}行】", f"第{i}句内容")]
    finally:
        e.close()
