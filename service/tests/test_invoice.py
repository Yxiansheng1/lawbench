"""发票整理 /api/invoice/run（T25；Spec 13.3；契约 api/invoice_run.schema.json 1.3）。"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import shutil

import pytest

from lawbench.config import REPO_ROOT
from lawbench.errors import ApiError
from lawbench.invoice import runner as R

from test_api_case import fail, ok, req_valid

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "invoices-01"
BUYER = "某某虚构律师事务所"
# 虚构发票的票号、金额（fixtures README）：日志里一个都不能出现
SECRETS = ("26999000000000410001", "26999000000000410002", "26999000000000410003", "26999000000000410005",
           "356.00", "1280.00", "86.50", "1366.50", BUYER, "某某虚构科技有限公司")


class FakeSettings:
    def __init__(self, office: str | None, buyer: str | None = BUYER):
        self.data = {"office": {"dir": office, "invoice_buyer": buyer}}

    def get(self) -> dict:
        return copy.deepcopy(self.data)


def make_runner(tmp_path, office=True, **kw) -> R.InvoiceRunner:
    od = tmp_path / "日常办公"
    return R.InvoiceRunner(FakeSettings(str(od) if office else None), tmp_path / "ad", **kw)


def argv_of(r: R.InvoiceRunner, req: dict) -> list[str]:
    ledger = r._ledger_dir()
    req_valid("invoice_run", req)
    return r._argv(req["action"], req, ledger)[0]


# ---------------------------------------------------------------- 拼命令与白名单

ALL_REQUESTS = [
    {"action": "env_check"}, {"action": "report"}, {"action": "check_schema"},
    {"action": "history", "period": "2026-09"},
    {"action": "plan", "period": "2026-09", "channel": "local", "history": "exclude", "history_numbers": []},
    {"action": "plan", "period": "2026-09", "channel": "eml", "history": "selected",
     "history_numbers": ["26999000000000410002"], "start": "2026-08-01", "end": "2026-09-01"},
    {"action": "run", "period": "2026-09", "batch": "九月", "src": str(FIXTURES), "channel": "local"},
    {"action": "run", "period": "2026-09", "batch": "九月", "src": str(FIXTURES), "channel": "eml"},
    {"action": "analyze", "period": "2026-09"}, {"action": "import", "period": "2026-09"},
    {"action": "prepare", "period": "2026-09", "batch": "九月", "replace": True},
    {"action": "reprint", "batch": "九月"},
    {"action": "cancel", "batch": "九月", "apply": False},
    {"action": "reimburse", "batch": "九月", "apply": False},
    {"action": "reimburse", "batch": "九月", "apply": True},
    {"action": "review", "sha256": "a" * 64, "reviewer": "李律师", "confirm": True},
    {"action": "exclude", "period": "2026-09", "item": "b" * 64, "reason": "分类不出，人工排除", "reviewer": "李律师",
     "confirm": True},
]


@pytest.mark.parametrize("req", ALL_REQUESTS, ids=lambda q: q["action"] + "-" + str(q.get("channel", q.get("apply", ""))))
def test_every_action_builds_whitelisted_command(tmp_path, req):
    argv = argv_of(make_runner(tmp_path), req)
    assert argv[0] in R.SCRIPTS
    for bad in ("--download-links", "--imap-host", "--account", "--folder", "--img", "collect", "attach"):
        assert bad not in argv
    if "--channel" in argv:
        assert argv[argv.index("--channel") + 1] in ("local", "eml")


def test_command_details(tmp_path):
    r = make_runner(tmp_path)
    ledger = str(tmp_path / "日常办公" / "发票台账")
    job = str(tmp_path / "日常办公" / "发票台账" / "_任务" / "2026-09")
    assert argv_of(r, {"action": "env_check"}) == ["env_check.py", "--deep", "--ocr"]
    assert argv_of(r, {"action": "reprint", "batch": "九月"}) == ["workflow.py", "reprint", "--ledger", ledger,
                                                                 "--batch=九月"]          # reprint 不带 --apply
    assert argv_of(r, {"action": "cancel", "batch": "九月", "apply": False})[-1] == "--apply"  # 回写③：一律带
    assert "--apply" not in argv_of(r, {"action": "reimburse", "batch": "九月", "apply": False})
    run = argv_of(r, {"action": "run", "period": "2026-09", "batch": "九月", "src": str(FIXTURES), "channel": "eml"})
    assert run[run.index("--eml") + 1] == str(FIXTURES) and "--src" not in run
    assert run[run.index("--job") + 1] == job and run[run.index("--ledger") + 1] == ledger


def test_plan_history_numbers_written_to_file(tmp_path):
    r = make_runner(tmp_path)
    nums = ["26999000000000410002", "26999000000000410003"]
    argv = argv_of(r, {"action": "plan", "period": "2026-09", "channel": "local", "history": "selected",
                       "history_numbers": nums})
    f = pathlib.Path(argv[argv.index("--history-numbers") + 1])
    assert f.parent == tmp_path / "日常办公" / "发票台账" / "_任务" / "2026-09"
    assert json.loads(f.read_text(encoding="utf-8")) == nums
    assert "--history-numbers" not in argv_of(r, {"action": "plan", "period": "2026-09", "channel": "local",
                                                  "history": "exclude", "history_numbers": []})


@pytest.mark.parametrize("argv", [
    ["workflow.py", "run", "--job", "j", "--batch", "b", "--ledger", "l", "--src", "s", "--download-links"],
    ["workflow.py", "collect", "--job", "j", "--batch", "b", "--imap-host", "imap.qq.com"],
    ["workflow.py", "attach", "--job", "j", "--item", "x", "--file", "f"],
    ["workflow.py", "plan", "--job", "j", "--period", "2026-09", "--channel", "imap", "--history", "exclude"],
    ["workflow.py", "plan", "--job", "j", "--period", "2026-09", "--channel", "mcp", "--history", "exclude"],
    ["build_env_zip.py"], ["runtime_cache.py", "--repair"], [r"..\..\x.py"], ["C:\\x.py"],
    ["invoice_db.py", "import", "--src", "s", "--batch", "b", "--img"],
    ["env_check.py", "--quiet"],
])
def test_refused_commands(argv):
    """拒绝清单：联网相关的子命令、参数、渠道和白名单外的脚本都拼不出来（服务端再断言一次）。"""
    with pytest.raises(ApiError) as e:
        R.assert_allowed(argv)
    assert e.value.code == "INVALID_ARGUMENT"


def test_batch_value_named_like_subcommand_is_fine(tmp_path):
    """参数值不在拒绝范围：批次叫 attach 也照常（只挡子命令位置和参数名）。"""
    assert "--batch=attach" in argv_of(make_runner(tmp_path), {"action": "reprint", "batch": "attach"})


@pytest.mark.parametrize("body", [
    {"action": "plan", "period": "2026-09", "channel": "imap", "history": "exclude", "history_numbers": []},
    {"action": "plan", "period": "2026-09", "channel": "mcp", "history": "exclude", "history_numbers": []},
    {"action": "run", "period": "2026-09", "batch": "b", "src": "C:\\x", "channel": "local", "download_links": True},
    {"action": "attach"}, {"action": "collect"}, {"action": "exclude"},
    {"action": "run", "period": "2026-09", "batch": "../x", "src": "C:\\x", "channel": "local"},
    {"action": "plan", "period": "2026-09", "channel": "local", "history": "selected", "history_numbers": ["12345678"]},
    {"action": "plan", "period": "2026-09", "channel": "eml", "history": "exclude", "history_numbers": []},
    {"action": "plan", "period": "2026-09", "channel": "eml", "history": "exclude", "history_numbers": [],
     "start": "2026-08-01", "end": None},
])
def test_api_refuses_by_contract(client, body, tmp_path):
    """契约挡住的，以及契约放行但服务要再挡的（eml 缺起止日期，契约 1.3）。"""
    s = ok(client.get("/api/settings"), "settings")
    s["office"]["dir"] = str(tmp_path / "日常办公")
    ok(client.put("/api/settings", json=s), "settings")
    fail(client.post("/api/invoice/run", json=body), "invoice_run", "INVALID_ARGUMENT")


def test_env_only_whitelisted(tmp_path, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("LAWFIRM_KEY", "sk-should-not-pass")
    monkeypatch.setenv("PYTHONPATH", "C:\\evil")
    env = make_runner(tmp_path).env()
    assert set(env) <= set(R.PASS_ENV) | {"PYTHONUTF8", "INVOICE_BUYER", "INVOICE_RUNTIME_CACHE"}
    assert env["PYTHONUTF8"] == "1" and env["INVOICE_BUYER"] == BUYER
    assert env["INVOICE_RUNTIME_CACHE"] == str(tmp_path / "ad" / "ivc")
    r2 = R.InvoiceRunner(FakeSettings(str(tmp_path), buyer=None), tmp_path / "ad")
    assert "INVOICE_BUYER" not in r2.env()                        # 未设置时不传，引擎自己判"待核"


def test_child_process_sees_only_whitelisted_env(tmp_path, monkeypatch):
    """真起子进程：塞一个 LB_CANARY 和代理变量，子进程看不到（Spec 13.3 回写⑤）。"""
    eng = tmp_path / "eng"
    (eng / "scripts").mkdir(parents=True)
    (eng / "scripts" / "invoke.py").write_text(
        "import json, os\nprint(json.dumps(sorted(os.environ)))\n", encoding="utf-8")
    monkeypatch.setenv("LB_CANARY", "canary-should-not-pass")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")
    r = make_runner(tmp_path, engine_dir=eng)
    v = r.run({"action": "report"})
    seen = set(json.loads(v["output"]))
    assert "LB_CANARY" not in seen and "HTTPS_PROXY" not in seen
    # Windows 会给每个进程自动补几项（如 SystemRoot 的大小写变体），除此之外只有名单里的
    allowed = {k.upper() for k in (*R.PASS_ENV, "PYTHONUTF8", "INVOICE_BUYER", "INVOICE_RUNTIME_CACHE")}
    extra = {k for k in seen if k.upper() not in allowed}
    assert extra <= {"__PYVENV_LAUNCHER__"}, extra


def test_office_dir_not_set(client):
    fail(client.post("/api/invoice/run", json={"action": "report"}), "invoice_run", "OFFICE_DIR_NOT_SET")


def test_exit_code_mapping(tmp_path, monkeypatch):
    """契约 1.3：0 成功；2 且没有 [BLOCKED] 为 attention；引擎自己报失败（[BLOCKED] 或退出码不是 0/2）返回成功体
    failed=true、原因在 output（1128 令 A 项裁决）。"""
    r = make_runner(tmp_path)
    for code, out, attention, failed in [
            (0, "ok", False, False),
            (2, "重复 1 张", True, False),
            (2, "{...}\n[BLOCKED] ValueError 收集任务有待处理或数量不符项", False, True),
            (1, "[FATAL] x", False, True),
            (3, "", False, True)]:
        monkeypatch.setattr(r, "_exec", lambda argv, c=code, o=out: (c, o))
        v = r.run({"action": "report"})
        assert (v["exit_code"], v["attention"], v["failed"], v["output"]) == (code, attention, failed, out)


def test_engine_cannot_start_is_engine_failed(tmp_path):
    """服务自身故障（引擎起不来）仍走失败体 ENGINE_FAILED。"""
    r = make_runner(tmp_path, python=str(tmp_path / "没有这个解释器.exe"))
    with pytest.raises(ApiError) as e:
        r.run({"action": "report"})
    assert e.value.code == "ENGINE_FAILED" and e.value.reason == "spawn"


def test_timeout_kills_engine_tree(tmp_path, monkeypatch):
    """超时：连同子进程一起结束，返回 ENGINE_FAILED。用一个会起子进程并一直睡的假引擎。"""
    eng = tmp_path / "eng"
    (eng / "scripts").mkdir(parents=True)
    pidfile = tmp_path / "child.pid"
    (eng / "scripts" / "invoke.py").write_text(
        "import subprocess, sys, time\n"
        f"c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f"open(r'{pidfile}', 'w').write(str(c.pid))\n"
        "time.sleep(120)\n", encoding="utf-8")
    r = make_runner(tmp_path, engine_dir=eng, timeout_s=3)
    with pytest.raises(ApiError) as e:
        r.run({"action": "report"})
    assert e.value.code == "ENGINE_FAILED" and e.value.reason == "timeout"
    pid = int(pidfile.read_text())
    import subprocess
    alive = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    assert str(pid) not in alive


def test_one_action_at_a_time(tmp_path, monkeypatch):
    import threading
    import time
    r = make_runner(tmp_path)
    running, peak = [0], [0]

    def slow(argv):
        running[0] += 1
        peak[0] = max(peak[0], running[0])
        time.sleep(0.3)
        running[0] -= 1
        return 0, ""
    monkeypatch.setattr(r, "_exec", slow)
    ts = [threading.Thread(target=r.run, args=({"action": "report"},)) for _ in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert peak[0] == 1


# ---------------------------------------------------------------- 真引擎：一期（虚构样本）

def _ledger_bytes(ledger: pathlib.Path) -> dict[str, str]:
    """台账目录里除 _任务 以外每个文件的 sha256（主台账、_原票、_提取记录、_日志……）。"""
    import hashlib
    return {str(f.relative_to(ledger)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in ledger.rglob("*") if f.is_file() and "_任务" not in f.relative_to(ledger).parts}


def _pending_ids(csv_path: pathlib.Path) -> dict[str, str]:
    import csv
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        return {r["记录ID"]: r["文件或链接"] for r in csv.DictReader(f) if r["状态"] == "待核"}


@pytest.fixture(scope="module")
def period(tmp_path_factory):
    """真引擎走一期：plan → run → analyze →（exclude 待核两项）→ analyze → prepare → reimburse 预览 → --apply。
    缓存目录放短路径（回写①）。"""
    base = pathlib.Path(os.environ.get("TEMP", tmp_path_factory.getbasetemp())) / f"lbiv{os.getpid()}"
    shutil.rmtree(base, ignore_errors=True)
    (base / "src").mkdir(parents=True)
    for f in FIXTURES.iterdir():
        shutil.copy(f, base / "src")
    r = R.InvoiceRunner(FakeSettings(str(base / "office")), base / "ad")
    ledger = base / "office" / "发票台账"
    res: dict = {}
    from lawbench import logs
    res["log_dir"] = logs.setup(base / "logs")                       # 全程的服务日志（A-P2-3）

    def step(name, req):
        try:
            res[name] = r.run(req)
        except ApiError as e:
            res[name] = e

    step("plan", {"action": "plan", "period": "2026-09", "channel": "local", "history": "exclude", "history_numbers": []})
    step("run", {"action": "run", "period": "2026-09", "batch": "九月", "src": str(base / "src"), "channel": "local"})
    step("analyze", {"action": "analyze", "period": "2026-09"})
    step("prepare_blocked", {"action": "prepare", "period": "2026-09", "batch": "九月", "replace": False})
    csv_path = ledger / "_任务" / "2026-09" / "收集对账表.csv"
    res["pending"] = _pending_ids(csv_path)
    res["ledger_before_exclude"] = _ledger_bytes(ledger)
    for item in res["pending"]:
        step(f"exclude:{item}", {"action": "exclude", "period": "2026-09", "item": item,
                                 "reason": "分类不出，本期人工排除（测试）", "reviewer": "李律师", "confirm": True})
    res["ledger_after_exclude"] = _ledger_bytes(ledger)
    step("analyze2", {"action": "analyze", "period": "2026-09"})
    step("prepare", {"action": "prepare", "period": "2026-09", "batch": "九月", "replace": False})
    step("reimburse_preview", {"action": "reimburse", "batch": "2026-09_九月", "apply": False})
    step("reprint", {"action": "reprint", "batch": "2026-09_九月"})
    step("reimburse", {"action": "reimburse", "batch": "2026-09_九月", "apply": True})
    step("report", {"action": "report"})
    step("dash_batch", {"action": "reprint", "batch": "-x"})         # 以 - 开头的值不被当成参数
    logs.close()
    yield base, res
    shutil.rmtree("\\\\?\\" + str(base), ignore_errors=True)


def test_period_flags_duplicates_and_wrong_buyer(period):
    _, res = period
    assert res["plan"]["exit_code"] == 0
    for s in ("run", "analyze"):
        assert res[s]["exit_code"] == 2 and res[s]["attention"] is True
    csv = pathlib.Path(next(f for f in res["analyze"]["files"] if f.endswith("收集对账表.csv"))).read_text(encoding="utf-8")
    assert csv.count(",重复,") == 2                                  # zip 里的 02、03 与单张同票
    assert "发票05-购买方不符.pdf,抬头错误," in csv


def test_prepare_blocked_while_items_pending_is_failed(period):
    """有待核项时引擎 [BLOCKED] 退出 2：failed=true、attention=false，原因原样在 output（不当"须看明细"）。"""
    _, res = period
    v = res["prepare_blocked"]
    assert v["exit_code"] == 2 and v["failed"] is True and v["attention"] is False
    assert "[BLOCKED]" in v["output"] and "收集任务有待处理" in v["output"]


def test_exclude_only_touches_task_dir(period):
    """exclude：发票01 与它的重复 04 两项待核被排除；台账目录（主台账、_原票、_提取记录等）逐字节不变。"""
    _, res = period
    assert sorted(res["pending"].values()) == ["发票01-办公用品.pdf", "发票04-办公用品-重复.pdf"]
    for k, v in res.items():
        if k.startswith("exclude:"):
            assert not isinstance(v, ApiError) and v["exit_code"] == 0
    assert res["ledger_before_exclude"] and res["ledger_after_exclude"] == res["ledger_before_exclude"]


def test_full_period_reimburse(period):
    """排除后一期走完：处理完成、建批次、预览、确认已报；台账里本期已报的是 02、03 两张（1366.50 元）。"""
    base, res = period
    for s in ("prepare", "reimburse_preview", "reprint", "reimburse", "report"):
        assert not isinstance(res[s], ApiError) and res[s]["failed"] is False, (s, res[s])
    assert '"processing_complete": true' in res["analyze2"]["output"]
    import openpyxl
    wb = openpyxl.load_workbook(base / "office" / "发票台账" / "发票主台账.xlsx", read_only=True)
    rows = [r for ws in wb.worksheets for r in ws.iter_rows(values_only=True)]
    paid = {str(r[7]) for r in rows if r and len(r) > 8 and r[8] == "已报"}
    assert paid == {"26999000000000410002", "26999000000000410003"}


def test_logs_have_no_invoice_details(period):
    """一期全程（plan、run、analyze、exclude、prepare、reimburse、report……）的服务日志：每行只有固定字段，
    票号、金额、购买方名称、文件名都不出现（把引擎输出写进日志的变异会让它变红）。"""
    _, res = period
    text = (res["log_dir"] / "service.log").read_text(encoding="utf-8")
    rows = [json.loads(x) for x in text.splitlines() if x.strip()]
    ops = {r_["op"] for r_ in rows if r_["module"] == "invoice"}
    assert {"plan", "run", "analyze", "exclude", "prepare", "reimburse", "report"} <= ops
    for row in rows:
        assert set(row) <= {"t", "module", "op", "status", "case_id", "ms", "error"}, row
    for secret in (*SECRETS, "发票01", "办公用品", "收集任务有待处理"):
        assert secret not in text


def test_api_contract_roundtrip(client, tmp_path, monkeypatch):
    """经 HTTP 接口：请求和返回都过契约（用假引擎，快）。"""
    s = ok(client.get("/api/settings"), "settings")
    s["office"]["dir"] = str(tmp_path / "日常办公")
    s["office"]["invoice_buyer"] = BUYER
    ok(client.put("/api/settings", json=s), "settings")
    st = client.app.state.lb
    monkeypatch.setattr(st.invoice, "_exec", lambda argv: (2, "重复 1 张"))
    v = ok(client.post("/api/invoice/run", json={"action": "history", "period": "2026-09"}), "invoice_run")
    assert v["attention"] is True and v["exit_code"] == 2
    monkeypatch.setattr(st.invoice, "_exec", lambda argv: (2, "[BLOCKED] ValueError x"))
    v = ok(client.post("/api/invoice/run", json={"action": "report"}), "invoice_run")
    assert v["failed"] is True and v["attention"] is False and v["output"] == "[BLOCKED] ValueError x"
    monkeypatch.setattr(st.invoice, "_exec", lambda argv: (_ for _ in ()).throw(R.subprocess.TimeoutExpired("x", 1)))
    fail(client.post("/api/invoice/run", json={"action": "report"}), "invoice_run", "ENGINE_FAILED")   # 超时仍是失败体


# ---------------------------------------------------------------- N50：贴票清单另存一份

def test_buyer_copy_written_and_original_untouched(period):
    """设置有购买方：prepare 后同一文件夹多一份"贴票清单（购买方）.html"，不含写死的律所名；返回的 files 用它代替原文件；
    原文件哈希仍等于批次记录里的值，所以之后的 reprint、reimburse 照常（一期夹具里已跑过）。"""
    import hashlib
    base, res = period
    files = [pathlib.Path(f) for f in res["prepare"]["files"]]
    copy = [f for f in files if f.name == f"贴票清单（{BUYER}）.html"]
    assert len(copy) == 1 and not any(f.name == "贴票清单.html" for f in files)
    text = copy[0].read_text(encoding="utf-8")
    assert R.HARDCODED_BUYER not in text and f"购买方：{BUYER}" in text
    original = copy[0].parent / "贴票清单.html"
    assert R.HARDCODED_BUYER in original.read_text(encoding="utf-8")          # 原文件不动
    rec = json.loads((base / "office" / "发票台账" / "_报销批次" / "2026-09_九月.json").read_text(encoding="utf-8"))
    assert rec["artifacts"]["贴票清单.html"] == hashlib.sha256(original.read_bytes()).hexdigest()
    assert any(pathlib.Path(f).name == f"贴票清单（{BUYER}）.html" for f in res["reprint"]["files"])
    assert res["reimburse"]["failed"] is False                                 # check_artifacts 之后照常


def _fake_batch(tmp_path, html_text: str) -> tuple[pathlib.Path, pathlib.Path]:
    ledger = tmp_path / "日常办公" / "发票台账"
    folder = ledger / "_打印包" / "2026-09" / "2026-09_九月" / "v001"
    folder.mkdir(parents=True)
    (folder / "贴票清单.html").write_text(html_text, encoding="utf-8")
    (ledger / "_报销批次").mkdir(parents=True)
    (ledger / "_报销批次" / "2026-09_九月.json").write_text(json.dumps({"folder": str(folder)}), encoding="utf-8")
    return ledger, folder


@pytest.mark.parametrize("buyer,html_text,made", [
    (None, f"<p>购买方：{R.HARDCODED_BUYER}。</p>", False),                 # 设置为空：不生成
    ("", f"<p>购买方：{R.HARDCODED_BUYER}。</p>", False),
    (BUYER, "<p>购买方：别的写法。</p>", False),                              # 引擎输出里没有那一串：不报错、不生成
    ("A&B<律所>", f"<p>购买方：{R.HARDCODED_BUYER}。</p>", True),             # 有特殊字符：内容转义、文件名去非法字符
])
def test_buyer_copy_cases(tmp_path, buyer, html_text, made):
    ledger, folder = _fake_batch(tmp_path, html_text)
    r = R.InvoiceRunner(FakeSettings(str(tmp_path / "日常办公"), buyer=buyer), tmp_path / "ad")
    orig = str(folder / "贴票清单.html")
    out = r._with_buyer_copy(ledger, {"action": "reprint", "batch": "2026-09_九月"}, [orig])
    copies = [f for f in folder.iterdir() if f.name != "贴票清单.html"]
    assert (folder / "贴票清单.html").read_text(encoding="utf-8") == html_text
    if not made:
        assert out == [orig] and copies == []
    else:
        assert len(copies) == 1 and out == [str(copies[0])]
        assert "&lt;律所&gt;" in copies[0].read_text(encoding="utf-8") and "<" not in copies[0].name



# ---------------------------------------------------------------- T25 返修

def test_dash_leading_value_not_taken_as_option(period):
    """批次名以 - 开头：拼成 --batch=-x，引擎当值处理（报批次不存在），不是"用法错误"被当成须看明细。"""
    _, res = period
    v = res["dash_batch"]
    assert v["failed"] is True and v["attention"] is False
    assert "usage:" not in v["output"].lower() and "[BLOCKED]" in v["output"]


def test_free_text_values_use_equals_form(tmp_path):
    r = make_runner(tmp_path)
    ex = argv_of(r, {"action": "exclude", "period": "2026-09", "item": "b" * 64, "reason": "-理由", "reviewer": "-x",
                     "confirm": True})
    assert "--reason=-理由" in ex and "--reviewer=-x" in ex
    assert "--batch=-x" in argv_of(r, {"action": "reprint", "batch": "-x"})
    rv = argv_of(r, {"action": "review", "sha256": "a" * 64, "reviewer": "-y", "confirm": False})
    assert "--reviewer=-y" in rv


def test_busy_returns_engine_busy_without_starting_engine(tmp_path, monkeypatch):
    """前一个动作在跑：第二个请求等 2 秒后得 ENGINE_BUSY，且它的引擎根本没起（不排队执行不可逆动作，B-P2-1）。"""
    import threading
    import time
    r = make_runner(tmp_path)
    started, release = [], threading.Event()

    def slow(argv):
        started.append(argv[1] if len(argv) > 1 else argv[0])
        release.wait(20)
        return 0, ""
    monkeypatch.setattr(r, "_exec", slow)
    t = threading.Thread(target=r.run, args=({"action": "report"},))
    t.start()
    while not started:
        time.sleep(0.01)
    t0 = time.monotonic()
    with pytest.raises(ApiError) as e:
        r.run({"action": "cancel", "batch": "九月", "apply": True})
    waited = time.monotonic() - t0
    release.set()
    t.join()
    assert e.value.code == "ENGINE_BUSY" and 1.8 <= waited < 5
    assert started == ["report"]                                   # cancel 没有启动


def test_api_busy_contract(client, tmp_path, monkeypatch):
    import threading
    s = ok(client.get("/api/settings"), "settings")
    s["office"]["dir"] = str(tmp_path / "日常办公")
    ok(client.put("/api/settings", json=s), "settings")
    st = client.app.state.lb
    st.invoice._lock.acquire()
    try:
        fail(client.post("/api/invoice/run", json={"action": "report"}), "invoice_run", "ENGINE_BUSY")
    finally:
        st.invoice._lock.release()


def test_missing_entry_is_engine_failed_spawn(tmp_path):
    eng = tmp_path / "eng"
    (eng / "scripts").mkdir(parents=True)                            # 没有 invoke.py
    r = make_runner(tmp_path, engine_dir=eng)
    with pytest.raises(ApiError) as e:
        r.run({"action": "report"})
    assert e.value.code == "ENGINE_FAILED" and e.value.reason == "spawn"


@pytest.fixture(scope="module")
def period_clean(tmp_path_factory):
    """只有发票 02、03 的一期：没有待核项，run 一口气走到 prepare（A-P2-1）。"""
    base = pathlib.Path(os.environ.get("TEMP", tmp_path_factory.getbasetemp())) / f"lbiw{os.getpid()}"
    shutil.rmtree(base, ignore_errors=True)
    (base / "src").mkdir(parents=True)
    for name in ("发票02-差旅住宿.pdf", "发票03-交通.pdf"):
        shutil.copy(FIXTURES / name, base / "src")
    r = R.InvoiceRunner(FakeSettings(str(base / "office")), base / "ad")
    r.run({"action": "plan", "period": "2026-09", "channel": "local", "history": "exclude", "history_numbers": []})
    v = r.run({"action": "run", "period": "2026-09", "batch": "九月", "src": str(base / "src"), "channel": "local"})
    yield base, v
    shutil.rmtree("\\\\?\\" + str(base), ignore_errors=True)


def test_run_also_writes_buyer_copy(period_clean):
    base, v = period_clean
    assert v["failed"] is False and v["exit_code"] == 0, v["output"][-500:]
    names = [pathlib.Path(f).name for f in v["files"]]
    assert f"贴票清单（{BUYER}）.html" in names and "贴票清单.html" not in names
    copy = next(pathlib.Path(f) for f in v["files"] if pathlib.Path(f).name == f"贴票清单（{BUYER}）.html")
    assert R.HARDCODED_BUYER not in copy.read_text(encoding="utf-8")


def test_buyer_copy_write_failure_returns_original(tmp_path, monkeypatch):
    """副本的位置被同名目录占住：run 照常返回成功体，files 是原清单，记一条 buyer_copy 日志。"""
    from lawbench import logs
    ledger, folder = _fake_batch(tmp_path, f"<p>购买方：{R.HARDCODED_BUYER}。</p>")
    (folder / f"贴票清单（{BUYER}）.html").mkdir()
    r = R.InvoiceRunner(FakeSettings(str(tmp_path / "日常办公")), tmp_path / "ad")

    def fake_exec(argv):
        os.utime(folder / "贴票清单.html")                            # 让它算作本次改动的产出
        return 0, "ok"
    monkeypatch.setattr(r, "_exec", fake_exec)
    log_dir = logs.setup(tmp_path / "lg")
    v = r.run({"action": "run", "period": "2026-09", "batch": "九月", "src": str(FIXTURES), "channel": "local"})
    logs.close()
    assert v["failed"] is False and str(folder / "贴票清单.html") in v["files"]
    assert '"error": "buyer_copy"' in (log_dir / "service.log").read_text(encoding="utf-8")



def test_run_exit2_does_not_touch_same_name_old_batch(tmp_path, monkeypatch):
    """run 停在"须看明细"（退出 2，引擎没跑 prepare），同月已有同名已报销批次：files 里没有副本，
    旧批次文件夹逐字节不变（T25 第二轮复核 B-P3-1）。"""
    import hashlib
    ledger, folder = _fake_batch(tmp_path, f"<p>购买方：{R.HARDCODED_BUYER}。</p>")
    before = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in folder.iterdir()}
    r = R.InvoiceRunner(FakeSettings(str(tmp_path / "日常办公")), tmp_path / "ad")
    monkeypatch.setattr(r, "_exec", lambda argv: (2, '{"processing_complete": false}'))
    v = r.run({"action": "run", "period": "2026-09", "batch": "九月", "src": str(FIXTURES), "channel": "local"})
    assert (v["exit_code"], v["attention"], v["failed"]) == (2, True, False)
    assert not any("贴票清单" in pathlib.Path(f).name for f in v["files"])
    after = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in folder.iterdir()}
    assert after == before


def test_run_exit0_still_writes_copy(tmp_path, monkeypatch):
    """对照：同样的批次、run 退出 0（本次跑完了 prepare）时照常另存副本。"""
    ledger, folder = _fake_batch(tmp_path, f"<p>购买方：{R.HARDCODED_BUYER}。</p>")
    r = R.InvoiceRunner(FakeSettings(str(tmp_path / "日常办公")), tmp_path / "ad")

    def fake_exec(argv):
        os.utime(folder / "贴票清单.html")
        return 0, "ok"
    monkeypatch.setattr(r, "_exec", fake_exec)
    v = r.run({"action": "run", "period": "2026-09", "batch": "九月", "src": str(FIXTURES), "channel": "local"})
    assert pathlib.Path(v["files"][0]).name == f"贴票清单（{BUYER}）.html"
