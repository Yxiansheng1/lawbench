"""T24 刑期计算：sentence-cases.json 全部用例、契约样例、/core/tool 接入、Spec 13.4 没写明处的取法。"""
from __future__ import annotations

import json
from datetime import date

import pytest

from lawbench.calc import sentence
from lawbench.calc.sentence import add_months, add_term, calc
from lawbench.config import REPO_ROOT
from lawbench.errors import ApiError

from t8_helpers import Env, fail, validator

FIX = REPO_ROOT / "tests" / "fixtures"
EX = REPO_ROOT / "contracts" / "examples"
CASES = json.loads((FIX / "sentence-cases.json").read_text(encoding="utf-8"))


def run(**a) -> dict:
    a.setdefault("custody", [])
    errs = list(validator("tools/case_calc_sentence.schema.json", "#/$defs/args").iter_errors(a))
    assert not errs, [e.message for e in errs]
    r = calc(a)
    errs = list(validator("tools/case_calc_sentence.schema.json", "#/$defs/result").iter_errors(r))
    assert not errs, [e.message for e in errs]
    assert all(b.endswith("（待律师核实）") for b in r["basis"] + [m["basis"] for m in r["milestones"]])
    return r


def seg(f, t, kind="逮捕"):
    return {"from": f, "to": t, "kind": kind}


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_sentence_cases(case):
    a = {k: case[k] for k in ("penalty", "years", "months", "execution_start", "custody") if k in case}
    r = run(**a)
    e = case["expect"]
    for k in ("start", "end", "offset_days", "custody_days"):
        if k in e:
            assert r[k] == e[k], (k, r[k], e[k])
    assert [(m["name"], m["date"]) for m in r["milestones"]] == [(m["name"], m["date"]) for m in e["milestones"]]
    for n in e["notes_contains"]:
        assert any(n in t for t in r["notes"]), (n, r["notes"])


def test_contract_example():
    args = json.loads((EX / "tool_calc_sentence.args.json").read_text(encoding="utf-8"))
    want = json.loads((EX / "tool_calc_sentence.result.json").read_text(encoding="utf-8"))
    assert calc(args) == want


# ---------- 接入 /core/tool ----------

@pytest.fixture(scope="module")
def env(tmp_path_factory):
    e = Env(tmp_path_factory.mktemp("t24"), {})
    yield e
    e.close()


def test_tool_via_core(env):
    tid = env.begin("sess-t24")["task_id"]
    args = json.loads((EX / "tool_calc_sentence.args.json").read_text(encoding="utf-8"))
    want = json.loads((EX / "tool_calc_sentence.result.json").read_text(encoding="utf-8"))
    assert env.tool_ok(tid, "case_calc_sentence", args) == want
    bad = json.loads((EX / "tool_calc_sentence.args_bad.json").read_text(encoding="utf-8"))
    fail(env.tool(tid, "case_calc_sentence", bad), "INVALID_ARGUMENT")
    fail(env.tool(tid, "case_calc_sentence", {"penalty": "有期徒刑", "years": 1,
                                              "custody": [seg("2026-03-02", "2026-03-01")]}), "INVALID_ARGUMENT")
    fail(env.tool(tid, "case_calc_sentence", {"penalty": "拘役", "years": 0, "months": 0, "custody": []}),
         "INVALID_ARGUMENT")


def test_date_out_of_range_is_bad_argument(env):
    """执行之日 9999-01-01 加 25 年：参数错误，不是 500（复核 P3-2）。"""
    tid = env.begin("sess-t24-range")["task_id"]
    fail(env.tool(tid, "case_calc_sentence", {"penalty": "有期徒刑", "years": 25, "months": 0,
                                              "execution_start": "9999-01-01", "custody": []}), "INVALID_ARGUMENT")
    with pytest.raises(ApiError) as ei:
        calc({"penalty": "有期徒刑", "years": 25, "months": 0, "execution_start": "9999-01-01", "custody": []})
    assert ei.value.code == "INVALID_ARGUMENT" and ei.value.reason == "date_out_of_range"


def test_overlapping_segments_count_as_continuous():
    """重叠的两段也算连续（并集是一整段）：起 = 羁押首日，notes 有"重叠"、没有"不连续"（复核 P3-1）。"""
    r = run(penalty="有期徒刑", years=1, months=0, execution_start=None,
            custody=[seg("2026-03-01", "2026-03-31", "刑事拘留"), seg("2026-03-20", "2026-04-30", "逮捕")])
    assert r["start"] == "2026-03-01" and r["custody_days"] == 61
    assert any("重叠" in n for n in r["notes"]) and not any("不连续" in n for n in r["notes"])


def test_errors_direct():
    with pytest.raises(ApiError) as ei:
        calc({"penalty": "有期徒刑", "years": 1, "custody": [seg("2026-03-02", "2026-03-01")]})
    assert ei.value.code == "INVALID_ARGUMENT"
    with pytest.raises(ApiError):
        calc({"penalty": "管制", "custody": []})


# ---------- 日期加法（Spec 13.4：先加年再加月，月末对齐；取法 d） ----------

