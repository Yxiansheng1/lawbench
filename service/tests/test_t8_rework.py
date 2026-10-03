"""T8 返修（执行令 致B-ORCH-执行令-T8返修-20260930-0201 与补充 0608；注记 0651、0805）逐条测试。编号与返修令一致。"""
from __future__ import annotations

import json
import pathlib
import sys
import threading
import time

import pytest

from lawbench.case import gate, texts
from lawbench.case.task import TaskStore
from lawbench.llm import tokens
from lawbench.tools import drafts as drafts_mod

from t8_helpers import CASE_FILES, FIXTURES, Env, fail, ok, validator


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    files = dict(CASE_FILES)
    e = Env(tmp_path_factory.mktemp("t8rw"), files)
    yield e
    e.close()


@pytest.fixture
def small(tmp_path):
    """一份有长行的 txt：第 2 行 3360 字，其余短。"""
    src = tmp_path / "src"
    src.mkdir()
    (src / "长行说明.txt").write_text("第一行\n" + "长" * 3360 + "\n第三行\n", encoding="utf-8")
    e = Env(tmp_path / "case", {"长行说明.txt": src / "长行说明.txt"})
    yield e
    e.close()


def rootof(env) -> str:
    return env.client.app.state.lb.cases.root_of(env.case_id)


def store(env) -> TaskStore:
    return env.client.app.state.lb.tasks


def end(env, tid, reason="completed", **kw):
    body = {"task_id": tid, "reason": reason, "model_calls": 1, "tool_calls": 1, "elapsed_s": 1, **kw}
    return env.client.post("/core/task/end", json=body)


def progress(env, tid, text="进度", model_calls=1, tool_calls=1):
    return env.client.post("/core/progress", json={"task_id": tid, "text": text, "model_calls": model_calls,
                                                   "tool_calls": tool_calls})


def coverage_of(env, tid) -> dict:
    s = store(env)
    return s.coverage(rootof(env), env.case_id, tid)


def create(env, session, skill="contract-review"):
    req = {"case_id": env.case_id, "session_id": session, "entry": skill, "skill": skill, "inputs": [],
           "params": {"thinking": "中", "window": "64K", "max_tokens": 4096}}
    return ok(env.client.post("/api/task", json=req), "api/task_create.schema.json")["task_id"]


# ---------- P1-1（按契约 1.2 N31）：单元超长时用 offset 接着读；没读全的单元不算已读 ----------

def _reads(e, tid):
    return [(r["from"], r["to"]) for r in e.read_json(tid, "reads.json", "files/reads.schema.json")["reads"]]


@pytest.mark.parametrize("max_chars", [500, None])
def test_p1_1_long_unit_read_in_parts(small, max_chars):
    if max_chars is None:  # 默认 8000：把第 2 行做得比 8000 还长
        (small.root / "长行说明.txt").write_text("第一行\n" + "长" * 9000 + "\n第三行\n", encoding="utf-8")
        ok(small.client.post("/api/materials/scan", json={"case_id": small.case_id}), "api/materials_scan.schema.json")
    limit = max_chars or 8000
    tid = small.begin("sess-trunc")["task_id"]
    args = {"name": "长行说明", "start": 2}
    if max_chars:
        args["max_chars"] = max_chars
    v = small.tool_ok(tid, "case_read_material", args)
    assert len(v["text"]) <= limit and v["start"] == v["end"] == 2
    assert v["next_offset"] and v["next_start"] == 2 and v["has_more"]
    assert _reads(small, tid) == []                                    # 第 2 行没读全：不记
    got = v["text"]
    while v["next_offset"] is not None:
        v = small.tool_ok(tid, "case_read_material", dict(args, offset=v["next_offset"]))
        assert len(v["text"]) <= limit
        got += v["text"]
    assert got.count("长") == (9000 if max_chars is None else 3360)    # 分段接起来一个字不少
    assert v["next_start"] == 3 and _reads(small, tid) == [(2, 2)]     # 读到单元末尾：这时才记
    small.tool_ok(tid, "case_read_material", {"name": "长行说明", "start": 1, "max_chars": 500})
    small.tool_ok(tid, "case_read_material", {"name": "长行说明", "start": 3})
    ok(end(small, tid), "core/task_end.schema.json")
    cov = small.read_json(tid, "result.json", "files/result.schema.json")["coverage"]
    assert cov["fully_read"] == ["长行说明"]


