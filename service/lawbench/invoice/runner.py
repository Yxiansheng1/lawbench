"""发票整理：按白名单调用发票引擎（Spec 13.3；契约 api/invoice_run.schema.json）。

- 引擎 engines/invoice-ledger 原样使用，入口 scripts/invoke.py。脚本名和参数全部由这里写死拼装，
  请求里的字段只作为参数值；绝不拼 --download-links、--imap-host、collect、attach（都要联网）。
- 台账目录 <日常办公文件夹>/发票台账，任务目录 发票台账/_任务/<报销年月>（formats.md 1.2）。
- 子进程环境清空，只传 Spec 13.3 名单里的变量（含 2026-09-30 回写的 INVOICE_RUNTIME_CACHE）。
- 同一时间只运行一个动作：后到的等锁最多 2 秒，超过返回 ENGINE_BUSY（不排队——排队中的不可逆动作会在律师
  放弃后照样执行，T25 复核 B-P2-1）；单个动作 30 分钟超时（连同引擎自己起的子进程一起结束）。
- 退出码 0 成功；2 且没有以 [BLOCKED] 开头的行为"须看明细"（attention）；引擎自己报失败（[BLOCKED] 或退出码
  不是 0/2）返回成功体 failed=true、原因在 output；引擎起不来、超时为 ENGINE_FAILED（契约 1.3）。
- 律师能填的自由文本（批次名、理由、核验人）一律拼成 --参数=值：以 - 开头的值也不会被引擎当成参数。
- 日志只记动作名、退出码、耗时；引擎输出只返回给界面，不写日志。
"""
from __future__ import annotations

import html
import json
import os
import re
import pathlib
import subprocess
import sys
import threading
import time
from datetime import datetime

from .. import logs, procs
from ..case import gate
from ..config import REPO_ROOT
from ..errors import ApiError

ENGINE_DIR = REPO_ROOT / "engines" / "invoice-ledger"
TIMEOUT_S = 30 * 60
BUSY_WAIT_S = 2.0
SCRIPTS = ("env_check.py", "workflow.py", "invoice_db.py")      # 只允许这三个脚本
# 每个脚本允许的子命令（env_check.py 没有子命令）；Spec 13.3 白名单
SUBCOMMANDS = {"workflow.py": ("history", "plan", "run", "analyze", "import", "prepare", "reprint", "cancel",
                               "reimburse", "review", "exclude"),
               "invoice_db.py": ("report", "check-schema")}
