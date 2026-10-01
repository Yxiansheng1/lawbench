"""T3 小项（执行令 20261001-1246）：带 pattern / format 的字符串字段拒绝换行和控制字符。

Python 正则的 $ 会放过结尾的换行（re.search("^[0-9]{4}-(0[1-9]|1[0-2])$", "2026-09\\n") 能匹配），
period:"2026-09\\n" 过契约后建目录 500、batch:"ab\\n" 一路送到引擎。草稿正文这类多行自由文本字段没有 pattern，照常收。
"""
from __future__ import annotations

import pytest

from lawbench import contracts

from t8_helpers import Env, fail, ok

BAD = ["\n", "\r", "\r\n", "\t", "\x00", "\x1b", "\x7f", "\x85"]


@pytest.mark.parametrize("tail", BAD, ids=[repr(x) for x in BAD])
def test_t25_invoice_period_and_batch(tail):
    """T25 的接口（invoice_run）：period、发票号码带结尾换行、控制字符时不过契约。"""
    req = "api/invoice_run.schema.json"
    assert not contracts.errors(req, "#/$defs/request", {"action": "history", "period": "2026-09"})
    assert contracts.errors(req, "#/$defs/request", {"action": "history", "period": "2026-09" + tail})
    assert contracts.errors(req, "#/$defs/request", {"action": "history", "period": tail + "2026-09"})


def test_date_fields_too():
    """日期字段：带 pattern 的（发票的 start/end）由本条拒绝；format: date 的（刑期的羁押起止）由日期校验拒绝。"""
    args = "tools/case_calc_sentence.schema.json"
    custody = [{"from": "2026-03-01", "to": "2026-03-02", "kind": "逮捕"}]
    assert not contracts.errors(args, "#/$defs/args", {"penalty": "拘役", "custody": custody})
    for bad in ("2026-03-01\n", "2026-03-01\r", "\t2026-03-01"):
        assert contracts.errors(args, "#/$defs/args", {"penalty": "拘役", "custody": [dict(custody[0], **{"from": bad})]})
    req = "api/invoice_run.schema.json"
    good = {"action": "plan", "period": "2026-09", "channel": "eml", "history": "exclude", "history_numbers": [],
            "start": "2026-09-01", "end": "2026-09-30"}
    assert not contracts.errors(req, "#/$defs/request", good)
    assert contracts.errors(req, "#/$defs/request", dict(good, start="2026-09-01\n"))
    assert contracts.errors(req, "#/$defs/request", dict(good, history_numbers=["123456789012345678\n"]))


@pytest.fixture
def env(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("借款80,000元\n", encoding="utf-8")
    e = Env(tmp_path / "case", {"a.txt": src / "a.txt"})
    yield e
    e.close()


@pytest.mark.parametrize("tail", ["\n", "\r", "\x00"], ids=["LF", "CR", "NUL"])
def test_t3_case_id_with_newline_rejected(env, tail):
    """T3 的接口：案件编号带结尾换行，按参数错误拒绝，不当成别的案件去找。"""
    fail(env.client.post("/api/materials/scan", json={"case_id": env.case_id + tail}), "INVALID_ARGUMENT")
    ok(env.client.post("/api/materials/scan", json={"case_id": env.case_id}), "api/materials_scan.schema.json")


def test_t8_draft_title_with_newline_rejected_content_multiline_ok(env):
    """T8 的接口：草稿标题带换行按参数错误拒绝（不建出带换行的文件名）；正文多行照常收。"""
    tid = env.begin("sess-nl")["task_id"]
    for title in ("报告\n", "报\t告", "报\x01告", "报\x85告"):                # 标题的 pattern 收任意字符：中间夹控制字符也拒
        fail(env.tool(tid, "case_save_draft", {"title": title, "content": "x"}), "INVALID_ARGUMENT")
    assert not (env.task_dir(tid) / "草稿").exists() or not list((env.task_dir(tid) / "草稿").iterdir())
    v = env.tool_ok(tid, "case_save_draft", {"title": "报告", "content": "第一行\n第二行\r\n\t第三行\n"})
    assert v["version"] == 1


# ---------- 第二轮复核 P3-a、P3-b（注记 20261001-1644） ----------

def test_ref_into_whole_documents_keeps_check():
    """沿 $ref 进到写了 "$schema" 的整份文档时照样拦（P3-a）：文件级 schema、capsules 请求。"""
    import json
    from lawbench.config import REPO_ROOT
    ex = json.loads((REPO_ROOT / "contracts" / "examples" / "file_material_index.json").read_text(encoding="utf-8"))
    assert not contracts.errors("files/material_index.schema.json", "", ex)
    ex["materials"][0]["rel_path"] += "\n"
    assert contracts.errors("files/material_index.schema.json", "", ex)
    caps = json.loads((REPO_ROOT / "contracts" / "examples" / "skill_capsules.json").read_text(encoding="utf-8"))
    assert not contracts.errors("api/capsules.schema.json", "#/$defs/request", caps)
    caps["groups"][0]["items"][0]["id"] += "\n"
    assert contracts.errors("api/capsules.schema.json", "#/$defs/request", caps)


@pytest.mark.parametrize("ch", ["\x7f", "\x85", "\x9f"], ids=["DEL", "NEL", "x9f"])
def test_rel_path_allows_del_and_c1(ch):
    """rel_path 只拦 0x00–0x1f，放行 Windows 文件名允许的 DEL 与 C1（P3-b，主编排定）；别的字段照旧全拦。"""
    assert not contracts.errors("common.schema.json", "#/$defs/rel_path", f"证据/借{ch}条.txt")
    assert contracts.errors("common.schema.json", "#/$defs/rel_path", "证据/借条.txt\n")
    assert contracts.errors("common.schema.json", "#/$defs/rel_path", "证据/借\x01条.txt")
    assert contracts.errors("tools/case_save_draft.schema.json", "#/$defs/args", {"title": f"报{ch}告", "content": "x"})


@pytest.mark.parametrize("validate", [True, False], ids=["开发测试-校验返回", "生产-不校验返回"])
def test_c1_file_name_listed_and_importable(make_client, cases_dir, tmp_path, validate):
    """原件区有"借\\x85条.txt"：扫描、列表 200（开发测试模式校验返回、生产模式不校验，两种都过）；
    导入到名字含 \\x85 的文件夹也能导入（P3-b）。"""
    client = make_client(validate_responses=validate)
    root = cases_dir / "C1文件名"
    root.mkdir()
    (root / "借\x85条.txt").write_text("借款80,000元\n", encoding="utf-8")
    cid = ok(client.post("/api/case/open", json={"path": str(root)}), "api/case_open.schema.json")["case_id"]
    ok(client.post("/api/materials/scan", json={"case_id": cid}), "api/materials_scan.schema.json")
    r = client.get("/api/materials", params={"case_id": cid})
    assert r.status_code == 200
    v = ok(r, "api/materials_list.schema.json")
    assert any(m["rel_path"] == "借\x85条.txt" for m in v["materials"])
    src = tmp_path / "外部"
    src.mkdir()
    (src / "收据.txt").write_text("收到\n", encoding="utf-8")
    r = client.post("/api/materials/import", json={"case_id": cid, "paths": [str(src / "收据.txt")],
                                                  "target": "收\x85件", "unzip": False})
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    assert (root / "收\x85件" / "收据.txt").is_file()
