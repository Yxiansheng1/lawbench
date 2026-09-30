"""/core 五个命令与 /api/task、/api/tasks（Spec 9.2、20.3；工单 T8 第 2、3、5、6 步）。"""
from __future__ import annotations

import json
import os
import re

import pytest

from lawbench.case import gate
from lawbench.llm import tokens

from t8_helpers import CASE_FILES, Env, fail, ok, validator


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    e = Env(tmp_path_factory.mktemp("t8core"), CASE_FILES)
    yield e
    e.close()


# ---------- /core/task/begin ----------

def test_begin_default_task(env):
    v = env.begin("sess-default")
    assert re.fullmatch(r"T-\d{14}-[0-9a-f]{4}", v["task_id"]) and v["case_id"] == env.case_id
    assert v["skill"] is None and v["budget"] == {"model_calls": 8, "tool_calls": 24, "minutes": 45}
    assert v["params"]["window"] == "64K" and v["params"]["thinking"] == "中"   # 设置里的默认参数
    task = env.read_json(v["task_id"], "task.json", "files/task.schema.json")
    assert task["state"] == "running" and task["session_id"] == "sess-default" and task["entry"] is None
    res = env.read_json(v["task_id"], "result.json", "files/result.schema.json")
    assert res["status"] == "running"
    assert env.read_json(v["task_id"], "reads.json", "files/reads.schema.json")["reads"] == []


@pytest.mark.parametrize("cwd", ["C:\\不存在的案件", "相对/路径", "", "..\\..\\"])
def test_begin_unknown_cwd(env, cwd):
    fail(env.client.post("/core/task/begin", json={"session_id": "s", "cwd": cwd}), "CASE_NOT_FOUND")


def test_begin_cwd_case_variant(env):
    if os.name != "nt":
        pytest.skip("Windows 不分大小写")
    assert env.begin("sess-case", str(env.root).upper())["case_id"] == env.case_id


def test_begin_uses_pending_task(env):
    req = {"case_id": env.case_id, "session_id": "sess-pend", "entry": "contract-review", "skill": "contract-review",
           "inputs": [], "params": {"thinking": "高", "window": "32K", "max_tokens": 4096}}
    tid = ok(env.client.post("/api/task", json=req), "api/task_create.schema.json")["task_id"]
    assert env.read_json(tid, "task.json", "files/task.schema.json")["state"] == "pending"
    v = env.begin("sess-pend")
    # 契约 1.2：按当前选择复制出新的执行中任务，选择本身不消耗，下一条消息仍按它跑
    assert v["task_id"] != tid and v["skill"] == "contract-review" and v["params"]["window"] == "32K"
    assert env.begin("sess-pend")["skill"] == "contract-review"
    assert env.read_json(tid, "task.json", "files/task.schema.json")["state"] == "pending"
    assert env.begin("sess-other")["skill"] is None    # 别的会话不受影响


def test_begin_bad_request(env):
    fail(env.client.post("/core/task/begin", json={"session_id": "", "cwd": str(env.root)}), "INVALID_ARGUMENT")
    fail(env.client.post("/core/task/begin", json={"session_id": "s", "cwd": str(env.root), "x": 1}),
         "INVALID_ARGUMENT")


# ---------- /api/task 的输入 ----------

def _draft(env, title="审查意见", content="正文"):
    tid = env.begin("sess-draft-src")["task_id"]
    return env.tool_ok(tid, "case_save_draft", {"title": title, "content": content})["path"]


def test_task_inputs_validated(env):
    good = _draft(env)
    base = {"case_id": env.case_id, "session_id": "sess-in", "entry": None, "skill": None,
            "params": {"thinking": "中", "window": "64K", "max_tokens": 4096}}
    tid = ok(env.client.post("/api/task", json=dict(base, inputs=[good])), "api/task_create.schema.json")["task_id"]
    ref = env.read_json(tid, "task.json", "files/task.schema.json")["inputs"][0]
    assert ref["index"] == 1 and ref["title"] == "审查意见" and ref["version"] == 1 and len(ref["sha256"]) == 64
    for bad in ["证据/借条.docx", "工作区/材料/index.json", "工作区/任务/../../证据/借条.docx", "成果/不存在-v1.md"]:
        fail(env.client.post("/api/task", json=dict(base, inputs=[bad])), "INVALID_ARGUMENT")
    fail(env.client.post("/api/task", json=dict(base, case_id="00000000-0000-4000-8000-000000000000", inputs=[])),
         "CASE_NOT_FOUND")


# ---------- /core/context ----------