def test_p1_1_skipping_part_not_counted(small):
    """只读了开头一段、跳过中间直接读末尾：不算读完。"""
    tid = small.begin("sess-skip")["task_id"]
    v = small.tool_ok(tid, "case_read_material", {"name": "长行说明", "start": 2, "max_chars": 500})
    small.tool_ok(tid, "case_read_material", {"name": "长行说明", "start": 2, "max_chars": 500, "offset": 3000})
    assert v["next_offset"] < 3000 and _reads(small, tid) == []
    ok(end(small, tid), "core/task_end.schema.json")
    cov = small.read_json(tid, "result.json", "files/result.schema.json")["coverage"]
    assert "长行说明" not in cov["fully_read"]


def test_p1_1_offset_out_of_range(small):
    tid = small.begin("sess-off")["task_id"]
    fail(small.tool(tid, "case_read_material", {"name": "长行说明", "start": 2, "offset": 99999}), "INVALID_ARGUMENT")


def test_p1_1_whole_units_still_recorded(small):
    tid = small.begin("sess-whole")["task_id"]
    v = small.tool_ok(tid, "case_read_material", {"name": "长行说明", "start": 1, "max_chars": 500})
    assert v["end"] == 1 and v["next_offset"] is None
    assert _reads(small, tid) == [(1, 1)]


# ---------- P1-2：执行中重开同一案件 ----------

def test_p1_2_reopen_does_not_touch_running_task_of_this_process(env):
    tid = env.begin("sess-reopen")["task_id"]
    ok(env.client.post("/api/case/open", json={"path": str(env.root)}), "api/case_open.schema.json")
    assert env.read_json(tid, "task.json", "files/task.schema.json")["state"] == "running"
    env.tool_ok(tid, "case_list_materials", {})
    env.tool_ok(tid, "case_save_draft", {"title": "重开后", "content": "x"})
    assert ok(end(env, tid), "core/task_end.schema.json")["status"] == "completed"


def test_p1_2_hard_exit_leftover_still_marked(env):
    tid = env.begin("sess-crash2")["task_id"]
    store(env)._begun.pop(tid)                      # 当成上一个进程留下的
    ok(env.client.post("/api/case/open", json={"path": str(env.root)}), "api/case_open.schema.json")
    assert env.read_json(tid, "task.json", "files/task.schema.json")["state"] == "abnormal"


# ---------- P1-3：result.json 的读-改-写互斥（确定的交错顺序） ----------

def test_p1_3_progress_and_save_draft_do_not_lose_drafts(env, monkeypatch):
    tid = env.begin("sess-race")["task_id"]
    s = store(env)
    real_result = TaskStore.result
    in_progress = threading.Event()

    def slow_result(self, root, task_id):
        data = real_result(self, root, task_id)
        if sys._getframe(1).f_code.co_name == "progress":   # 只在 progress 里停（请求跑在线程池里，线程名认不出）
            in_progress.set()
            time.sleep(0.5)          # progress 读完 result.json 后停一下，让 save_draft 插进来
        return data

    monkeypatch.setattr(TaskStore, "result", slow_result)
    t = threading.Thread(target=lambda: progress(env, tid, "中途"), name="progress")
    t.start()
    assert in_progress.wait(5)
    env.tool_ok(tid, "case_save_draft", {"title": "交错", "content": "x"})
    t.join(10)
    res = env.read_json(tid, "result.json", "files/result.schema.json")
    assert [d["title"] for d in res["drafts"]] == ["交错"]
    ok(end(env, tid), "core/task_end.schema.json")
    names = sorted(p.name for p in (env.task_dir(tid) / "草稿").iterdir())
    assert not any(n.startswith("未完成") for n in names)


def test_p1_3_locks_are_per_task(env):
    s = store(env)
    assert s.task_lock("T-20260930000000-aaaa") is s.task_lock("T-20260930000000-aaaa")
    assert s.task_lock("T-20260930000000-aaaa") is not s.task_lock("T-20260930000000-bbbb")


# ---------- P2-1：占位页不算已读 ----------