# 任何位置都不能出现的参数（Spec 13.3"不提供"；T25 调研绕过口子）。参数值（批次名等）不在此列
FORBIDDEN_FLAGS = ("--download-links", "--imap-host", "--account", "--folder", "--img")
PASS_ENV = ("SYSTEMROOT", "LOCALAPPDATA", "USERPROFILE", "TEMP", "TMP")
LEDGER_DIR_NAME = "发票台账"
# 这两个目录里新出现或改动的文件作为本次产出返回（贴票包、报销批次）
OUTPUT_DIRS = ("_打印包", "_报销批次")
# 引擎贴票清单里写死的购买方（engines/invoice-ledger/scripts/reimbursement.py:86）。换引擎版本时重新核对这一串
HARDCODED_BUYER = "广东连越（深圳）律师事务所"
LIST_NAME = "贴票清单.html"


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
        if not self._lock.acquire(timeout=BUSY_WAIT_S):           # 一次一个动作；后到的最多等 2 秒
            raise ApiError("ENGINE_BUSY", action)
        try:
            return self._run_locked(action, req, ledger)
        finally:
            self._lock.release()

    def _run_locked(self, action: str, req: dict, ledger: pathlib.Path) -> dict:
        t0 = time.monotonic()
        argv, files = self._argv(action, req, ledger)
        before = _snapshot(ledger)
        try:
            code, output = self._exec(argv)
        except subprocess.TimeoutExpired:                     # 服务自身故障：失败体
            logs.event("invoice", action, status="fail", duration_ms=(time.monotonic() - t0) * 1000,
                       error="timeout")
            raise ApiError("ENGINE_FAILED", "timeout")
        except OSError:                                       # 引擎起不来（解释器或入口缺失）
            logs.event("invoice", action, status="fail", duration_ms=(time.monotonic() - t0) * 1000,
                       error="spawn")
            raise ApiError("ENGINE_FAILED", "spawn")
        ms = (time.monotonic() - t0) * 1000
        blocked = any(line.startswith("[BLOCKED]") for line in output.splitlines())
        # 契约 1.3 failed：引擎自己报失败（[BLOCKED] 或退出码不是 0/2）→ 成功体 failed=true，原因在 output 给律师看
        failed = blocked or code not in (0, 2)
        attention = code == 2 and not failed
        logs.event("invoice", action, status="fail" if failed else "ok", duration_ms=ms,
                   error=None if code == 0 and not failed else
                   ("exit_2_blocked" if code == 2 and blocked else f"exit_{code}"))
        produced = [f for f in files if f.exists()] + _changed(ledger, before)
        paths = _unique([str(f) for f in produced])
        # run 只在退出码 0 时另存：退出 2（import 未处理完）时引擎不跑 prepare，按批次名找到的会是同名旧批次（T25 复核 B-P3-1）
        if not failed and (action in ("prepare", "reprint") or (action == "run" and code == 0)):
            paths = self._with_buyer_copy(ledger, req, paths)
        return {"exit_code": code, "attention": attention, "failed": failed, "output": output, "files": paths}

    # ---------------------------------------------------------------- N50：贴票清单另存一份（对引擎输出唯一的后处理）

    def _with_buyer_copy(self, ledger: pathlib.Path, req: dict, paths: list[str]) -> list[str]:
        """引擎贴票清单里写死了一家律所名（reimbursement.py:86）。原文件不能改：prepare 把打印包每个文件的
        sha256 记进批次记录，reprint / reimburse 前会核对（check_artifacts）。所以在同一文件夹另写
        `贴票清单（<购买方>）.html`，返回列表里用它代替原文件；设置里购买方为空、或清单里没有那一串时不生成。"""
        buyer = (self.settings.get()["office"].get("invoice_buyer") or "").strip()
        if not buyer:
            return paths
        # prepare 与 run（run 的最后一步就是 prepare）的批次名前面要加报销年月，与引擎一致；reprint 用律师给的全名
        batch = req["batch"] if req["action"] == "reprint" else scoped_batch(req["period"], req["batch"])
        try:
            rec = json.loads((ledger / "_报销批次" / f"{batch}.json").read_text(encoding="utf-8"))
            folder = ledger / rec["folder_relative"] if rec.get("folder_relative") else pathlib.Path(rec["folder"])
            src = folder / LIST_NAME
            text = src.read_text(encoding="utf-8")
        except (OSError, ValueError, KeyError):
            return paths
        if HARDCODED_BUYER not in text:
            return paths
        dst = folder / f"贴票清单（{_safe_name(buyer)}）.html"
        try:
            dst.write_text(text.replace(HARDCODED_BUYER, html.escape(buyer)), encoding="utf-8")
        except OSError:                                          # 写不了（如同名目录占着）：只记一条，照常返回原清单
            logs.event("invoice", req["action"], status="fail", error="buyer_copy")
            return paths
        out = [p for p in paths if pathlib.Path(p).name != LIST_NAME and p != str(dst)]
        return [str(dst)] + out

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
            if req["channel"] == "eml" and not (req.get("start") and req.get("end")):
                raise ApiError("INVALID_ARGUMENT", "eml_needs_dates")    # 契约 1.3：eml 时起止日期必填
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
            argv = ["workflow.py", "run", "--job", J, f"--batch={req['batch']}", "--ledger", L,
                    "--eml" if req["channel"] == "eml" else "--src", str(src)]
            files.append(pathlib.Path(J) / "收集对账表.csv")
        elif action in ("analyze", "import"):
            J = job(req["period"])
            argv = ["workflow.py", action, "--job", J, "--ledger", L]
            files.append(pathlib.Path(J) / "收集对账表.csv")
        elif action == "prepare":
            argv = ["workflow.py", "prepare", "--job", job(req["period"]), "--ledger", L, f"--batch={req['batch']}"]
            if req["replace"]:
                argv.append("--replace")
        elif action == "reprint":
            argv = ["workflow.py", "reprint", "--ledger", L, f"--batch={req['batch']}"]
        elif action == "cancel":
            # 引擎不支持取消预览：界面先用 report / reprint 展示批次内容再确认，这里一律带 --apply（Spec 13.3 回写③）
            argv = ["workflow.py", "cancel", "--ledger", L, f"--batch={req['batch']}", "--apply"]
        elif action == "reimburse":
            argv = ["workflow.py", "reimburse", "--ledger", L, f"--batch={req['batch']}"]
            if req["apply"]:
                argv.append("--apply")
        elif action == "exclude":
            # 契约 1.3：只改任务目录内的 collection.json 与对账表，不碰台账、不联网、不可逆；确认在界面做，一律带 --confirm
            J = job(req["period"])
            argv = ["workflow.py", "exclude", "--job", J, "--item", req["item"], f"--reason={req['reason']}",
                    f"--reviewer={req['reviewer']}", "--confirm"]
            files.append(pathlib.Path(J) / "收集对账表.csv")
        elif action == "review":
            argv = ["workflow.py", "review", "--ledger", L, "--sha256", req["sha256"], f"--reviewer={req['reviewer']}"]
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
        entry = self.engine_dir / "scripts" / "invoke.py"
        if not entry.is_file():                                  # 引擎入口缺失：按"起不来"处理
            raise FileNotFoundError(str(entry))
        cmd = [self.python, str(entry), *argv]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        p = subprocess.Popen(cmd, env=self.env(), cwd=str(self.engine_dir), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
        try:
            out, _ = p.communicate(timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            procs.kill_tree(p, drain=True)
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


def scoped_batch(period: str, batch: str) -> str:
    """与引擎 period_plan.scoped_batch 一致：prepare 的批次名前面加"<报销年月>_"。"""
    return batch if batch.startswith(period + "_") else f"{period}_{batch}"


def _safe_name(name: str) -> str:
    """购买方名称放进文件名：去掉 Windows 文件名不允许的字符。"""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")[:60] or "购买方"