def test_context_without_wiki(env):
    tid = env.begin("sess-ctx")["task_id"]
    v = ok(env.client.post("/core/context", json={"task_id": tid}), "core/context.schema.json")
    assert "还没有生成 wiki" in v["l0"]["text"] and "借条（已解析）" in v["l0"]["text"]
    assert "加密（无法处理）" in v["l0"]["text"] and v["l0"]["chars"] == len(v["l0"]["text"]) <= 6000
    assert v["l1"] == {"text": "", "tokens": 0, "truncated": False, "toc": []}


def test_context_with_wiki_card(env):
    idx = json.loads((env.root / "工作区" / "材料" / "index.json").read_text(encoding="utf-8"))
    first = idx["materials"][0]
    card = {"v": 1, "case_id": env.case_id, "case_type": "civil",
            "stance": {"text": "代理出借人李某乙", "set_at": "2026-09-29T10:00:00+08:00"},
            "parties": [{"id": "F0001", "text": "李某乙，出借人", "citations": ["〔借条 第2段〕"], "status": "lawyer_confirmed"}],
            "issues": [{"id": "F0002", "text": "2万元是本金还是利息", "citations": [], "status": "unconfirmed"}],
            "key_facts": [], "generated_by": None, "generated_at": "2026-09-29T10:00:00+08:00",
            "materials_at_generation": [{"material_id": first["material_id"], "sha256": first["sha256"]}]}
    assert not list(validator("files/case_card.schema.json").iter_errors(card))
    (env.root / "工作区" / "wiki").mkdir(exist_ok=True)
    (env.root / "工作区" / "wiki" / "case.json").write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    try:
        tid = env.begin("sess-card")["task_id"]
        l0 = ok(env.client.post("/core/context", json={"task_id": tid}), "core/context.schema.json")["l0"]["text"]
        assert "本方立场：代理出借人李某乙" in l0 and "[✔律师确认] 李某乙，出借人〔借条 第2段〕" in l0
        assert "[⚠未确认] 2万元是本金还是利息" in l0
        others = [m["name"] for m in idx["materials"][1:]]
        assert f"{others[0]}（" in l0 and "wiki 生成后新增或修改" in l0     # 生成后才有的材料要标出
        line = next(x for x in l0.splitlines() if x.startswith(f"- {first['name']}（"))
        assert "wiki 生成后新增或修改" not in line          # 生成时就有、没变过的材料不标
    finally:
        (env.root / "工作区" / "wiki" / "case.json").unlink()


def test_context_l0_capped(env):
    idx = json.loads((env.root / "工作区" / "材料" / "index.json").read_text(encoding="utf-8"))
    card = {"v": 1, "case_id": env.case_id, "case_type": "civil", "stance": None,
            "parties": [{"id": f"F{i:04d}", "text": "很长的事实" * 40, "citations": [], "status": "excerpt"}
                        for i in range(1, 60)],
            "issues": [], "key_facts": [], "generated_by": None, "generated_at": None,
            "materials_at_generation": [{"material_id": m["material_id"], "sha256": m["sha256"]} for m in idx["materials"]]}
    (env.root / "工作区" / "wiki").mkdir(exist_ok=True)
    (env.root / "工作区" / "wiki" / "case.json").write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    try:
        tid = env.begin("sess-cap")["task_id"]
        l0 = ok(env.client.post("/core/context", json={"task_id": tid}), "core/context.schema.json")["l0"]
        assert l0["chars"] <= 6000 and "已截断" in l0["text"]
    finally:
        (env.root / "工作区" / "wiki" / "case.json").unlink()


def test_context_l1_window_and_toc(env):
    small = _draft(env, "小输入", "短短一段。")
    big = _draft(env, "大输入", "很长的前序成果内容。" * 5000)        # 真计数、近似计数下都超过 32K 窗口的 40%，不超过 128K 的 40%
    after = _draft(env, "排在后面", "也很短。")
    req = {"case_id": env.case_id, "session_id": "sess-l1", "entry": None, "skill": None, "inputs": [small, big, after],
           "params": {"thinking": "中", "window": "32K", "max_tokens": 4096}}
    ok(env.client.post("/api/task", json=req), "api/task_create.schema.json")
    tid = env.begin("sess-l1")["task_id"]
    l1 = ok(env.client.post("/core/context", json={"task_id": tid}), "core/context.schema.json")["l1"]
    assert l1["truncated"] is True and "短短一段" in l1["text"]
    assert [t["index"] for t in l1["toc"]] == [2, 3]              # 放不下的和其后的只列目录
    assert l1["tokens"] <= tokens.l1_budget("32K")
    assert "case_read_input" in l1["text"]
    # 64K 窗口放得下
    req.update(session_id="sess-l1b", params={"thinking": "中", "window": "128K", "max_tokens": 4096})
    ok(env.client.post("/api/task", json=req), "api/task_create.schema.json")
    tid2 = env.begin("sess-l1b")["task_id"]
    assert ok(env.client.post("/core/context", json={"task_id": tid2}), "core/context.schema.json")["l1"]["toc"] == []