@pytest.mark.parametrize("d,n,want", [
    ("2027-01-31", 1, "2027-02-28"), ("2028-01-31", 1, "2028-02-29"), ("2026-08-31", 6, "2027-02-28"),
    ("2027-02-28", 1, "2027-03-28"),            # 取法 d：原日期是月末，不追月末
    ("2028-02-29", 12, "2029-02-28"), ("2026-12-15", 1, "2027-01-15"), ("2026-11-30", 3, "2027-02-28"),
])
def test_add_months(d, n, want):
    assert add_months(date.fromisoformat(d), n).isoformat() == want


def test_add_years_then_months():
    """先加年再加月：2028-02-29 + 1 年 1 个月 = 2029-02-28 + 1 个月 = 2029-03-28（一次加 13 个月会得 03-29）。"""
    assert add_term(date(2028, 2, 29), 1, 1) == date(2029, 3, 28)
    assert add_months(date(2028, 2, 29), 13) == date(2029, 3, 29)


def test_by_day_half_rounds_up():
    """按天折半向上取整：1 个月（奇数个月）、2026-01-01 至 01-31 共 31 日，⌈31/2⌉ = 16，节点 01-16。"""
    r = run(penalty="拘役", years=0, months=1, execution_start="2026-01-01")
    assert r["milestones"][0]["date"] == "2026-01-16" and any("按天折半" in n for n in r["notes"])


def test_month_end_start_takes_no_month_end():
    r = run(penalty="有期徒刑", years=0, months=1, execution_start="2027-02-28")
    assert r["end"] == "2027-03-27"                                     # 2-28 + 1 个月 = 3-28，减 1 日


# ---------- 取法 f：没给执行之日、连续羁押、比例不是 1:1 ----------

def test_control_continuous_custody_adjusted():
    """管制 1 年、连续羁押 39 日（折抵 78 日）、没给执行之日：起 = 羁押首日，止 = 起 + 1 年 − 1 日 − (78 − 39)。"""
    r = run(penalty="管制", years=1, months=0, execution_start=None, custody=[seg("2026-04-01", "2026-05-09", "刑事拘留")])
    assert (r["start"], r["end"], r["offset_days"], r["custody_days"]) == ("2026-04-01", "2027-02-20", 78, 39)
    assert r["milestones"][0]["date"] == "2026-08-22"                  # 2026-10-01 − 1 日 = 09-30，再 − 39 日
    assert any("调整" in n for n in r["notes"])


def test_residence_continuous_custody_adjusted():
    """有期徒刑 1 年、只有指定居所监视居住 31 日（折抵 15 日）、没给执行之日：止日延后 31 − 15 = 16 日。"""
    r = run(penalty="有期徒刑", years=1, months=0, execution_start=None,
            custody=[seg("2026-03-01", "2026-03-31", "指定居所监视居住")])
    assert (r["start"], r["end"], r["offset_days"], r["custody_days"]) == ("2026-03-01", "2027-03-16", 15, 31)
    assert any("不足" in n for n in r["notes"]) and any("调整" in n for n in r["notes"])


def test_ratio_one_no_adjust_note():
    r = run(penalty="有期徒刑", years=1, custody=[seg("2026-03-01", "2026-03-31")])
    assert r["notes"] == [] and r["end"] == "2027-02-28"


# ---------- 其他边界 ----------

def test_no_custody_no_start():
    r = run(penalty="拘役", years=0, months=3)
    assert r["start"] is None and r["end"] is None and r["milestones"] == [] and r["offset_days"] == 0
    assert any("请提供判决执行之日" in n for n in r["notes"])


def test_overlap_and_other_kind_notes():
    r = run(penalty="有期徒刑", years=1, execution_start="2026-06-01",
            custody=[seg("2026-01-01", "2026-01-31", "刑事拘留"), seg("2026-01-20", "2026-02-10", "其他")])
    assert r["custody_days"] == 41 and r["offset_days"] == 41
    assert any("重叠" in n for n in r["notes"]) and any("其他" in n for n in r["notes"])


def test_residence_overlapping_detention_counts_as_detention():
    """同一天既在羁押段又在指定居所监视居住段：按羁押算一次（取法 c）。"""
    r = run(penalty="有期徒刑", years=1, execution_start="2026-06-01",
            custody=[seg("2026-03-01", "2026-03-10", "指定居所监视居住"), seg("2026-03-06", "2026-03-15", "逮捕")])
    assert r["custody_days"] == 15 and r["offset_days"] == 10 + 5 // 2      # 羁押 10 日、指居 5 日（3-1 至 3-5）
    assert any("不足" in n for n in r["notes"])


def test_offset_longer_than_term():
    r = run(penalty="拘役", years=0, months=1, execution_start="2026-06-01",
            custody=[seg("2026-01-01", "2026-03-31", "刑事拘留")])
    assert r["end"] < r["start"] and any("执行完毕" in n for n in r["notes"])


def test_life_imprisonment():
    r = run(penalty="无期徒刑", execution_start="2026-06-01", custody=[seg("2026-01-01", "2026-01-31")])
    assert (r["start"], r["end"], r["offset_days"], r["milestones"]) == (None, None, 0, [])
    assert sentence.NOTE_LIFE in r["notes"]


def test_rules_md_matches_code():
    """rules.md（交责任律师核对的规则表）与代码里的依据文字一致。"""
    md = (REPO_ROOT / "docs" / "plan" / "evidence" / "T24" / "rules.md").read_text(encoding="utf-8")
    for text in sentence.RULES.values():
        assert text in md, text
