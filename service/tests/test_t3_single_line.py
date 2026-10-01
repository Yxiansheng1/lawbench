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