def test_context_input_changed(env):
    path = _draft(env, "会被改", "原文")
    req = {"case_id": env.case_id, "session_id": "sess-chg", "entry": None, "skill": None, "inputs": [path],
           "params": {"thinking": "中", "window": "64K", "max_tokens": 4096}}
    ok(env.client.post("/api/task", json=req), "api/task_create.schema.json")
    tid = env.begin("sess-chg")["task_id"]
    (env.root / path).write_text("被改过了", encoding="utf-8")
    fail(env.client.post("/core/context", json={"task_id": tid}), "INPUT_CHANGED")
    fail(env.tool(tid, "case_read_input", {"index": 1}), "INPUT_CHANGED")


def test_context_unknown_task(env):
    fail(env.client.post("/core/context", json={"task_id": "T-20260101000000-abcd"}), "TASK_NOT_FOUND")
    fail(env.client.post("/core/context", json={"task_id": "../x"}), "INVALID_ARGUMENT")


# ---------- /core/progress、/core/task/end ----------

def test_progress_and_end_without_draft(env):
    tid = env.begin("sess-end")["task_id"]
    ok(env.client.post("/core/progress", json={"task_id": tid, "text": "写到一半的内容", "model_calls": 2,
                                               "tool_calls": 3}), "core/progress.schema.json")
    assert (env.task_dir(tid) / "草稿" / "进行中.md").read_text(encoding="utf-8") == "写到一半的内容"
    assert env.read_json(tid, "result.json", "files/result.schema.json")["usage"]["model_calls"] == 2
    v = ok(env.client.post("/core/task/end", json={"task_id": tid, "reason": "aborted", "model_calls": 3,
                                                   "tool_calls": 4, "elapsed_s": 60}), "core/task_end.schema.json")
    assert v == {"status": "cancelled"}
    drafts = [p.name for p in (env.task_dir(tid) / "草稿").iterdir()]
    assert "进行中.md" not in drafts and any(re.fullmatch(r"未完成-\d{14}\.md", n) for n in drafts)
    res = env.read_json(tid, "result.json", "files/result.schema.json")
    assert res["status"] == "cancelled" and res["finished_at"] and res["usage"]["elapsed_s"] == 60
    assert res["coverage"] is not None
    assert env.read_json(tid, "task.json", "files/task.schema.json")["state"] == "finished"
    fail(env.tool(tid, "case_list_materials", {}), "TASK_NOT_FOUND")   # 结束后不能再调工具


@pytest.mark.parametrize("reason,status", [("completed", "completed"), ("max-tokens", "output_limit"),
                                           ("budget", "budget_stopped"), ("error", "failed"),
                                           ("interrupted", "interrupted"), ("blocked", "failed")])
def test_end_status_mapping(env, reason, status):
    tid = env.begin(f"sess-map-{reason}")["task_id"]
    env.tool_ok(tid, "case_save_draft", {"title": "结论", "content": "有正式草稿"})
    v = ok(env.client.post("/core/task/end", json={"task_id": tid, "reason": reason, "model_calls": 1,
                                                   "tool_calls": 1, "elapsed_s": 1}), "core/task_end.schema.json")
    assert v["status"] == status
    assert not any(p.name.startswith("未完成") for p in (env.task_dir(tid) / "草稿").iterdir())  # 有正式草稿就不改名


def test_reopen_marks_running_abnormal(env):
    tid = env.begin("sess-crash")["task_id"]
    env.client.app.state.lb.tasks._begun.pop(tid)   # 当成上一个进程留下的（T8 返修 P1-2：本进程的不标）
    ok(env.client.post("/api/case/open", json={"path": str(env.root)}), "api/case_open.schema.json")
    assert env.read_json(tid, "task.json", "files/task.schema.json")["state"] == "abnormal"
    assert env.read_json(tid, "result.json", "files/result.schema.json")["status"] == "abnormal"


def test_tasks_list(env):
    tid = env.begin("sess-list")["task_id"]
    env.tool_ok(tid, "case_save_draft", {"title": "列表用", "content": "x"})
    v = ok(env.client.get("/api/tasks", params={"case_id": env.case_id}), "api/tasks_list.schema.json")
    mine = [t for t in v["tasks"] if t["task_id"] == tid][0]
    assert mine["status"] == "running" and mine["drafts"][0]["title"] == "列表用" and mine["citation_passed"] is True


def test_core_requires_token(env):
    r = env.client.post("/core/task/begin", json={"session_id": "s", "cwd": str(env.root)},
                        headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_task_dir_is_gate_protected(env):
    with pytest.raises(Exception):
        gate.resolve_read(str(env.root), "工作区/任务")
