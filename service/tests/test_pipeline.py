"""T16 流水线与案件 wiki：用假 6000D（httpx.MockTransport，按系统提示认步骤、回流式内容）。"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import tempfile
import threading

import httpx
import pytest
from starlette.testclient import TestClient

from lawbench import contracts, logs
from lawbench.app import create_app
from lawbench.case import gate
from lawbench.config import REPO_ROOT, Config
from lawbench.pipeline import budget_calls, llm as llm_mod
from lawbench.pipeline.runner import Runner
from lawbench.pipeline.steps import wiki

from t8_helpers import fail, ok

TOKEN = "p" * 40
KEY = "test-key-not-real"
PARAMS = {"thinking": "高", "window": "64K", "max_tokens": 4096}

STEP_MARKS = [("修改", "没有通过出处检查"), ("案件卡片", "只输出一个 JSON 对象"), ("材料摘要", "为它写摘要"),
              ("当事人", "写\"当事人\"一文"), ("时间线", "写\"时间线\"一文"), ("争议焦点", "写\"争议焦点\"一文"),
              ("概览", "写\"概览\"一文")]


def sse(text: str, finish: str = "stop") -> bytes:
    out = []
    for i in range(0, len(text), 50):
        out.append("data: " + json.dumps({"choices": [{"delta": {"content": text[i:i + 50]}}]}, ensure_ascii=False))
    out.append("data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": finish}],
                                      "usage": {"prompt_tokens": 100, "completion_tokens": 20}}))
    out.append("data: [DONE]")
    return ("\n\n".join(out) + "\n\n").encode("utf-8")


class Fake6000D:
    """按步骤回内容。摘要：每行原文一条〔第N行〕；四篇：照抄摘要里的前几条；卡片：一条当事人。"""

    def __init__(self):
        self.requests: list[dict] = []
        self.wrong_first_summary = False      # 第一份摘要故意标错行号，看修改轮
        self.status = 200
        self.block = None                     # threading.Event：摘要调用卡住，等测试放行
        self._lock = threading.Lock()

    def step_of(self, system: str) -> str:
        return next(name for name, mark in STEP_MARKS if mark in system)

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen38-27b"}]})
        body = json.loads(request.content)
        system, user = body["messages"][0]["content"], body["messages"][1]["content"]
        step = self.step_of(system)
        with self._lock:
            self.requests.append({"step": step, "body": body, "headers": dict(request.headers), "user": user})
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "x"})
        if step == "材料摘要" and self.block is not None:
            self.block.wait(10)
        return httpx.Response(200, headers={"content-type": "text/event-stream", "x-queue-wait-ms": "7"},
                              content=sse(self.answer(step, user)))

    def answer(self, step: str, user: str) -> str:
        if step == "材料摘要":
            lines = [f"- 【书证】{t}〔第{n}行〕" for n, t in re.findall(r"【第(\d+)行】(.+)", user)]
            if self.wrong_first_summary and lines:
                self.wrong_first_summary = False
                k, (n, t) = next((k, x) for k, x in enumerate(re.findall(r"【第(\d+)行】(.+)", user))
                                 if re.search(r"\d", x[1]))
                lines[k] = f"- 【书证】{t}〔第{int(n) + 1}行〕"
            return "\n".join(lines)
        if step == "修改":
            out = []
            for n, line in re.findall(r"^(\d+)\. (.+)$", user, re.M):
                out.append(f"{n}. " + re.sub(r"〔[^〔〕]*〕", "〔推断〕", line))
            return "\n".join(out)
        if step == "案件卡片":
            cite = re.search(r"〔[^〔〕]+ 第\d+行〕", user)
            return json.dumps({"case_type": "civil", "parties": [{"text": "王某，借款人", "citations": [cite.group(0)],
                                                                 "status": "excerpt"}],
                               "issues": [{"text": "是否还款", "citations": ["〔不存在 第1页〕"], "status": "x"}],
                               "key_facts": []}, ensure_ascii=False)
        facts = [ln for ln in user.splitlines() if ln.startswith("- 【")]
        return "\n".join(facts[:6]) or "- 无"


CASE = {"借条.txt": "借条\n今借到王某人民币80,000元\n借款日期2025年3月12日\n借款人：李某\n",
        "说明.txt": "情况说明\n王某于2025年6月10日收到还款20,000元\n",
        "流水.txt": "| 交易日期 | 摘要 | 收入 | 支出 | 对方户名 |\n|---|---|---|---|---|\n"
                    "| 2025-03-12 | 转账 |  | 80,000.00 | 王某 |\n| 2025-03-13 | 消费 |  | 35.00 | 某超市 |\n"
                    "| 2025-03-14 | 取现 |  | 500.00 | ATM |\n"}


@pytest.fixture
def world(tmp_path):
    fake = Fake6000D()
    saved = gate._registry_onedrive_folders
    gate._registry_onedrive_folders = lambda: []
    appdata = pathlib.Path(tempfile.mkdtemp(prefix="lbad-"))
    app = create_app(Config(token=TOKEN, appdata=appdata), key_getter=lambda: KEY,
                     transport=httpx.MockTransport(fake.handler))
    client = TestClient(app, raise_server_exceptions=False)
    client.headers["Authorization"] = f"Bearer {TOKEN}"
    root = tmp_path / "案件"
    root.mkdir()
    for n, t in CASE.items():
        (root / n).write_text(t, encoding="utf-8")
    cid = ok(client.post("/api/case/open", json={"path": str(root)}), "api/case_open.schema.json")["case_id"]
    ok(client.post("/api/materials/scan", json={"case_id": cid}), "api/materials_scan.schema.json")
    w = {"client": client, "fake": fake, "root": root, "cid": cid, "appdata": appdata, "st": app.state.lb}
    yield w
    client.close()
    gate._registry_onedrive_folders = saved
    logs.close()
    shutil.rmtree(appdata, ignore_errors=True)


def start(w, step="wiki_build") -> str:
    return ok(w["client"].post("/api/pipeline/run", json={"case_id": w["cid"], "step": step, "use_prep": False,
                                                         "params": PARAMS}), "api/pipeline_run.schema.json")["task_id"]


def finish(w, tid) -> dict:
    w["st"].pipelines.wait(tid, 30)
    return ok(w["client"].get(f"/api/pipeline/{tid}"), "api/pipeline_status.schema.json")


def wiki_file(w, rel) -> str:
    return (w["root"] / "工作区" / "wiki" / rel).read_text(encoding="utf-8")


def index(w) -> dict:
    return {m["name"]: m for m in w["st"].materials.index(w["cid"])["materials"]}


def task_json(w, tid, name):
    return json.loads((w["root"] / "工作区" / "任务" / tid / name).read_text(encoding="utf-8"))


# ---------- 正常生成 ----------

def test_build(world):
    w = world
    tid = start(w)
    assert tid.startswith("P-")
    st = finish(w, tid)
    assert st["status"] == "completed" and st["current"] is None
    mats = index(w)
    page = wiki_file(w, f"材料/{mats['借条']['material_id']}.md")
    assert page.startswith("# 借条\n") and "〔借条 第2行〕" in page and "80,000" in page
    for s in ("当事人", "时间线", "争议焦点", "概览", "材料清单"):
        assert wiki_file(w, f"案件/{s}.md").startswith(f"# {s}\n")
    card = json.loads(wiki_file(w, "case.json"))
    assert not contracts.errors("files/case_card.schema.json", "", card)
    assert card["case_type"] == "civil" and card["generated_by"] == tid
    assert [f["id"] for f in card["parties"] + card["issues"]] == ["F0001", "F0002"]   # 编号由程序分配
    assert card["issues"][0]["citations"] == [] and card["issues"][0]["status"] == "unconfirmed"  # 不合格出处丢掉
    assert {x["material_id"] for x in card["materials_at_generation"]} == {m["material_id"] for m in mats.values()}
    assert "共 3 份材料，已读 3 份" in wiki_file(w, "案件/材料清单.md")
    assert wiki_file(w, "index.md").startswith("# 案件 wiki 目录") and tid in wiki_file(w, "log.md")
    task = task_json(w, tid, "task.json")
    assert task["kind"] == "pipeline" and task["state"] == "finished" and task["step"] == "wiki_build"
    assert task["budget"]["model_calls"] == budget_calls(2, 5)        # 两份非表格材料各 1 段、四篇 + 卡片
    res = task_json(w, tid, "result.json")
    assert not contracts.errors("files/result.schema.json", "", res)
    assert res["status"] == "completed" and res["citation_check"]["passed"] is True
    assert {d["title"] for d in res["drafts"]} == {"当事人", "时间线", "争议焦点", "概览", "案件卡片"}
    rec = task_json(w, tid, "运行记录.json")
    assert rec["模型调用次数"] == res["usage"]["model_calls"] == len(w["fake"].requests)


def test_request_shape(world):
    w = world
    finish(w, start(w))
    r = w["fake"].requests[0]
    b = r["body"]
    assert b["model"] == "qwen38-27b" and b["stream"] is True and b["max_tokens"] == 4096
    assert b["chat_template_kwargs"] == {"enable_thinking": True, "reasoning_effort": "xhigh"}   # "高"发 xhigh
    assert r["headers"]["authorization"] == f"Bearer {KEY}" and r["headers"]["x-session-id"].startswith("P-")
    assert b["messages"][0]["content"].startswith(wiki.REQUIRED_STEPS and "你在为律师整理一个案件的案件 wiki")


def test_table_material_summarized_by_program(world):
    w = world
    finish(w, start(w))
    assert not any("流水" in r["user"].split("\n", 1)[0] for r in w["fake"].requests if r["step"] == "材料摘要")
    page = wiki_file(w, f"材料/{index(w)['流水']['material_id']}.md")
    assert page.splitlines()[1].startswith("> 筛选条件：") and "已列出 2 行 / 共 3 行" in page
    assert "80,000.00" in page and "取现" in page and "某超市" not in page.split("其余交易")[0]
    assert "摘要为筛选结果，非全量" in wiki_file(w, "案件/材料清单.md")


# ---------- 核对与修改：只交问题句 ----------

def test_fix_round_sends_only_problem_sentences(world):
    w = world
    w["fake"].wrong_first_summary = True
    tid = start(w)
    assert finish(w, tid)["status"] == "completed"
    fixes = [r for r in w["fake"].requests if r["step"] == "修改"]
    assert len(fixes) == 1
    u = fixes[0]["user"]
    assert u.count("\n1. ") + u.startswith("【有问题的句子】\n1. ") >= 1 and "\n2. " not in u.split("【相关原文】")[0]
    assert "问题 B" in u and "【相关原文】" in u
    rec = task_json(w, tid, "运行记录.json")
    assert rec["修改记录"] and rec["修改记录"][0]["轮次"] == 1


def test_fix_parser_and_apply():
    bad = [(0, "- 【书证】甲〔借条 第3行〕", []), (2, "| a | b〔x 第1行〕 |", [])]
    text = "- 【书证】甲〔借条 第3行〕\n- 不动\n| a | b〔x 第1行〕 |"
    reply = "1. 【书证】甲〔借条 第2行〕\n2. | a | b〔推断〕 |\n3. 多出来的"
    assert Runner.apply_fixes(text, bad, reply) == "- 【书证】甲〔借条 第2行〕\n- 不动\n| a | b〔推断〕 |"


def test_expand_short_citations():
    assert wiki.expand_short("甲〔第3页〕乙〔第1页、第2页〕丙〔第1页至第3页〕丁〔推断〕戊〔借条 第2段〕", "笔录") == \
        "甲〔笔录 第3页〕乙〔笔录 第1页、笔录 第2页〕丙〔笔录 第1-3页〕丁〔推断〕戊〔借条 第2段〕"


# ---------- 律师修改块（对称用例：去掉保护即红） ----------

def test_lawyer_blocks_kept(world):
    w = world
    finish(w, start(w))
    p = w["root"] / "工作区" / "wiki" / "案件" / "时间线.md"
    old = p.read_text(encoding="utf-8").splitlines()
    anchor = old[2]
    block = "<!-- 律师修改 -->\n律师补充：已核对原件。\n<!-- /律师修改 -->"
    p.write_text("\n".join(old[:3] + [block] + old[3:]) + "\n\n锚点没了的那行\n<!-- 律师修改 -->\n孤块\n<!-- /律师修改 -->\n",
                 encoding="utf-8")
    finish(w, start(w))
    new = p.read_text(encoding="utf-8")
    lines = new.splitlines()
    i = lines.index(anchor)
    assert lines[i + 1:i + 4] == block.splitlines()                      # 原位置
    assert "> **Status: 待律师核对**" in new and new.rstrip().endswith("<!-- /律师修改 -->") and "孤块" in new


def test_lawyer_block_helpers():
    old = "# 标题\n\n第一行\n<!-- 律师修改 -->\nA\n<!-- /律师修改 -->\n第二行\n"
    blocks = wiki.take_lawyer_blocks(old)
    assert blocks == [("第一行", "<!-- 律师修改 -->\nA\n<!-- /律师修改 -->")]
    assert wiki.put_lawyer_blocks("# 标题\n\n第一行\n新内容", blocks) == \
        "# 标题\n\n第一行\n<!-- 律师修改 -->\nA\n<!-- /律师修改 -->\n新内容"
    assert wiki.put_lawyer_blocks("别的", blocks).endswith("> **Status: 待律师核对**\n\n<!-- 律师修改 -->\nA\n<!-- /律师修改 -->")


# ---------- 更新：只重跑变化材料（对称用例） ----------

def test_update_reruns_only_changed(world):
    w = world
    finish(w, start(w))
    n0 = len(w["fake"].requests)
    (w["root"] / "说明.txt").write_text("情况说明\n王某于2025年7月1日又收到还款10,000元\n", encoding="utf-8")
    ok(w["client"].post("/api/materials/scan", json={"case_id": w["cid"]}), "api/materials_scan.schema.json")
    tid = start(w, "wiki_update")
    assert finish(w, tid)["status"] == "completed"
    summaries = [r for r in w["fake"].requests[n0:] if r["step"] == "材料摘要"]
    assert [r["user"].split("\n", 1)[0] for r in summaries] == ["材料名：说明"]          # 借条没变，不重跑
    assert "2025年7月1日" in wiki_file(w, f"材料/{index(w)['说明']['material_id']}.md")
    assert "80,000" in wiki_file(w, f"材料/{index(w)['借条']['material_id']}.md")       # 沿用旧摘要页
    assert sum(r["step"] in wiki.SECTIONS for r in w["fake"].requests[n0:]) == 4           # 四篇照写


def test_build_reruns_everything(world):
    w = world
    finish(w, start(w))
    n0 = len(w["fake"].requests)
    finish(w, start(w, "wiki_build"))
    assert sum(r["step"] == "材料摘要" for r in w["fake"].requests[n0:]) == 2


def test_update_keeps_pages_of_deleted_originals(world):
    """原件删了、材料文本保留（Spec 4.1，状态 source_deleted）：摘要页留着，材料清单注明。"""
    w = world
    finish(w, start(w))
    gone = index(w)["说明"]["material_id"]
    (w["root"] / "说明.txt").unlink()
    ok(w["client"].post("/api/materials/scan", json={"case_id": w["cid"]}), "api/materials_scan.schema.json")
    assert index(w)["说明"]["status"] == "source_deleted"
    finish(w, start(w, "wiki_update"))
    assert (w["root"] / "工作区" / "wiki" / "材料" / f"{gone}.md").exists()
    assert "原件已删除" in wiki_file(w, "案件/材料清单.md")


# ---------- 预算、取消、错误 ----------

@pytest.mark.parametrize("calls,pages", [(1, 2), (2, 3)])
def test_budget_stop_saves_done_parts(world, monkeypatch, calls, pages):
    """上限 1 次：停在摘要中途，写完的那份摘要照样存下（另一份没写）；上限 2 次：两份摘要都存、停在四篇。"""
    w = world
    monkeypatch.setattr("lawbench.pipeline.budget_calls", lambda s, a: calls)
    tid = start(w)
    assert finish(w, tid)["status"] == "budget_stopped"
    assert len(w["fake"].requests) == calls
    res = task_json(w, tid, "result.json")
    assert res["status"] == "budget_stopped" and res["usage"]["model_calls"] == calls
    got = list((w["root"] / "工作区" / "wiki" / "材料").glob("*.md"))
    assert len(got) == pages                                                 # 写完的摘要 + 程序筛选的流水


def test_cancel(world):
    w = world
    w["fake"].block = threading.Event()
    tid = start(w)
    ok(w["client"].post(f"/api/pipeline/{tid}/cancel", json={}), "api/pipeline_cancel.schema.json")
    w["fake"].block.set()
    assert finish(w, tid)["status"] == "cancelled"
    assert task_json(w, tid, "result.json")["status"] == "cancelled"
    assert len(w["fake"].requests) <= 2                                      # 在途的两路之后不再发


def test_key_invalid_fails(world):
    w = world
    w["fake"].status = 401
    tid = start(w)
    assert finish(w, tid)["status"] == "failed"
    rec = task_json(w, tid, "运行记录.json")
    assert rec["错误"] == "KEY_INVALID"


def test_http_error_mapping():
    def resp(code, text=""):
        return httpx.Response(code, text=text, request=httpx.Request("POST", "http://x"))
    assert llm_mod._http_error(resp(403)).code == "KEY_INVALID"
    assert llm_mod._http_error(resp(503)).code == "SERVER_BUSY"
    assert llm_mod._http_error(resp(400, "maximum context length is 32768")).code == "CONTEXT_TOO_LONG"
    assert llm_mod._http_error(resp(500)).code == "INTERNAL"
    assert llm_mod.thinking_fields("关闭") == {"enable_thinking": False}
    assert llm_mod.thinking_fields("中") == {"enable_thinking": True, "reasoning_effort": "medium"}


def test_second_run_returns_running_task(world):
    w = world
    w["fake"].block = threading.Event()
    a = start(w)
    b = start(w)
    w["fake"].block.set()
    finish(w, a)
    assert a == b


# ---------- 日志、接口 ----------

def test_logs_only_metadata(world):
    w = world
    finish(w, start(w))
    logs.close()
    text = "".join(p.read_text(encoding="utf-8") for p in (w["appdata"] / "logs").glob("*"))
    logs.setup(w["appdata"])
    for s in ("借条", "80,000", "王某", "你在为律师整理", KEY):
        assert s not in text, s
    assert '"module": "pipeline"' in text


def test_status_after_restart_reads_result(world):
    w = world
    tid = start(w)
    finish(w, tid)
    w["st"].pipelines._live.clear()
    v = ok(w["client"].get(f"/api/pipeline/{tid}"), "api/pipeline_status.schema.json")
    assert v["status"] == "completed"
    fail(w["client"].get("/api/pipeline/P-20260101000000-abcd"), "TASK_NOT_FOUND")


def test_wiki_suggestions(world):
    w = world
    tid = ok(w["client"].post("/core/task/begin", json={"session_id": "s-t16", "cwd": str(w["root"])}),
             "core/task_begin.schema.json")["task_id"]
    for v in ("甲", "乙"):
        ok(w["client"].post("/core/tool", json={"task_id": tid, "tool": "case_suggest_wiki",
                                                "args": {"field": "当事人", "value": v, "source": "〔借条 第2行〕"}}),
           "core/tool.schema.json")
    v = ok(w["client"].get("/api/wiki/suggestions", params={"case_id": w["cid"]}), "api/wiki_suggestions.schema.json")
    assert [s["status"] for s in v["suggestions"]] == ["pending", "pending"]
    v = ok(w["client"].post("/api/wiki/suggestions/S0001", json={"case_id": w["cid"], "accept": True}),
           "api/wiki_suggestions.schema.json")
    assert [s["status"] for s in v["suggestions"]] == ["accepted", "pending"]
    v = ok(w["client"].post("/api/wiki/suggestions/S0002", json={"case_id": w["cid"], "accept": False}),
           "api/wiki_suggestions.schema.json")
    assert [s["status"] for s in v["suggestions"]] == ["accepted", "rejected"]
    fail(w["client"].post("/api/wiki/suggestions/S0002", json={"case_id": w["cid"], "accept": True}), "INVALID_ARGUMENT")
    fail(w["client"].post("/api/wiki/suggestions/S0009", json={"case_id": w["cid"], "accept": True}), "INVALID_ARGUMENT")
    assert "S0001" in wiki_file(w, "log.md")


def test_prompts_file_has_fixed_steps():
    from lawbench.pipeline.prompts import Prompts
    p = Prompts.load([REPO_ROOT / "skills"], "case-wiki-build", wiki.REQUIRED_STEPS)
    assert set(wiki.REQUIRED_STEPS) <= set(p.sections)