def test_p2_1_placeholder_units_not_read(env):
    tid = env.begin("sess-ocr")["task_id"]
    idx = env.client.app.state.lb.materials.index(env.case_id)
    m = next(m for m in idx["materials"] if m["name"] == "起诉意见书")
    text_path = env.root / "工作区" / "材料" / "文本" / (m["rel_path"] + ".md")
    original = text_path.read_text(encoding="utf-8")
    units = texts.split_units(original, "page")
    try:
        patched = original
        for u in units[1:]:   # 第 2 页起换成占位
            patched = patched.replace(u.header + "\n" + u.text, u.header + "\n" + texts.PENDING_OCR, 1)
        text_path.write_text(patched, encoding="utf-8")
        start = 1
        while start:
            v = env.tool_ok(tid, "case_read_material", {"name": "起诉意见书", "start": start})
            start = v["next_start"]
        cov = coverage_of(env, tid)
        assert "起诉意见书" not in cov["fully_read"]
        part = next(p for p in cov["partially_read"] if p["name"] == "起诉意见书")
        assert part["read_units"] == 1 and part["total_units"] == len(units)
    finally:
        text_path.write_text(original, encoding="utf-8")


# ---------- P2-2：草稿版本号 ----------

def test_p2_2_case_insensitive_versions(env):
    tid = env.begin("sess-case-title")["task_id"]
    vs = [env.tool_ok(tid, "case_save_draft", {"title": t, "content": t})["version"]
          for t in ("Report", "report", "REPORT")]
    assert vs == [1, 2, 3]
    files = sorted(p.name.casefold() for p in (env.task_dir(tid) / "草稿").iterdir() if p.suffix == ".md")
    assert files == ["report-v1.md", "report-v2.md", "report-v3.md"]


@pytest.fixture
def slow_writes(monkeypatch):
    """写文件前停一下，让并发请求的读-改-写一定交错（没有锁时必然丢更新）。"""
    real = gate.write_bytes

    def slow(*a, **k):
        time.sleep(0.1)
        return real(*a, **k)

    monkeypatch.setattr(gate, "write_bytes", slow)


