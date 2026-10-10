"""契约 1.4：案件 wiki 的核对状态（GET / POST /api/wiki/review），记在 工作区/wiki/case.json 的 review。"""
from __future__ import annotations

import json

import pytest

from t8_helpers import FIXTURES, Env, fail, ok

SCHEMA = "api/wiki_review.schema.json"


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path, {"说明.txt": FIXTURES / "civil-01" / "情况说明.txt", "摘要.md": FIXTURES / "civil-01" / "案情摘要.md"})
    yield e
    e.close()


def card(env, generated_at="2026-10-10T09:00:00+08:00"):
    idx = env.client.app.state.lb.materials.index(env.case_id)
    data = {"v": 1, "case_id": env.case_id, "case_type": "civil", "stance": None, "parties": [], "issues": [],
            "key_facts": [], "generated_by": None, "generated_at": generated_at,
            "materials_at_generation": [{"material_id": m["material_id"], "sha256": m["sha256"]} for m in idx["materials"]]}
    p = env.root / "工作区" / "wiki" / "case.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def get(env):
    return ok(env.client.get("/api/wiki/review", params={"case_id": env.case_id}), SCHEMA)


def mark(env):
    return env.client.post("/api/wiki/review", json={"case_id": env.case_id})


def test_no_wiki(env):
    assert get(env) == {"exists": False, "reviewed": False, "reviewed_at": None, "changes": None}
    fail(mark(env), "INVALID_ARGUMENT")


def test_mark_then_material_change_resets(env):
    p = card(env)
    assert get(env) == {"exists": True, "reviewed": False, "reviewed_at": None,
                        "changes": {"added": 0, "changed": 0, "removed": 0}}
    v = ok(mark(env), SCHEMA)
    assert v["reviewed"] is True and v["reviewed_at"]
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert len(saved["review"]["signature"]) == 64 and saved["parties"] == []      # 只加 review，别的不动
    assert get(env)["reviewed"] is True                                             # 记在案件里：重读仍是已核对
    f = env.root / "说明.txt"                                                        # 材料内容变了：回到未核对
    f.write_text(f.read_text(encoding="utf-8") + "补一行\n", encoding="utf-8")
    ok(env.client.post("/api/materials/scan", json={"case_id": env.case_id}), "api/materials_scan.schema.json")
    v = get(env)
    assert v["reviewed"] is False and v["reviewed_at"] is None and v["changes"]["changed"] == 1


def test_regenerate_resets(env):
    card(env)
    ok(mark(env), SCHEMA)
    old = json.loads((env.root / "工作区" / "wiki" / "case.json").read_text(encoding="utf-8"))["review"]
    p = card(env, generated_at="2026-10-10T10:00:00+08:00")                         # 重新生成：新的生成时间，review 没了
    assert get(env)["reviewed"] is False
    data = json.loads(p.read_text(encoding="utf-8"))
    data["review"] = old                                                            # 就算旧指纹还留着也不算
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert get(env)["reviewed"] is False


def test_broken_card(env):
    p = card(env)
    p.write_text("{", encoding="utf-8")
    fail(env.client.get("/api/wiki/review", params={"case_id": env.case_id}), "CASE_CARD_INVALID")
