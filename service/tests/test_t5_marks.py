"""材料原文里以【开头的行不是位置标记（注记 20261001-1221，T10 大卷宗对照时发现）。"""
from __future__ import annotations

import pytest

from lawbench.case.texts import split_units

from t8_helpers import Env, ok

CHAT = ("微信聊天记录导出（虚构）\n"
        "【2025-03-10 21:14】周立新：陈姐，今天聊得很愉快，项目的事你考虑一下。\n"
        "【2025-03-11 09:05】陈美华：那我先投10万试试。\n"
        "【系统消息】你撤回了一条消息\n")


@pytest.fixture
def env(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "微信导出.txt").write_text(CHAT, encoding="utf-8")
    e = Env(tmp_path / "case", {"微信导出.txt": src / "微信导出.txt"})
    yield e
    e.close()


def test_read_material_keeps_bracket_lines(env):
    tid = env.begin("sess-m1")["task_id"]
    v = env.tool_ok(tid, "case_read_material", {"name": "微信导出", "start": 1})
    for line in CHAT.splitlines():
        assert line in v["text"], line
    m = env.client.app.state.lb.materials.index(env.case_id)["materials"][0]
    assert m["unit"] == "line" and m["unit_count"] == 4


def test_search_finds_bracket_lines(env):
    v = ok(env.client.get("/api/search", params={"case_id": env.case_id, "q": "那我先投10万试试"}),
           "api/search.schema.json")
    assert [h["citation"] for h in v["hits"]] == ["〔微信导出 第3行〕"]


def test_citation_check_on_bracket_lines(env):
    tid = env.begin("sess-m2")["task_id"]
    content = "陈美华称“那我先投10万试试。”〔微信导出 第3行〕\n\n周立新称“今天聊得很愉快，项目的事你考虑一下”〔微信导出 第2行〕\n"
    v = env.tool_ok(tid, "case_save_draft", {"title": "微信", "content": content})
    assert v["citation_check"]["passed"] and v["citation_check"]["problems"] == [], v["citation_check"]


@pytest.mark.parametrize("unit,text,want", [
    ("page", "【第1页】\n甲\n【第2段】\n【第3页】 后面有字\n【2025-01-01】乙\n【第2页】\n丙", ["甲\n【第2段】\n【第3页】 后面有字\n【2025-01-01】乙", "丙"]),
    ("para", "【第1段】\n【第1页】\n【第2段】\n乙", ["【第1页】", "乙"]),
    ("line", "【第1行】\n【表:流水】\n【第9页】\nx", ["【表:流水】", "【第9页】", "x"]),
])
def test_only_own_marks_split(unit, text, want):
    assert [u.text for u in split_units(text, unit)] == want


def test_cell_marks_only_sheet_labels():
    text = "【表:流水】\n| 行 | A |\n|---|---|\n| 1 | x |\n【第2页】\n| 2 | y |\n【表:汇总】\n| 行 | A |\n|---|---|\n| 1 | z |"
    got = [(u.sheet, u.row, u.text) for u in split_units(text, "cell")]
    assert got == [("流水", 1, "| 1 | x |"), ("流水", 2, "| 2 | y |"), ("汇总", 1, "| 1 | z |")]


def test_unknown_unit_is_empty():
    assert split_units("【第1页】\n甲", "slide") == []