def test_p2_2_concurrent_same_title(env, slow_writes):
    tid = env.begin("sess-conc-title")["task_id"]
    out = []
    ths = [threading.Thread(target=lambda i=i: out.append(env.tool_ok(tid, "case_save_draft",
                                                                       {"title": "同题", "content": str(i)})))
           for i in range(4)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(30)
    assert sorted(v["version"] for v in out) == [1, 2, 3, 4]
    res = env.read_json(tid, "result.json", "files/result.schema.json")
    assert sorted(d["version"] for d in res["drafts"]) == [1, 2, 3, 4]


# ---------- P2-3：待确认.json 的读-改-写加锁 ----------

def test_p2_3_concurrent_suggestions(env, slow_writes):
    tid = env.begin("sess-wiki")["task_id"]
    ids = []
    ths = [threading.Thread(target=lambda i=i: ids.append(env.tool_ok(tid, "case_suggest_wiki", {
        "field": "关键事实", "value": f"事实{i}", "source": "〔借条 第2段〕"})["suggestion_id"])) for i in range(5)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(30)
    assert len(set(ids)) == 5
    data = json.loads((env.root / "工作区" / "wiki" / "待确认.json").read_text(encoding="utf-8"))
    values = {s["value"] for s in data["suggestions"]}
    assert {f"事实{i}" for i in range(5)} <= values


# ---------- P2-4：终态 ----------

def test_p2_4_end_is_idempotent_and_progress_after_end_ignored(env):
    tid = env.begin("sess-final")["task_id"]
    assert ok(end(env, tid, "aborted"), "core/task_end.schema.json")["status"] == "cancelled"
    before = env.read_json(tid, "result.json", "files/result.schema.json")
    assert ok(end(env, tid, "completed", model_calls=9, tool_calls=9, elapsed_s=9),
              "core/task_end.schema.json")["status"] == "cancelled"
    ok(progress(env, tid, "迟到的进度", 7, 7), "core/progress.schema.json")
    after = env.read_json(tid, "result.json", "files/result.schema.json")
    assert after == before
    assert not (env.task_dir(tid) / "草稿" / "进行中.md").exists()


# ---------- P2-5：扫描期间读索引不等锁 ----------

def test_p2_5_index_does_not_wait_for_scan_lock(env):
    mats = env.client.app.state.lb.materials
    lock = mats._lock(env.case_id)
    tid = env.begin("sess-lock")["task_id"]
    held = threading.Event()

    def hold():  # 另一个线程持锁 3 秒，模拟扫描（锁在测试线程里拿会让改坏的版本死等）
        with lock:
            held.set()
            time.sleep(3)

    t = threading.Thread(target=hold)
    t.start()
    assert held.wait(5)
    t0 = time.monotonic()
    env.tool_ok(tid, "case_list_materials", {})
    assert time.monotonic() - t0 < 2
    t.join()


# ---------- P2-6：_mkdirs 并发 ----------

def test_p2_6_mkdirs_tolerates_concurrent_creation(tmp_path, monkeypatch):
    root = gate.check_root(str(tmp_path))
    target = pathlib.Path(root) / "工作区" / "任务" / "x" / "草稿"
    real_mkdir = gate.os.mkdir

    def racing_mkdir(p, *a, **k):
        real_mkdir(p, *a, **k)          # 别人抢先建好了
        raise FileExistsError(p)

    monkeypatch.setattr(gate.os, "mkdir", racing_mkdir)
    gate._mkdirs(root, target, "t")
    assert target.is_dir()


def test_p2_6_mkdirs_still_rejects_file(tmp_path, monkeypatch):
    root = gate.check_root(str(tmp_path))
    (pathlib.Path(root) / "工作区").mkdir()
    (pathlib.Path(root) / "工作区" / "任务").write_text("x", encoding="utf-8")   # 同名文件
    with pytest.raises(gate.GateError):
        gate._mkdirs(root, pathlib.Path(root) / "工作区" / "任务" / "a", "t")


# ---------- P2-7（按契约 1.2 N37）：设置当前选择；begin 按选择复制，选择不消耗 ----------

def current(env, session):
    return ok(env.client.get("/api/task/current", params={"session_id": session}),
              "api/task_current.schema.json")["selection"]


def test_p2_7_selection_not_consumed(env):
    a = create(env, "sess-p27", "contract-review")
    b = create(env, "sess-p27", "case-summary")
    assert not env.task_dir(a).exists()                              # 新的顶掉旧的
    v1 = env.begin("sess-p27")
    v2 = env.begin("sess-p27")
    assert v1["skill"] == v2["skill"] == "case-summary"             # 每条消息都按当前选择跑
    assert len({v1["task_id"], v2["task_id"], b}) == 3              # 复制出新的执行中任务
    assert env.read_json(b, "task.json", "files/task.schema.json")["state"] == "pending"   # 选择不消耗
    assert env.read_json(v1["task_id"], "task.json", "files/task.schema.json")["state"] == "running"


def test_p2_7_switch_back_to_free(env):
    create(env, "sess-p27f", "contract-review")
    req = {"case_id": env.case_id, "session_id": "sess-p27f", "entry": None, "skill": None, "inputs": [],
           "params": {"thinking": "低", "window": "32K", "max_tokens": 2048}}
    ok(env.client.post("/api/task", json=req), "api/task_create.schema.json")
    v = env.begin("sess-p27f")
    assert v["skill"] is None and v["params"]["thinking"] == "低"


def test_p2_7_task_current_three_forms(env):
    assert current(env, "sess-p27-none") is None
    b = create(env, "sess-p27c", "case-summary")
    sel = current(env, "sess-p27c")
    assert sel["task_id"] == b and sel["skill"] == "case-summary" and sel["inputs"] == []
    req = {"case_id": env.case_id, "session_id": "sess-p27c", "entry": None, "skill": None, "inputs": [],
           "params": {"thinking": "中", "window": "64K", "max_tokens": 4096}}
    ok(env.client.post("/api/task", json=req), "api/task_create.schema.json")
    sel = current(env, "sess-p27c")
    assert sel["entry"] is None and sel["skill"] is None             # 自由对话
    env.begin("sess-p27c")
    assert current(env, "sess-p27c") is not None                     # begin 之后选择还在


def test_p2_7_same_second_later_wins(env, monkeypatch):
    from lawbench.case import task as task_mod
    monkeypatch.setattr(task_mod, "now_iso", lambda: "2026-09-30T10:00:00+08:00")
    a = create(env, "sess-p27s", "contract-review")
    b = create(env, "sess-p27s", "case-summary")
    monkeypatch.undo()
    assert not env.task_dir(a).exists()
    assert env.begin("sess-p27s")["skill"] == "case-summary" and current(env, "sess-p27s")["task_id"] == b


def test_p2_7_other_session_untouched(env):
    other = create(env, "sess-p27-other")
    create(env, "sess-p27-mine")
    assert env.read_json(other, "task.json", "files/task.schema.json")["state"] == "pending"


def test_p2_7_running_and_finished_not_deleted(env):
    run = env.begin("sess-p27-run")["task_id"]
    fin = env.begin("sess-p27-fin")["task_id"]
    ok(end(env, fin), "core/task_end.schema.json")
    for sess in ("sess-p27-run", "sess-p27-fin"):
        create(env, sess)
    assert env.task_dir(run).exists() and env.task_dir(fin).exists()


def test_p2_7_pending_with_extra_files_not_deleted(env):
    a = create(env, "sess-p27-extra")
    (env.task_dir(a) / "草稿").mkdir()
    (env.task_dir(a) / "草稿" / "x.md").write_text("x", encoding="utf-8")
    create(env, "sess-p27-extra")
    assert (env.task_dir(a) / "task.json").exists()


def test_p2_7_voided_not_listed(env):
    a = create(env, "sess-p27-list")
    b = create(env, "sess-p27-list")
    listed = {t["task_id"] for t in ok(env.client.get("/api/tasks", params={"case_id": env.case_id}),
                                        "api/tasks_list.schema.json")["tasks"]}
    assert a not in listed and b not in listed                     # 注记 0651：待执行的不列
    assert not env.task_dir(a).exists()                              # 注记 0805：被顶掉的不留 result.json


# ---------- 注记 0651：/api/tasks 不列待执行 ----------

def test_tasks_list_excludes_pending(env):
    a = create(env, "sess-0651")
    listed = {t["task_id"] for t in ok(env.client.get("/api/tasks", params={"case_id": env.case_id}),
                                        "api/tasks_list.schema.json")["tasks"]}
    assert a not in listed
    run = env.begin("sess-0651")["task_id"]
    tasks = ok(env.client.get("/api/tasks", params={"case_id": env.case_id}), "api/tasks_list.schema.json")["tasks"]
    listed = {t["task_id"] for t in tasks}
    assert run in listed and a not in listed                          # 1.2：选择不消耗，也不列
    item = next(t for t in tasks if t["task_id"] == run)
    assert item["coverage"] is None and item["citation_check"] is None  # N35①：还没保存过，都是 null


# ---------- P3-1：目录那几行计入预算 ----------

def test_p3_1_toc_counted_in_budget(env, monkeypatch):
    tid0 = env.begin("sess-l1src")["task_id"]
    paths = [env.tool_ok(tid0, "case_save_draft", {"title": f"输入标题比较长的一份材料{i:02d}",
                                                   "content": "甲" * 300})["path"] for i in range(40)]
    req = {"case_id": env.case_id, "session_id": "sess-l1", "entry": None, "skill": None, "inputs": paths,
           "params": {"thinking": "中", "window": "32K", "max_tokens": 4096}}
    ok(env.client.post("/api/task", json=req), "api/task_create.schema.json")
    tid = env.begin("sess-l1")["task_id"]
    monkeypatch.setattr(tokens, "l1_budget", lambda w: 3000)
    v = ok(env.client.post("/core/context", json={"task_id": tid}), "core/context.schema.json")
    assert v["l1"]["truncated"] and v["l1"]["tokens"] <= 3000


# ---------- P3-2：没 begin 的任务 ----------

def test_p3_2_progress_end_on_pending(env):
    a = create(env, "sess-p32")
    fail(progress(env, a), "TASK_NOT_FOUND")
    fail(end(env, a), "TASK_NOT_FOUND")
    assert env.read_json(a, "task.json", "files/task.schema.json")["state"] == "pending"


# ---------- P3-3：elapsed_s 从 begin 算起 ----------

def test_p3_3_elapsed_from_begin(env, monkeypatch):
    from lawbench.case import task as task_mod
    monkeypatch.setattr(task_mod, "now_iso", lambda: "2020-01-01T00:00:00+08:00")
    create(env, "sess-p33")
    tid = env.begin("sess-p33")["task_id"]          # task.json 的建单时间写成很久以前
    monkeypatch.undo()
    ok(progress(env, tid), "core/progress.schema.json")
    assert env.read_json(tid, "result.json", "files/result.schema.json")["usage"]["elapsed_s"] < 60


# ---------- 测试缺口：单元号裁剪、add_read 的锁 ----------

def test_gap_coverage_clips_unit_numbers(small):
    tid = small.begin("sess-clip")["task_id"]
    s = store(small)
    m = small.client.app.state.lb.materials.index(small.case_id)["materials"][0]
    s.add_read(rootof(small), tid, {"material_id": m["material_id"], "material_version": m["sha256"],
                                          "unit": "line", "from": 2, "to": 10, "at": "2026-09-30T10:00:00+08:00"})
    cov = s.coverage(rootof(small), small.case_id, tid)
    assert cov["partially_read"] == [{"name": "长行说明", "read_units": 2, "total_units": 3}]


def test_gap_add_read_is_locked(small, monkeypatch):
    tid = small.begin("sess-addread")["task_id"]
    s = store(small)
    real_read = TaskStore._read

    def slow_read(root, rel, schema):
        data = real_read(root, rel, schema)
        if rel.endswith("reads.json"):
            time.sleep(0.2)
        return data

    monkeypatch.setattr(TaskStore, "_read", staticmethod(slow_read))
    rec = {"material_id": "M0001", "material_version": "0" * 64, "unit": "line", "from": 1, "to": 1,
           "at": "2026-09-30T10:00:00+08:00"}
    ths = [threading.Thread(target=s.add_read, args=(rootof(small), tid, rec)) for _ in range(3)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(30)
    monkeypatch.undo()
    assert len(small.read_json(tid, "reads.json", "files/reads.schema.json")["reads"]) == 3


# ---------- 契约 1.2 N35①：tasks_list 带 coverage、citation_check ----------

def test_n35_tasks_list_has_coverage_and_check(env):
    tid = env.begin("sess-n35")["task_id"]
    env.tool_ok(tid, "case_save_draft", {"title": "带覆盖", "content": "x"})
    tasks = ok(env.client.get("/api/tasks", params={"case_id": env.case_id}), "api/tasks_list.schema.json")["tasks"]
    item = next(t for t in tasks if t["task_id"] == tid)
    assert item["coverage"]["total"] > 0 and item["citation_check"]["passed"] is True


# ---------- 契约 1.2 N35⑥：GET /api/outputs ----------

def test_n35_outputs_empty_and_filled(env):
    idx = env.root / "成果" / "索引.json"
    assert ok(env.client.get("/api/outputs", params={"case_id": env.case_id}),
              "api/outputs_list.schema.json") == {"v": 1, "outputs": []}
    data = {"v": 1, "outputs": [{"title": "审查意见", "version": 1, "files": [{"format": "md", "path": "成果/审查意见-v1.md"}],
                                 "task_id": "T-20260930100000-abcd", "inputs": [], "citation_passed": True,
                                 "confirmed_at": "2026-09-30T10:00:00+08:00"}]}
    idx.parent.mkdir(exist_ok=True)
    idx.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    try:
        assert ok(env.client.get("/api/outputs", params={"case_id": env.case_id}),
                  "api/outputs_list.schema.json") == data
    finally:
        idx.unlink()


def test_n35_outputs_unknown_case(env):
    other = env.case_id[:-1] + ("0" if env.case_id[-1] != "0" else "1")   # 格式对、但没登记过
    fail(env.client.get("/api/outputs", params={"case_id": other}), "CASE_NOT_FOUND")


# ---------- T14 派修：存过正式草稿的任务不留 进行中.md ----------

def test_t14_in_progress_removed_after_formal_draft(env):
    tid = env.begin("sess-t14-progress")["task_id"]
    folder = env.task_dir(tid) / "草稿"
    ok(progress(env, tid, "写到一半"), "core/progress.schema.json")
    assert (folder / "进行中.md").exists()
    env.tool_ok(tid, "case_save_draft", {"title": "结论", "content": "正式"})
    assert not (folder / "进行中.md").exists()                 # 存正式草稿即清
    ok(progress(env, tid, "存完又回复了一句"), "core/progress.schema.json")
    assert (folder / "进行中.md").exists()
    assert ok(end(env, tid), "core/task_end.schema.json")["status"] == "completed"
    assert sorted(p.name for p in folder.iterdir()) == ["结论-v1.md"]   # 结束时再清，也不改名为 未完成-*

