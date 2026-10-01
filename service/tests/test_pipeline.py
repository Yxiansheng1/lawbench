"""T16 流水线与案件 wiki：用假 6000D（httpx.MockTransport，按系统提示认步骤、回流式内容）。"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import tempfile
import threading
import time

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
        self.prep_mode = "good"               # 假 395：good 字段都对；bad 字段多数对不上；down 返回 503
        self.extract: list[dict] = []
        self.card_cut = 0                     # 卡片这一步前几次回"被截断"（finish_reason=length）
        self.stubborn = False                 # 修改轮原样交回句子（大卷宗实测出现过）
        self.fix_wrong = False                # 修改轮每次都换一个错的行号（看修改轮上限）
        self.header_delay = 0.0               # 摘要调用迟迟不回响应头（6000D 排队），秒
        self.prep_delay = 0.0                 # 假 395 迟迟不回，秒
        self.card_len_valid = 0               # 卡片前几次回合法 JSON 但 finish_reason=length
        self.raise_exc = None                 # 摘要调用抛这个网络异常
        self.primary_down = False             # 所内地址探测不通
        self.prep_dup, self.prep_bad = 1, 0   # 假 395 mix 模式：真字段重复几遍、另加几个对不上的
        self.slow = 0.0                       # 每次调用耗时（看同时在途的请求数）
        self.on_summary = None                # 每次摘要调用时回调（注入时钟用）
        self.inflight = self.max_inflight = 0
        self.queue_ms = 7
        self._lock = threading.Lock()

    def step_of(self, system: str) -> str:
        return next(name for name, mark in STEP_MARKS if mark in system)

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            if self.primary_down and request.url.host == "192.168.8.77":
                return httpx.Response(503)
            return httpx.Response(200, json={"data": [{"id": "qwen38-27b"}]})
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/v1/extract":
            return self.prep(request)
        body = json.loads(request.content)
        system, user = body["messages"][0]["content"], body["messages"][1]["content"]
        step = self.step_of(system)
        with self._lock:
            self.requests.append({"step": step, "body": body, "headers": dict(request.headers), "user": user,
                                  "host": request.url.host})
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            return self._answer(step, user, request)
        finally:
            with self._lock:
                self.inflight -= 1

    def _answer(self, step: str, user: str, request: httpx.Request) -> httpx.Response:
        if self.slow:
            time.sleep(self.slow)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "x"})
        if step == "材料摘要":
            if self.on_summary is not None:
                self.on_summary()
            if self.raise_exc is not None:
                raise self.raise_exc("x", request=request)
            if self.header_delay:
                time.sleep(self.header_delay)
        if step == "材料摘要" and self.block is not None:
            self.block.wait(10)
        if step == "案件卡片" and self.card_len_valid > 0:
            self.card_len_valid -= 1
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=sse(self.answer(step, user), finish="length"))
        if step == "案件卡片" and self.card_cut > 0:
            self.card_cut -= 1
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=sse('{"case_type": "civil", "parties": [{"text": "王', finish="length"))
        return httpx.Response(200, headers={"content-type": "text/event-stream", "x-queue-wait-ms": str(self.queue_ms)},
                              content=sse(self.answer(step, user)))

    def prep(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        with self._lock:
            self.extract.append({"body": body, "headers": dict(request.headers)})
        if self.prep_delay:
            time.sleep(self.prep_delay)
        if self.prep_mode == "down":
            return httpx.Response(503, json={"error": {"code": "QUEUE_FULL", "message": "满"}})
        if body["task"] == "classify":
            return httpx.Response(200, json={"task": "classify", "result": {"category": "书证"}, "elapsed_ms": 5})
        out = []
        for n, t in re.findall(r"【第(\d+)行】(.+)", body["text"]):
            for v in re.findall(r"\d[\d,]*元|\d{4}年\d+月\d+日", t):
                f = {"field": "金额" if v.endswith("元") else "日期",
                     "value": v if self.prep_mode in ("good", "mix") else v.replace("0", "9"), "loc": f"第{n}行"}
                out += [f] * (self.prep_dup if self.prep_mode == "mix" else 1)
        if self.prep_mode == "mix" and out:
            out += [dict(out[0], value="对不上的值")] * self.prep_bad
        return httpx.Response(200, json={"task": "fields", "result": out, "elapsed_ms": 9})

    def answer(self, step: str, user: str) -> str:
        if step == "材料摘要":
            lines = [f"- 【书证】{t}〔第{n}行〕" for n, t in re.findall(r"【第(\d+)行】(.+)", user)]
            if self.wrong_first_summary and lines and user.startswith("材料名：借条"):   # 固定在借条上，不看并行谁先到
                self.wrong_first_summary = False
                k, (n, t) = next((k, x) for k, x in enumerate(re.findall(r"【第(\d+)行】(.+)", user))
                                 if re.search(r"\d", x[1]))
                lines[k] = f"- 【书证】{t}〔第{int(n) + 1}行〕"
            return "\n".join(lines)
        if step == "修改":
            out = []
            for n, line in re.findall(r"^(\d+)\. (.+)$", user, re.M):
                if self.fix_wrong:          # 每轮换一个仍然错的行号：内容有变化、问题还在
                    line = re.sub(r"第(\d+)行〕", lambda m: f"第{int(m.group(1)) + 1}行〕", line)
                out.append(f"{n}. " + (line if self.stubborn or self.fix_wrong
                                       else re.sub(r"〔[^〔〕]*〕", "〔推断〕", line)))
            return "\n".join(out)
        if step == "案件卡片":
            cite = re.search(r"〔[^〔〕]+ 第\d+行〕", user)
            return json.dumps({"case_type": "civil", "parties": [{"text": "王某，借款人", "citations": [cite.group(0)],
                                                                 "status": "excerpt"}],
                               "issues": [{"text": "是否还款", "citations": ["〔不存在 第1页〕"], "status": "x"}],
                               "key_facts": [{"text": "借款90,000元", "citations": ["〔借条 第2行〕"], "status": "excerpt"},
                                             {"text": "借款80,000元", "citations": ["〔借条 第2行〕"], "status": "excerpt"}]},
                              ensure_ascii=False)
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


def start(w, step="wiki_build", use_prep=False) -> str:
    return ok(w["client"].post("/api/pipeline/run", json={"case_id": w["cid"], "step": step, "use_prep": use_prep,
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
    # 卡片出处和条目文字一起核：金额写错的那条丢掉出处、改为未确认；写对的保留
    assert [(f["text"], f["citations"], f["status"]) for f in card["key_facts"]] == [
        ("借款90,000元", [], "unconfirmed"), ("借款80,000元", ["〔借条 第2行〕"], "excerpt")]
    assert "共 3 份材料，已读 3 份" in wiki_file(w, "案件/材料清单.md")
    assert wiki_file(w, "index.md").startswith("# 案件 wiki 目录") and tid in wiki_file(w, "log.md")
    task = task_json(w, tid, "task.json")
    assert task["kind"] == "pipeline" and task["state"] == "finished" and task["step"] == "wiki_build"
    assert task["budget"]["model_calls"] == 2 * 3 + 5 * 3 + 10 == 31     # 两份非表格材料各 1 段、四篇 + 卡片（P3-3：期望值不用同一函数算）
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
    # P3-5：表格行不到 60% 的材料仍交模型，实测版"流水只列 ①–⑤ 类行"的规则保留作兜底
    assert "① 户名、账号、查询期间" in p.system("材料摘要") and "通话详单只写机主" in p.system("材料摘要")


def test_ranges_and_failed_reason(world):
    assert wiki._ranges(["第1页", "第2页", "第3页", "第5页"]) == ["第1-3页", "第5页"]
    assert wiki._ranges(["流水!A3:F3"]) == ["流水!A3:F3"]
    w = world
    idx_path = w["root"] / "工作区" / "材料" / "index.json"
    data = json.loads(idx_path.read_text(encoding="utf-8"))
    m = next(x for x in data["materials"] if x["name"] == "说明")
    m.update(status="failed", error="文件已加密，无法打开，请提供未加密版本", unit_count=0)
    idx_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    finish(w, start(w))
    row = next(ln for ln in wiki_file(w, "案件/材料清单.md").splitlines() if ln.startswith("| 说明 |"))
    assert row.endswith("| — | **否** | 文件已加密，无法打开，请提供未加密版本 |")


# ---------- 395 的 9B（假 395；真机补测见 9b.txt） ----------

def test_prep_good_fields_go_to_summary(world):
    w = world
    tid = start(w, use_prep=True)
    assert finish(w, tid)["status"] == "completed"
    ex = w["fake"].extract
    assert {e["body"]["task"] for e in ex} == {"classify", "fields"}
    assert all(e["headers"]["authorization"] == f"Bearer {KEY}" for e in ex)
    assert not any("交易日期" in e["body"]["text"] for e in ex)                # 表格类材料不送 9B
    sums = {r["user"].split("\n", 1)[0]: r["user"] for r in w["fake"].requests if r["step"] == "材料摘要"}
    assert "- 金额：80,000元〔借条 第2行〕" in sums["材料名：借条"] and "395 分类：书证" in sums["材料名：借条"]
    rec = task_json(w, tid, "运行记录.json")
    assert rec["395"]["提示"] is None and rec["395"]["字段"] >= 3 and rec["395"]["核对不过"] == 0
    assert "395 抽取：已用" in wiki_file(w, "log.md")


@pytest.mark.parametrize("mode,note", [("bad", "高于 20%"), ("down", "395 不可用")])
def test_prep_skipped(world, mode, note):
    w = world
    w["fake"].prep_mode = mode
    tid = start(w, use_prep=True)
    assert finish(w, tid)["status"] == "completed"
    assert not any("395 抽取的参考字段" in r["user"] for r in w["fake"].requests)
    assert note in task_json(w, tid, "运行记录.json")["395"]["提示"] and note in wiki_file(w, "log.md")


def test_prep_not_used_unless_ticked(world):
    w = world
    tid = start(w)
    finish(w, tid)
    assert w["fake"].extract == [] and task_json(w, tid, "运行记录.json")["395"] is None


def test_table_summary_cites_page_ranges():
    from lawbench.case import texts
    text = "【第1页】\n| 交易日期 | 摘要 | 收入 | 支出 | 对方户名 |\n|---|---|---|---|---|\n| 2025-03-01 | 消费 |  | 5.00 | 甲超市 |\n\n" \
           "【第2页】\n| 交易日期 | 摘要 | 收入 | 支出 | 对方户名 |\n| 2025-03-02 | 消费 |  | 6.00 | 乙超市 |\n\n" \
           "【第3页】\n| 交易日期 | 摘要 | 收入 | 支出 | 对方户名 |\n| 2025-03-03 | 消费 |  | 7.00 | 丙超市 |\n"
    m = wiki.Mat({"name": "流水", "material_id": "M0009", "unit": "page"}, texts.split_units(text, "page"))
    lines, kept, total = wiki.table_summary(m, "", dict(wiki.DEFAULT_FILTER))
    assert (kept, total) == (0, 3) and lines[-1].endswith("〔流水 第1-3页〕")


# ---------- 案件卡片被截断（大卷宗实测发现：输出到上限、JSON 不完整时曾写出空卡片） ----------

def test_card_truncated_once_retried(world):
    w = world
    w["fake"].card_cut = 1
    tid = start(w)
    assert finish(w, tid)["status"] == "completed"
    cards = [r for r in w["fake"].requests if r["step"] == "案件卡片"]
    assert len(cards) == 2 and "上一次输出过长被截断" in cards[1]["user"]
    card = json.loads(wiki_file(w, "case.json"))
    assert card["parties"] and card["case_type"] == "civil"


def test_card_truncated_twice_fails_and_keeps_old_card(world):
    w = world
    finish(w, start(w))
    old = wiki_file(w, "case.json")
    w["fake"].card_cut = 2
    tid = start(w)
    assert finish(w, tid)["status"] == "failed"
    assert task_json(w, tid, "运行记录.json")["错误"] == "OUTPUT_TRUNCATED"
    assert wiki_file(w, "case.json") == old                                  # 不写空卡片、不覆盖原来的


def test_prep_skips_table_materials_itself():
    """Prep.run 自己也不把表格类材料送 9B（调用方也筛过一道，这里单独测这一层）。"""
    from lawbench.case import texts
    from lawbench.pipeline.prep import Prep

    class Net:
        calls = 0

        def request(self, *a, **k):
            Net.calls += 1
            raise AssertionError("不该发请求")

    m = wiki.Mat({"name": "流水", "material_id": "M0009", "unit": "line"},
                 texts.split_units("【第1行】\n| 交易日期 | 摘要 |\n| 2025-01-01 | 转账 |", "line"), table=True)
    assert Prep(Net(), lambda: KEY).run([m]) == ({}, {}) and Net.calls == 0


# ---------- 修改轮用完仍有问题：程序兜底 ----------

def test_settle_b_moves_citation_to_actual_place(world):
    """模型修改时原样交回：B 类（值在别处）由程序把出处改到核对结果里"实际在"的那一处。"""
    w = world
    w["fake"].wrong_first_summary = True
    w["fake"].stubborn = True
    tid = start(w)
    assert finish(w, tid)["status"] == "completed"
    page = wiki_file(w, f"材料/{index(w)['借条']['material_id']}.md")
    assert "今借到王某人民币80,000元〔借条 第2行〕" in page
    res = task_json(w, tid, "result.json")
    assert res["citation_check"]["stats"]["must_fix"] == 0
    rec = task_json(w, tid, "运行记录.json")
    assert any(f["轮次"] == "程序兜底" for f in rec["修改记录"])


def test_settle_unfixable_marked_not_found():
    """改不了的（不是 B 类，或改到别处也不过）：出处改标〔未找到依据〕；文号里的〔2026〕不动。"""
    from lawbench.checks import MaterialSet
    from lawbench.pipeline.runner import Budget, Progress
    mats = MaterialSet.from_texts([{"name": "借条", "material_id": "M0001", "sha256": "a" * 64, "unit": "line",
                                    "text": "【第1行】\n借款80,000元\n"}])
    r = Runner(llm=None, prompts=None, params={}, materials=mats, task_id="P-20260101000000-abcd",
               budget=Budget(1), progress=Progress())
    out = r.settle("- 据虚公刑诉字〔2026〕417号，借款90,000元〔借条 第1行〕\n- 借款80,000元〔借条 第1行〕", "x")
    assert out == "- 据虚公刑诉字〔2026〕417号，借款90,000元〔未找到依据〕\n- 借款80,000元〔借条 第1行〕"
    assert r.fixes[0]["轮次"] == "程序兜底" and len(r.fixes[0]["问题"]) == 1
    # 同一句 B（日期在别处）+ C（金额哪里都没有）：挪了出处还不过，整句改标〔未找到依据〕
    mats2 = MaterialSet.from_texts([{"name": "借条", "material_id": "M0001", "sha256": "a" * 64, "unit": "line",
                                     "text": "【第1行】\n2025年3月12日签\n借款80,000元\n"}])
    r2 = Runner(llm=None, prompts=None, params={}, materials=mats2, task_id="P-20260101000000-abcd",
                budget=Budget(1), progress=Progress())
    assert r2.settle("- 借款90,000元于2025年3月12日〔借条 第2行〕", "y") == "- 借款90,000元于2025年3月12日〔未找到依据〕"


def test_settle_per_class():
    """A：不动出处，插注原文的识别不清写法；C：只改有问题的那组出处；G：程序不改。"""
    from lawbench.checks import MaterialSet
    from lawbench.pipeline.runner import Budget, Progress
    mats = MaterialSet.from_texts([
        {"name": "流水", "material_id": "M0001", "sha256": "a" * 64, "unit": "page",
         "text": "【第1页】\n| 2025-03-20 | 转账 | 8■,000.00 | 陈美■ |\n\n【第2页】\n| 2025-03-12 | 转账 | 100,000.00 | 陈美华 |\n"}])
    r = Runner(llm=None, prompts=None, params={}, materials=mats, task_id="P-20260101000000-abcd",
               budget=Budget(1), progress=Progress())
    text = ("- 3月20日收到陈美华转账〔流水 第1页〕，3月12日收到100,000.00〔流水 第2页〕\n"
            "- 借款90,000元〔流水 第2页〕，3月12日陈美华转账100,000.00〔流水 第2页〕\n"
            "- 周立新显然知情〔流水 第2页〕")
    out = r.settle(text, "x").splitlines()
    assert out[0] == ("- 3月20日收到陈美华转账（原文流水 第1页为“陈美■”，识别不清，需核对原件）〔流水 第1页〕，"
                      "3月12日收到100,000.00〔流水 第2页〕")
    assert out[1] == "- 借款90,000元〔未找到依据〕，3月12日陈美华转账100,000.00〔流水 第2页〕"
    assert out[2] == "- 周立新显然知情〔流水 第2页〕"                         # G 程序改不了
    assert [p["class"] for _, _, ps in r.problem_lines("\n".join(out)) for p in ps] == ["G"]


# ---------- T16 返修（执行令 20261001-2147） ----------

def _wait_done(w, tid, limit):
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit:
        if w["st"].pipelines.status(tid)["status"] != "running":
            return time.monotonic() - t0
        time.sleep(0.05)
    return None


def _cancel_after_1s(w, tid):
    time.sleep(1)
    ok(w["client"].post(f"/api/pipeline/{tid}/cancel", json={}), "api/pipeline_cancel.schema.json")
    return _wait_done(w, tid, 10)


def test_cancel_while_waiting_headers(world):
    """P2-1：6000D 排队时迟迟不回响应头（假服务 30 秒），第 1 秒取消，10 秒内结束、状态 cancelled。"""
    w = world
    w["fake"].header_delay = 30
    tid = start(w)
    took = _cancel_after_1s(w, tid)
    assert took is not None and took < 10
    w["st"].pipelines.wait(tid, 10)
    assert finish(w, tid)["status"] == "cancelled" and task_json(w, tid, "result.json")["status"] == "cancelled"


def test_cancel_during_395(world):
    """P2-1：395 阶段也看取消标志（假 395 30 秒不回）。"""
    w = world
    w["fake"].prep_delay = 30
    tid = start(w, use_prep=True)
    took = _cancel_after_1s(w, tid)
    assert took is not None and took < 10
    w["st"].pipelines.wait(tid, 10)
    assert finish(w, tid)["status"] == "cancelled" and not w["fake"].requests


def test_cancel_closes_connection():
    """P2-1：真套接字——响应头一直不来，取消后很快抛 Cancelled，服务端看到连接断开（网关据此记 499）。"""
    import socket
    from lawbench.net import Net
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    port = srv.getsockname()[1]
    closed = threading.Event()

    def handle(c):
        buf = b""
        try:
            while True:
                while b"\r\n\r\n" not in buf:
                    got = c.recv(65536)
                    if not got:
                        return
                    buf += got
                head, buf = buf.split(b"\r\n\r\n", 1)
                if head.startswith(b"GET"):
                    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}")
                    continue
                c.settimeout(20)
                while c.recv(65536):                 # 不回响应头，等客户端断开
                    pass
                closed.set()
                return
        except OSError:
            closed.set()
        finally:
            c.close()

    def serve():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=handle, args=(c,), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()
    url = f"http://127.0.0.1:{port}/v1"
    net = Net({"llm_base_url": url, "llm_alt_base_url": None, "prep_base_url": url, "prep_alt_base_url": None})
    cancel = threading.Event()
    box = {}

    def go():
        t0 = time.monotonic()
        try:
            llm_mod.LLM(net, lambda: KEY, cancel).chat("s", "u", PARAMS, "P-20260101000000-abcd")
        except BaseException as e:  # noqa: BLE001
            box["e"], box["t"] = e, time.monotonic() - t0

    t = threading.Thread(target=go)
    t.start()
    time.sleep(1)
    cancel.set()
    t.join(5)
    srv.close()
    assert isinstance(box.get("e"), llm_mod.Cancelled) and box["t"] < 3
    assert closed.wait(5)


def test_same_case_started_twice_at_once(world, monkeypatch):
    """P2-3：同一案件两个请求同时到（建任务前放慢一点），只起一个任务、两个请求拿到同一个编号。"""
    w = world
    orig = wiki.load_materials
    monkeypatch.setattr(wiki, "load_materials", lambda *a, **k: (time.sleep(0.3), orig(*a, **k))[1])
    d = {"case_id": w["cid"], "step": "wiki_build", "use_prep": False, "params": PARAMS}
    gate_ = threading.Barrier(2)
    got = []

    def one():
        gate_.wait()
        got.append(w["st"].pipelines.run(dict(d))["task_id"])

    ts = [threading.Thread(target=one) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(10)
    assert len(got) == 2 and got[0] == got[1]
    finish(w, got[0])
    assert [p.name for p in (w["root"] / "工作区" / "任务").iterdir() if p.name.startswith("P-")] == [got[0]]


def test_dirs_made_before_parallel_steps(world):
    """P2-2：第一次调模型之前，wiki 的 材料/、案件/ 和任务的 草稿/ 都已建好（两路并行第一次建目录时闸门偶发误判）。"""
    w = world
    seen = []

    def look():
        base = w["root"] / "工作区"
        seen.append(((base / "wiki" / "案件").is_dir(), (base / "wiki" / "材料").is_dir(),
                     any((t / "草稿").is_dir() for t in (base / "任务").iterdir())))

    w["fake"].on_summary = look
    assert finish(w, start(w))["status"] == "completed"
    assert seen and all(x == (True, True, True) for x in seen)


def _small_chunks(monkeypatch):
    orig = wiki.chunk
    monkeypatch.setattr(wiki, "chunk", lambda m, limit=wiki.CHUNK_CHARS: orig(m, 20))   # 借条 4 段、说明 2 段


def _row(w, name):
    return next(ln for ln in wiki_file(w, "案件/材料清单.md").splitlines() if ln.startswith(f"| {name} |"))


def test_stop_keeps_complete_page(world, monkeypatch):
    """P2-4：已有完整摘要页时，停下不覆盖；半份存任务草稿；清单写"保留上次的摘要页"。"""
    w = world
    _small_chunks(monkeypatch)
    finish(w, start(w))
    mid = index(w)["借条"]["material_id"]
    before = wiki_file(w, f"材料/{mid}.md")
    monkeypatch.setattr("lawbench.pipeline.budget_calls", lambda s, a: 1)
    tid = start(w)
    assert finish(w, tid)["status"] == "budget_stopped"
    assert wiki_file(w, f"材料/{mid}.md") == before
    drafts = [p.name for p in (w["root"] / "工作区" / "任务" / tid / "草稿").iterdir()]
    assert drafts == [f"材料摘要 {mid} 部分（1 段，共 4 段）-v1.md"]
    assert "| 是 |" in _row(w, "借条") and "保留上次的摘要页" in _row(w, "借条")


def test_stop_without_old_page_writes_part(world, monkeypatch):
    """P2-4：没有旧页时写半份，页首和材料清单都写"部分（k/n 段）"；一段没写的写"运行中止，未生成"。"""
    w = world
    _small_chunks(monkeypatch)
    monkeypatch.setattr("lawbench.pipeline.budget_calls", lambda s, a: 1)
    tid = start(w)
    assert finish(w, tid)["status"] == "budget_stopped"
    page = wiki_file(w, f"材料/{index(w)['借条']['material_id']}.md")
    assert page.splitlines()[1] == f"{wiki.PARTIAL_HEAD}部分（1/4 段），运行中止，没有读完"
    assert "| 部分（1/4 段） |" in _row(w, "借条") and _row(w, "说明").endswith("| **否** | 运行中止，未生成 |")
    assert "已读 1 份" in wiki_file(w, "案件/材料清单.md")          # 只有程序筛选的流水算读完


def test_run_record_has_no_text(world):
    """P3-1：运行记录的对象写材料编号，修改记录不写原句（兜底也只记行号和做法）。"""
    w = world
    w["fake"].wrong_first_summary = True
    w["fake"].stubborn = True
    tid = start(w)
    finish(w, tid)
    raw = (w["root"] / "工作区" / "任务" / tid / "运行记录.json").read_text(encoding="utf-8")
    rec = json.loads(raw)
    assert any(f["轮次"] == "程序兜底" for f in rec["修改记录"])
    for s in ("借条", "说明", "80,000", "王某", "〔"):
        assert s not in raw, s
    assert any(re.fullmatch(r"M\d{4}#1", c["对象"]) for c in rec["调用"])


def test_two_cases_share_two_slots(world, tmp_path):
    """P3-2：两个案件同时跑，同时在途的 6000D 请求不超过 2 个（Spec 8.5 每位律师 2 路）。"""
    w = world
    root2 = tmp_path / "案件二"
    root2.mkdir()
    for n, t in CASE.items():
        (root2 / n).write_text(t, encoding="utf-8")
    cid2 = ok(w["client"].post("/api/case/open", json={"path": str(root2)}), "api/case_open.schema.json")["case_id"]
    ok(w["client"].post("/api/materials/scan", json={"case_id": cid2}), "api/materials_scan.schema.json")
    w["fake"].slow = 0.15
    a = start(w)
    b = ok(w["client"].post("/api/pipeline/run", json={"case_id": cid2, "step": "wiki_build", "use_prep": False,
                                                       "params": PARAMS}), "api/pipeline_run.schema.json")["task_id"]
    assert finish(w, a)["status"] == "completed" and finish(w, b)["status"] == "completed"
    assert w["fake"].max_inflight == 2


def test_fix_rounds_at_most_two(world):
    """P3-3：修改后内容有变化但问题还在：最多 2 轮。"""
    w = world
    w["fake"].wrong_first_summary = True
    w["fake"].fix_wrong = True
    finish(w, start(w))
    assert sum(r["step"] == "修改" for r in w["fake"].requests) == 2


def test_fix_stops_when_unchanged(world):
    """P3-3：修改轮原样交回：第 1 轮后就停。"""
    w = world
    w["fake"].wrong_first_summary = True
    w["fake"].stubborn = True
    finish(w, start(w))
    assert sum(r["step"] == "修改" for r in w["fake"].requests) == 1


def _jump_clock(w):
    off = [0.0]
    w["st"].pipelines.clock = lambda: time.monotonic() + off[0]
    w["fake"].on_summary = lambda: off.__setitem__(0, 46 * 60)        # 第一次摘要调用时时钟跳过 46 分钟
    return off


def test_minutes_limit(world):
    """P3-3：45 分钟上限（注入时钟）：到了就停在下一次调用前，状态 budget_stopped。"""
    w = world
    _jump_clock(w)
    tid = start(w)
    assert finish(w, tid)["status"] == "budget_stopped"
    assert len(w["fake"].requests) <= 2


def test_queue_wait_not_counted(world):
    """P3-3：排队时间不算进 45 分钟：时钟跳过 46 分钟、但每次都排队 46 分钟，照常完成。"""
    w = world
    _jump_clock(w)
    w["fake"].queue_ms = 46 * 60 * 1000
    assert finish(w, start(w))["status"] == "completed"


def test_llm_goes_through_net_selection(world):
    """P3-3：6000D 地址由 Net 选：所内探测不通时走所外。"""
    w = world
    w["fake"].primary_down = True
    assert finish(w, start(w))["status"] == "completed"
    assert w["fake"].requests and {r["host"] for r in w["fake"].requests} == {"10.126.126.1"}


def test_lawyer_confirmed_and_stance_kept(world):
    """P3-3：律师确认的条目和本方立场在重新生成后保留。"""
    w = world
    finish(w, start(w))
    p = w["root"] / "工作区" / "wiki" / "case.json"
    card = json.loads(p.read_text(encoding="utf-8"))
    card["stance"] = {"text": "主张已部分还款", "set_at": card["generated_at"]}
    card["key_facts"][0].update(text="律师核实：借款80,000元", status="lawyer_confirmed")
    assert not contracts.errors("files/case_card.schema.json", "", card)
    p.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    assert finish(w, start(w))["status"] == "completed"
    new = json.loads(p.read_text(encoding="utf-8"))
    assert new["stance"] == card["stance"]
    assert [f["text"] for f in new["key_facts"] if f["status"] == "lawyer_confirmed"] == ["律师核实：借款80,000元"]


@pytest.mark.parametrize("dup,bad,used", [(3, 2, False), (17, 6, True)])
def test_prep_threshold_boundary(world, dup, bad, used):
    """P3-3：9B 字段核对不过 25%（高于 20%）整体跳过，15% 照用。"""
    w = world
    w["fake"].prep_mode, w["fake"].prep_dup, w["fake"].prep_bad = "mix", dup, bad
    tid = start(w, use_prep=True)
    assert finish(w, tid)["status"] == "completed"
    rec = task_json(w, tid, "运行记录.json")["395"]
    assert rec["核对不过"] / rec["字段"] == (0.25 if not used else 0.15)
    assert (rec["提示"] is None) == used
    assert any("395 抽取的参考字段" in r["user"] for r in w["fake"].requests) == used


def test_update_reruns_missing_or_partial_pages(world):
    """P3-3：更新时，没有摘要页的、摘要页只有部分的材料也重跑（sha 没变）。"""
    w = world
    finish(w, start(w))
    mats = index(w)
    (w["root"] / "工作区" / "wiki" / "材料" / f"{mats['借条']['material_id']}.md").unlink()
    p = w["root"] / "工作区" / "wiki" / "材料" / f"{mats['说明']['material_id']}.md"
    p.write_text(f"# 说明\n{wiki.PARTIAL_HEAD}部分（1/2 段），运行中止，没有读完\n\n## 摘要\n\n- 半份\n", encoding="utf-8")
    n0 = len(w["fake"].requests)
    assert finish(w, start(w, "wiki_update"))["status"] == "completed"
    got = sorted(r["user"].split("\n", 1)[0] for r in w["fake"].requests[n0:] if r["step"] == "材料摘要")
    assert got == ["材料名：借条", "材料名：说明"]


def test_card_length_finish_not_success(world):
    """P3-3：卡片 finish_reason=length 即使 JSON 能解析也不算成功，重试。"""
    w = world
    w["fake"].card_len_valid = 1
    assert finish(w, start(w))["status"] == "completed"
    assert sum(r["step"] == "案件卡片" for r in w["fake"].requests) == 2


def test_status_checks_task_kind(world):
    """P3-3：status、cancel 只认流水线任务。"""
    from lawbench.errors import ApiError
    w = world
    tid = ok(w["client"].post("/core/task/begin", json={"session_id": "s-t16k", "cwd": str(w["root"])}),
             "core/task_begin.schema.json")["task_id"]
    for fn in (w["st"].pipelines.status, w["st"].pipelines.cancel):
        with pytest.raises(ApiError) as e:
            fn(tid)
        assert e.value.code == "TASK_NOT_FOUND"


def test_consecutive_lawyer_blocks_keep_order():
    """P3-4：连续几块整组放回，顺序不变。"""
    def blk(x):
        return f"<!-- 律师修改 -->\n{x}\n<!-- /律师修改 -->"
    old = f"# 标题\n\n第一行\n{blk('一')}\n{blk('二')}\n\n{blk('三')}\n第二行\n"
    blocks = wiki.take_lawyer_blocks(old)
    assert len(blocks) == 1 and blocks[0][0] == "第一行"
    out = wiki.put_lawyer_blocks("# 标题\n\n第一行\n新内容", blocks)
    assert out.index("一") < out.index("二") < out.index("三") < out.index("新内容")
    two = [("第一行", blk("甲")), ("第一行", blk("乙"))]      # 不同组落在同一位置（锚点相同）也按原来的先后
    out = wiki.put_lawyer_blocks("第一行\n尾", two)
    assert out.index("甲") < out.index("乙") < out.index("尾")


def test_window_exceeded_fails_before_sending(world):
    """P3-6：系统提示 + 输入 + max_tokens 超过窗口：不发，整次 failed、错误 CONTEXT_TOO_LONG。"""
    w = world
    params = {"thinking": "关闭", "window": "32K", "max_tokens": 32768}
    tid = ok(w["client"].post("/api/pipeline/run", json={"case_id": w["cid"], "step": "wiki_build", "use_prep": False,
                                                         "params": params}), "api/pipeline_run.schema.json")["task_id"]
    assert finish(w, tid)["status"] == "failed"
    assert task_json(w, tid, "运行记录.json")["错误"] == "CONTEXT_TOO_LONG" and not w["fake"].requests


def test_bad_old_card_not_overwritten(world):
    """P3-7：旧 case.json 不合契约：不覆盖、整次报错，不发任何请求。"""
    w = world
    p = w["root"] / "工作区" / "wiki" / "case.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    bad = '{"v": 1, "stance": {"text": "律师写的立场"}}'
    p.write_text(bad, encoding="utf-8")
    tid = start(w)
    assert finish(w, tid)["status"] == "failed"
    assert task_json(w, tid, "运行记录.json")["错误"] == "INVALID_ARGUMENT" and not w["fake"].requests
    assert p.read_text(encoding="utf-8") == bad


def test_index_lawyer_block_kept(world):
    """NOTE：目录 index.md 也保护律师修改块。"""
    w = world
    finish(w, start(w))
    p = w["root"] / "工作区" / "wiki" / "index.md"
    block = "<!-- 律师修改 -->\n备注\n<!-- /律师修改 -->"
    p.write_text(p.read_text(encoding="utf-8").replace("## 材料\n", "## 材料\n" + block + "\n"), encoding="utf-8")
    finish(w, start(w))
    assert block in p.read_text(encoding="utf-8")


@pytest.mark.parametrize("exc,code", [(httpx.RemoteProtocolError, "SERVER_UNREACHABLE"), (httpx.ReadTimeout, "TIMEOUT")])
def test_network_errors_mapped(world, exc, code):
    """NOTE：网络异常按 Spec 8.3 的错误码记，不记异常类名。"""
    w = world
    w["fake"].raise_exc = exc
    tid = start(w)
    assert finish(w, tid)["status"] == "failed"
    assert task_json(w, tid, "运行记录.json")["错误"] == code


def test_key_invalid_stops_other_segments(world, monkeypatch):
    """NOTE：某段报 401 后，排着的其余段不再发出（只有并行的 2 路）。"""
    w = world
    _small_chunks(monkeypatch)
    w["fake"].status = 401
    tid = start(w)
    assert finish(w, tid)["status"] == "failed"
    assert len(w["fake"].requests) <= 2
