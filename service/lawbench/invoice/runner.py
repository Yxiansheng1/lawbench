"""发票整理：按白名单调用发票引擎（Spec 13.3；契约 api/invoice_run.schema.json）。

- 引擎 engines/invoice-ledger 原样使用，入口 scripts/invoke.py。脚本名和参数全部由这里写死拼装，
  请求里的字段只作为参数值；绝不拼 --download-links、--imap-host、collect、attach（都要联网）。
- 台账目录 <日常办公文件夹>/发票台账，任务目录 发票台账/_任务/<报销年月>（formats.md 1.2）。
- 子进程环境清空，只传 Spec 13.3 名单里的变量（含 2026-09-30 回写的 INVOICE_RUNTIME_CACHE）。
- 同一时间只运行一个动作；单个动作 30 分钟超时（连同引擎自己起的子进程一起结束）。
- 退出码 0 成功；2 且输出没有 [BLOCKED] 为"须看明细"（attention）；其余为 ENGINE_FAILED。
- 日志只记动作名、退出码、耗时；引擎输出只返回给界面，不写日志。
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import threading
import time
from datetime import datetime

from .. import logs
from ..case import gate
from ..config import REPO_ROOT
from ..errors import ApiError

ENGINE_DIR = REPO_ROOT / "engines" / "invoice-ledger"
TIMEOUT_S = 30 * 60
SCRIPTS = ("env_check.py", "workflow.py", "invoice_db.py")      # 只允许这三个脚本
# 每个脚本允许的子命令（env_check.py 没有子命令）；Spec 13.3 白名单
SUBCOMMANDS = {"workflow.py": ("history", "plan", "run", "analyze", "import", "prepare", "reprint", "cancel",
                               "reimburse", "review"),
               "invoice_db.py": ("report", "check-schema")}
# 任何位置都不能出现的参数（Spec 13.3"不提供"；T25 调研绕过口子）。参数值（批次名等）不在此列
FORBIDDEN_FLAGS = ("--download-links", "--imap-host", "--account", "--folder", "--img")
PASS_ENV = ("SYSTEMROOT", "LOCALAPPDATA", "USERPROFILE", "TEMP", "TMP")
LEDGER_DIR_NAME = "发票台账"
# 这两个目录里新出现或改动的文件作为本次产出返回（贴票包、报销批次）
OUTPUT_DIRS = ("_打印包", "_报销批次")


class InvoiceRunner:
    def __init__(self, settings, appdata: pathlib.Path, python: str | None = None,
                 engine_dir: pathlib.Path = ENGINE_DIR, timeout_s: float = TIMEOUT_S):
        self.settings = settings
        self.appdata = pathlib.Path(appdata)
        self.python = python or sys.executable
        self.engine_dir = pathlib.Path(engine_dir)
        self.timeout_s = timeout_s
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- 入口

    def run(self, req: dict) -> dict:
        ledger = self._ledger_dir()
        action = req["action"]
        with self._lock:                                          # 一次一个动作；后到的请求排队
            t0 = time.monotonic()
            argv, files = self._argv(action, req, ledger)
            before = _snapshot(ledger)
            try:
                code, output = self._exec(argv)
            except subprocess.TimeoutExpired:
                logs.event("invoice", action, status="fail", duration_ms=(time.monotonic() - t0) * 1000,
                           error="timeout")
                raise ApiError("ENGINE_FAILED", "timeout")
            ms = (time.monotonic() - t0) * 1000
            blocked = any(line.startswith("[BLOCKED]") for line in output.splitlines())
            if code == 0 or (code == 2 and not blocked):
                logs.event("invoice", action, duration_ms=ms, error=None if code == 0 else "exit_2")
                produced = [f for f in files if f.exists()] + _changed(ledger, before)
                return {"exit_code": code, "attention": code == 2, "output": output,
                        "files": _unique([str(f) for f in produced])}
            logs.event("invoice", action, status="fail", duration_ms=ms,
                       error="exit_2_blocked" if code == 2 else f"exit_{code}")
            raise ApiError("ENGINE_FAILED", "blocked" if code == 2 else "exit")

    # ---------------------------------------------------------------- 拼命令

    def _ledger_dir(self) -> pathlib.Path:
        office = self.settings.get()["office"]["dir"]
        if not office:
            raise ApiError("OFFICE_DIR_NOT_SET")
        gate.check_office_dir(office, op="invoice_run")          # 云同步目录再挡一次（设置可能是旧文件）
        ledger = pathlib.Path(office) / LEDGER_DIR_NAME
        ledger.mkdir(parents=True, exist_ok=True)
        return ledger

    def _argv(self, action: str, req: dict, ledger: pathlib.Path) -> tuple[list[str], list[pathlib.Path]]:
        """返回（引擎参数，本次要返回的已知产出文件）。参数值只来自契约已校验过的字段。"""
        L = str(ledger)
        files: list[pathlib.Path] = []

        def job(period: str) -> str:
            d = ledger / "_任务" / period
            d.mkdir(parents=True, exist_ok=True)
            return str(d)

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        if action == "env_check":
            argv = ["env_check.py", "--deep", "--ocr"]
        elif action in ("report", "check_schema"):
            argv = ["invoice_db.py", "report" if action == "report" else "check-schema", "--ledger", L]
        elif action == "history":
            out = pathlib.Path(job(req["period"])) / f"历史未报清单-{stamp}.json"
            argv = ["workflow.py", "history", "--ledger", L, "--out", str(out)]
            files.append(out)
        elif action == "plan":
            J = job(req["period"])
            argv = ["workflow.py", "plan", "--job", J, "--period", req["period"], "--channel", req["channel"],
                    "--history", req["history"]]
            if req.get("start") or req.get("end"):
                argv += ["--start", req.get("start") or "", "--end", req.get("end") or ""]
            if req["history_numbers"]:
                nf = pathlib.Path(J) / f"历史票号-{stamp}.json"     # 引擎要文件路径（Spec 13.3、T25 调研）
                nf.write_text(json.dumps(req["history_numbers"], ensure_ascii=False), encoding="utf-8")
                argv += ["--history-numbers", str(nf)]
            files.append(pathlib.Path(J) / "collection.json")
        elif action == "run":
            src = pathlib.Path(req["src"])
            if not src.is_absolute() or not src.exists():
                raise ApiError("INVALID_ARGUMENT", "src_missing")
            J = job(req["period"])
            argv = ["workflow.py", "run", "--job", J, "--batch", req["batch"], "--ledger", L,
                    "--eml" if req["channel"] == "eml" else "--src", str(src)]
            files.append(pathlib.Path(J) / "收集对账表.csv")
        elif action in ("analyze", "import"):
            J = job(req["period"])
            argv = ["workflow.py", action, "--job", J, "--ledger", L]
            files.append(pathlib.Path(J) / "收集对账表.csv")
        elif action == "prepare":
            argv = ["workflow.py", "prepare", "--job", job(req["period"]), "--ledger", L, "--batch", req["batch"]]
            if req["replace"]:
                argv.append("--replace")
        elif action == "reprint":
            argv = ["workflow.py", "reprint", "--ledger", L, "--batch", req["batch"]]
        elif action == "cancel":
            # 引擎不支持取消预览：界面先用 report / reprint 展示批次内容再确认，这里一律带 --apply（Spec 13.3 回写③）
            argv = ["workflow.py", "cancel", "--ledger", L, "--batch", req["batch"], "--apply"]
        elif action == "reimburse":
            argv = ["workflow.py", "reimburse", "--ledger", L, "--batch", req["batch"]]
            if req["apply"]:
                argv.append("--apply")
        elif action == "review":
            argv = ["workflow.py", "review", "--ledger", L, "--sha256", req["sha256"], "--reviewer", req["reviewer"]]
            if req["confirm"]:
                argv.append("--confirm")
        else:                                                       # 契约已挡住，这里再挡一次
            raise ApiError("INVALID_ARGUMENT", "action")
        assert_allowed(argv)
        return argv, files

    # ---------------------------------------------------------------- 执行

    def env(self) -> dict[str, str]:
        """子进程只拿名单里的变量（Spec 13.3）；不继承代理等其他变量。"""
        env = {k: os.environ[k] for k in PASS_ENV if os.environ.get(k)}
        env["PYTHONUTF8"] = "1"
        env["INVOICE_RUNTIME_CACHE"] = str(self.appdata / "ivc")    # 短路径，避免超过 259 字符（回写①）
        buyer = self.settings.get()["office"].get("invoice_buyer")
        if buyer:
            env["INVOICE_BUYER"] = buyer
        return env

    def _exec(self, argv: list[str]) -> tuple[int, str]:
        cmd = [self.python, str(self.engine_dir / "scripts" / "invoke.py"), *argv]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        p = subprocess.Popen(cmd, env=self.env(), cwd=str(self.engine_dir), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
        try:
            out, _ = p.communicate(timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            _kill_tree(p)
            raise
        return p.returncode, out.decode("utf-8", errors="replace")


def assert_allowed(argv: list[str]) -> None:
    """拼出来的命令再断言一次：脚本和子命令在白名单、没有联网相关的参数、渠道只有 local / eml。"""
    if not argv or argv[0] not in SCRIPTS:
        raise ApiError("INVALID_ARGUMENT", "script")
    if argv[0] in SUBCOMMANDS and (len(argv) < 2 or argv[1] not in SUBCOMMANDS[argv[0]]):
        raise ApiError("INVALID_ARGUMENT", "subcommand")
    if argv[0] == "env_check.py" and argv[1:] != ["--deep", "--ocr"]:
        raise ApiError("INVALID_ARGUMENT", "env_check_args")
    for a in argv:
        if a in FORBIDDEN_FLAGS:
            raise ApiError("INVALID_ARGUMENT", "forbidden_arg")
    if "--channel" in argv and argv[argv.index("--channel") + 1] not in ("local", "eml"):
        raise ApiError("INVALID_ARGUMENT", "channel")


def _kill_tree(p: subprocess.Popen) -> None:
    """引擎 invoke.py 会再起缓存里的 Python：连子进程一起结束。"""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        p.kill()
    try:
        p.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()


def _snapshot(ledger: pathlib.Path) -> dict[str, float]:
    snap: dict[str, float] = {}
    for name in OUTPUT_DIRS:
        root = ledger / name
        if root.is_dir():
            for f in root.rglob("*"):
                if f.is_file():
                    snap[str(f)] = f.stat().st_mtime
    return snap


def _changed(ledger: pathlib.Path, before: dict[str, float]) -> list[pathlib.Path]:
    after = _snapshot(ledger)
    return sorted(pathlib.Path(f) for f, m in after.items() if before.get(f) != m)


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    return [x for x in items if not (x in seen or seen.add(x))]
