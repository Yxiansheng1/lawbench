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
                                                                 "--batch", "九月"]       # reprint 不带 --apply
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
    assert "attach" in argv_of(make_runner(tmp_path), {"action": "reprint", "batch": "attach"})


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
    r = make_runner(tmp_path)
    for code, out, expect in [(0, "ok", (0, False)), (2, "重复 1 张", (2, True)),
                              (2, "[BLOCKED] ValueError 收集任务有待处理", "ENGINE_FAILED"),
                              (1, "[FATAL] x", "ENGINE_FAILED"), (3, "", "ENGINE_FAILED")]:
        monkeypatch.setattr(r, "_exec", lambda argv, c=code, o=out: (c, o))
        if expect == "ENGINE_FAILED":
            with pytest.raises(ApiError) as e:
                r.run({"action": "report"})
            assert e.value.code == "ENGINE_FAILED"
        else:
            v = r.run({"action": "report"})
            assert (v["exit_code"], v["attention"]) == expect and v["output"] == out


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
    step("reimburse", {"action": "reimburse", "batch": "2026-09_九月", "apply": True})
    step("report", {"action": "report"})
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


def test_prepare_blocked_while_items_pending_is_engine_failed(period):
    """有待核项时引擎 [BLOCKED] 退出 2：服务判 ENGINE_FAILED，不当"须看明细"（回写②）。"""
    _, res = period
    assert isinstance(res["prepare_blocked"], ApiError) and res["prepare_blocked"].code == "ENGINE_FAILED"


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
    for s in ("prepare", "reimburse_preview", "reimburse", "report"):
        assert not isinstance(res[s], ApiError), (s, getattr(res[s], "reason", None))
    assert '"processing_complete": true' in res["analyze2"]["output"]
    assert any(f.endswith("贴票清单.html") for f in res["prepare"]["files"])
    import openpyxl
    wb = openpyxl.load_workbook(base / "office" / "发票台账" / "发票主台账.xlsx", read_only=True)
    rows = [r for ws in wb.worksheets for r in ws.iter_rows(values_only=True)]
    paid = {str(r[7]) for r in rows if r and len(r) > 8 and r[8] == "已报"}
    assert paid == {"26999000000000410002", "26999000000000410003"}


def test_logs_have_no_invoice_details(period, tmp_path):
    """日志只有动作名、退出码、耗时：票号、金额、购买方名称都不出现。"""
    from lawbench import logs
    log_dir = logs.setup(tmp_path)
    r = R.InvoiceRunner(FakeSettings(str(period[0] / "office")), period[0] / "ad")
    r.run({"action": "report"})
    logs.close()
    text = (log_dir / "service.log").read_text(encoding="utf-8")
    assert '"module": "invoice"' in text and '"op": "report"' in text
    for s in SECRETS:
        assert s not in text


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
    fail(client.post("/api/invoice/run", json={"action": "report"}), "invoice_run", "ENGINE_FAILED")
