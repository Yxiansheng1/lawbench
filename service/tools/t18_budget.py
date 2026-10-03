r"""T18 预算实测的计量工具（联调工具，不是产品功能；不改 lawbench\ 产品代码；对日志和案件文件只读）。

用法（在 service\ 目录）：
    .venv\Scripts\python tools\t18_budget.py --case <案件根目录> [--case <另一个>] [--logs <appdata>\logs]
                                            [--since 2026-10-03T14:00] [--until 2026-10-03T18:00] [--out <目录>]
    .venv\Scripts\python tools\t18_budget.py --selftest      # 用造的最小样本自测（不需要服务、不需要服务器）

输出：<out>\budget-<时间>.md 与 .json（缺省 out = docs\plan\evidence\T18\）。

按任务单（task_id）汇总，每行一个任务：
  - 来源 1：案件 `工作区\任务\<task_id>\`：task.json（kind、skill、session_id、budget、created_at）、result.json（status、
    usage 里插件自报的 model_calls / tool_calls / elapsed_s、finished_at）；流水线任务另读 运行记录.json 的调用次数。
  - 来源 2：DSH 会话记录 `工作区\会话\**\session.v*.jsonl(.zstd)`：按 task.json 的 session_id 找到那份记录，取任务时间窗
    （created_at 到 finished_at，前后各放 5 秒）里的事件，**只读事件的 type、time 和 tool/call 的 name**，不读 arguments、
    消息正文：模型调用 = step/start 次数；工具调用 = tool/call，按工具名分列。
  - 来源 3（可选）：工作台服务日志 `service.log`（只有元数据）：同一时间窗里 core/tool、core/task_begin、core/task_end 的条数。
    日志里 core/tool 没有 task_id、多数也没有 case_id，只作旁证（同一时段只跑一个任务时才可比）。
  - 预算口径（F-RUN-05、Spec 9.2）：计入工具次数的是 case_* 工具里除 case_save_draft 以外的；skill、ask_user_question
    不计工具次数（各占一次模型调用）。超预算 = 实测超过 task.json 的 budget（model_calls / tool_calls / minutes）。
  - 对照：读 docs\plan\evidence\T18\skill-report.md 第一节各 Skill 的"预估：典型 / 大"两列，并列为"自报"。
"""
from __future__ import annotations

import argparse
import io
import json
import pathlib
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timedelta

SERVICE = pathlib.Path(__file__).resolve().parents[1]
REPO = SERVICE.parent
OUT = REPO / "docs" / "plan" / "evidence" / "T18"
REPORT = OUT / "skill-report.md"
SLACK = timedelta(seconds=5)
NOT_COUNTED = {"case_save_draft"}                    # Spec 9.2：保存草稿不计入工具调用
NOT_TOOLS = {"skill", "ask_user_question"}           # DSH 的这两个不计工具次数


def parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.astimezone()


def ms_time(ms: int | float) -> datetime:
    return datetime.fromtimestamp(ms / 1000).astimezone()


# ---------------------------------------------------------------- 会话记录

def read_lines(p: pathlib.Path) -> list[str]:
    raw = p.read_bytes()
    if p.name.endswith(".zstd"):
        try:
            import zstandard
        except ImportError:
            raise RuntimeError("会话记录是 zstd 压缩的，本机没装 zstandard（pip install zstandard 后重跑）") from None
        # DSH 每次 flush 追加一个 zstd 帧：要跨帧读完（decompressobj 只解第一帧，T18 实测踩到）
        with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw), read_across_frames=True) as r:
            raw = r.read()
    return raw.decode("utf-8", "replace").splitlines()


def load_sessions(case_root: pathlib.Path) -> tuple[dict[str, list[dict]], list[str]]:
    """{session_id: [{type, time, name?}]}，只留计量要的字段；另返回读不了的文件说明。"""
    out: dict[str, list[dict]] = {}
    problems: list[str] = []
    base = case_root / "工作区" / "会话"
    if not base.is_dir():
        return out, problems
    for p in sorted(base.rglob("session*.jsonl*")):
        try:
            lines = read_lines(p)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{p.relative_to(case_root)}：{e}")
            continue
        sid, events = None, []
        for ln in lines:
            if not ln.strip():
                continue
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            if rec.get("type") == "session":
                sid = rec.get("id")
                continue
            ev = {"type": rec.get("type"), "time": rec.get("time")}
            if ev["type"] == "tool/call":
                ev["name"] = (rec.get("data") or {}).get("name")          # 只取工具名，不碰 arguments
            events.append(ev)
        if sid:
            out.setdefault(sid, []).extend(events)
    return out, problems


# ---------------------------------------------------------------- 服务日志

def load_log(logs: pathlib.Path | None) -> list[dict]:
    if not logs:
        return []
    recs = []
    for p in sorted(logs.glob("service.log*")):
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("module") == "core":
                recs.append({"op": r.get("op"), "t": parse_time(r.get("t")), "case_id": r.get("case_id")})
    return recs


# ---------------------------------------------------------------- 自报（skill-report）

def load_claims(report: pathlib.Path = REPORT) -> dict[str, dict]:
    claims: dict[str, dict] = {}
    if not report.is_file():
        return claims
    rows = [ln for ln in report.read_text(encoding="utf-8").splitlines() if ln.startswith("| ")]
    head = None
    for ln in rows:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if cells and cells[0] == "Skill":
            head = cells
            continue
        if head and len(cells) == len(head) and not set(cells[0]) <= set("-: "):
            row = dict(zip(head, cells))
            name = re.sub(r"[（(].*", "", row["Skill"]).strip()
            claims[name] = {"典型": row.get("预估：典型", ""), "大": row.get("预估：大", ""),
                            "是否够": row.get("预算是否够（F-RUN-05：模型 8 / 工具 24）", "")}
    return claims


# ---------------------------------------------------------------- 汇总

def collect(case_roots: list[pathlib.Path], logs: pathlib.Path | None, since: datetime | None,
            until: datetime | None) -> dict:
    sessions_all: dict[str, list[dict]] = {}
    notes: list[str] = []
    rows = []
    log = load_log(logs)
    for root in case_roots:
        sessions, problems = load_sessions(root)
        sessions_all.update(sessions)
        notes += problems
        tdir = root / "工作区" / "任务"
        if not tdir.is_dir():
            notes.append(f"{root.name}：没有 工作区\\任务")
            continue
        for d in sorted(p for p in tdir.iterdir() if p.is_dir()):
            try:
                task = json.loads((d / "task.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if task.get("state") == "pending":
                continue                                          # 任务单（选择）本身，不是一次执行
            start = parse_time(task.get("created_at"))
            if (since and start and start < since) or (until and start and start > until):
                continue
            res = {}
            if (d / "result.json").is_file():
                res = json.loads((d / "result.json").read_text(encoding="utf-8"))
            end = parse_time(res.get("finished_at"))
            usage = res.get("usage") or {}
            budget = task.get("budget") or {}
            row = {"task_id": task["task_id"], "case": root.name, "kind": task.get("kind"),
                   "skill": task.get("skill") or task.get("step"), "status": res.get("status"),
                   "start": start.isoformat(timespec="seconds") if start else None,
                   "end": end.isoformat(timespec="seconds") if end else None,
                   "minutes": round((end - start).total_seconds() / 60, 1) if start and end else None,
                   "budget": budget, "self_reported": {"model_calls": usage.get("model_calls"),
                                                       "tool_calls": usage.get("tool_calls"),
                                                       "elapsed_s": usage.get("elapsed_s")}}
            if task.get("kind") == "pipeline":
                rec = d / "运行记录.json"
                if rec.is_file():
                    r = json.loads(rec.read_text(encoding="utf-8"))
                    row["measured"] = {"model_calls": r.get("模型调用次数"), "tools": {}, "tool_calls": None,
                                       "source": "运行记录.json"}
            else:
                evs = sessions.get(task.get("session_id") or "", [])
                lo = (start - SLACK) if start else None
                hi = (end + SLACK) if end else None
                win = [e for e in evs if e.get("time") is not None
                       and (lo is None or ms_time(e["time"]) >= lo) and (hi is None or ms_time(e["time"]) <= hi)]
                if not evs:
                    row["measured"] = {"model_calls": None, "tools": {}, "tool_calls": None,
                                       "source": "无会话记录（不经 DSH 的调用，如联调脚本）"}
                else:
                    tools = Counter(e["name"] for e in win if e["type"] == "tool/call" and e.get("name"))
                    counted = sum(n for name, n in tools.items()
                                  if name not in NOT_COUNTED and name not in NOT_TOOLS)
                    row["measured"] = {"model_calls": sum(1 for e in win if e["type"] == "step/start"),
                                       "tools": dict(sorted(tools.items())), "tool_calls": counted,
                                       "source": "DSH 会话记录"}
                    times = [ms_time(e["time"]) for e in win]
                    if times and row["minutes"] is None:
                        row["minutes"] = round((max(times) - min(times)).total_seconds() / 60, 1)
            if log and start:
                lo, hi = start - SLACK, (end or start) + SLACK
                inwin = [r for r in log if r["t"] and lo <= r["t"] <= hi]
                row["service_log"] = dict(Counter(r["op"] for r in inwin))
            m = row.get("measured") or {}
            over = []
            if m.get("model_calls") is not None and budget.get("model_calls") and m["model_calls"] > budget["model_calls"]:
                over.append("模型")
            if m.get("tool_calls") is not None and budget.get("tool_calls") and m["tool_calls"] > budget["tool_calls"]:
                over.append("工具")
            if row["minutes"] is not None and budget.get("minutes") and row["minutes"] > budget["minutes"]:
                over.append("时间")
            row["over_budget"] = over
            rows.append(row)
    return {"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "cases": [str(p.name) for p in case_roots], "window": {"since": since and since.isoformat(),
                                                                  "until": until and until.isoformat()},
            "rows": rows, "notes": notes}


def to_markdown(data: dict, claims: dict[str, dict]) -> str:
    def n(x):
        return "—" if x is None else str(x)
    out = [f"# T18 预算实测（{data['generated_at']}）", "",
           f"案件：{'、'.join(data['cases'])}；时间窗：{data['window']['since'] or '不限'} 至 {data['window']['until'] or '不限'}",
           "口径：模型 = 会话里 step/start 次数（流水线取 运行记录.json）；工具 = case_* 里除 case_save_draft 外的调用"
           "（skill、ask_user_question 不计）；超预算按 task.json 的 budget 判。", "",
           "| 任务 | 类型 | Skill | 状态 | 模型 实测 / 自报 / 上限 | 工具 实测 / 自报 / 上限 | 分钟 / 上限 | 超预算 | 工具分列 | 服务日志 core | 自报（skill-report 预估：典型 ‖ 大） |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in data["rows"]:
        m, s, b = r.get("measured") or {}, r["self_reported"], r["budget"]
        tools = "、".join(f"{k}×{v}" for k, v in (m.get("tools") or {}).items()) or "—"
        log = "、".join(f"{k}×{v}" for k, v in (r.get("service_log") or {}).items()) or "—"
        c = claims.get(r["skill"] or "", {})
        claim = f"{c.get('典型', '—')} ‖ {c.get('大', '—')}" if c else "—"
        out.append(f"| {r['task_id']} | {r['kind']} | {n(r['skill'])} | {n(r['status'])} | "
                   f"{n(m.get('model_calls'))} / {n(s['model_calls'])} / {n(b.get('model_calls'))} | "
                   f"{n(m.get('tool_calls'))} / {n(s['tool_calls'])} / {n(b.get('tool_calls'))} | "
                   f"{n(r['minutes'])} / {n(b.get('minutes'))} | {'、'.join(r['over_budget']) or '否'} | {tools} | {log} | {claim} |")
    if data["notes"]:
        out += ["", "说明："] + [f"- {x}" for x in data["notes"]]
    srcs = sorted({(r.get('measured') or {}).get('source') for r in data["rows"]} - {None})
    if srcs:
        out += ["", "实测来源：" + "；".join(srcs)]
    return "\n".join(out) + "\n"


def write(data: dict, out: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    md, js = out / f"budget-{stamp}.md", out / f"budget-{stamp}.json"
    md.write_text(to_markdown(data, load_claims()), encoding="utf-8")
    js.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return md, js


# ---------------------------------------------------------------- 自测

def selftest() -> int:
    """造一个最小案件：一个 Agent 任务（带会话记录）、一个任务单、一个流水线任务，外加一份服务日志；核对汇总。"""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lbt18-"))
    root = tmp / "案件甲"
    t0 = datetime(2026, 10, 3, 14, 0, 0).astimezone()
    ms = lambda dt: int(dt.timestamp() * 1000)  # noqa: E731

    def put(rel, obj):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj, encoding="utf-8")

    budget = {"model_calls": 8, "tool_calls": 24, "minutes": 45}
    put("工作区/任务/T-1/task.json", {"task_id": "T-1", "kind": "agent", "session_id": "s-1", "skill": "criminal-reading-notes",
                                   "budget": budget, "state": "finished", "created_at": t0.isoformat()})
    put("工作区/任务/T-1/result.json", {"status": "completed", "usage": {"model_calls": 4, "tool_calls": 3, "elapsed_s": 120},
                                     "finished_at": (t0 + timedelta(minutes=2)).isoformat()})
    put("工作区/任务/T-0/task.json", {"task_id": "T-0", "kind": "agent", "session_id": "s-1", "skill": "criminal-reading-notes",
                                   "budget": budget, "state": "pending", "created_at": t0.isoformat()})
    put("工作区/任务/P-1/task.json", {"task_id": "P-1", "kind": "pipeline", "step": "wiki_build", "skill": "case-wiki-build",
                                   "budget": {"model_calls": 79, "tool_calls": 1, "minutes": 45}, "state": "finished",
                                   "created_at": (t0 + timedelta(minutes=10)).isoformat()})
    put("工作区/任务/P-1/result.json", {"status": "completed", "usage": {"model_calls": 30, "tool_calls": 0, "elapsed_s": 149},
                                     "finished_at": (t0 + timedelta(minutes=12, seconds=29)).isoformat()})
    put("工作区/任务/P-1/运行记录.json", {"模型调用次数": 30})
    ev = [{"type": "session", "version": 4, "id": "s-1", "createdAt": ms(t0), "isSeeded": False, "delegationDepth": 0}]
    seq = [("step/start", 1), ("tool/call", 2, "skill"), ("step/start", 5), ("tool/call", 6, "ask_user_question"),
           ("step/start", 20), ("tool/call", 21, "case_list_materials"), ("tool/call", 21, "case_read_material"),
           ("tool/call", 22, "case_read_material"), ("step/start", 60), ("tool/call", 61, "case_save_draft"),
           ("step/start", 90)]
    for item in seq:
        e = {"type": item[0], "time": ms(t0 + timedelta(seconds=item[1])), "data": {"turn": 1, "step": 0}}
        if item[0] == "tool/call":
            e["data"].update(callId=f"c{item[1]}", name=item[2], arguments='{"query":"不该被读到的检索词"}')
        ev.append(e)
    ev.append({"type": "step/start", "time": ms(t0 + timedelta(minutes=30)), "data": {}})   # 时间窗外：另一轮
    put("工作区/会话/proj/s-1/session.v4.jsonl", "\n".join(json.dumps(e, ensure_ascii=False) for e in ev))
    logs = tmp / "logs"
    logs.mkdir()
    lines = [{"t": (t0 + timedelta(seconds=s)).isoformat(), "module": "core", "op": op, "status": "ok"}
             for s, op in [(0, "task_begin"), (21, "tool"), (21, "tool"), (22, "tool"), (61, "tool"), (120, "task_end")]]
    (logs / "service.log").write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")

    data = collect([root], logs, None, None)
    by = {r["task_id"]: r for r in data["rows"]}
    checks = [
        ("任务单（pending）不计", set(by) == {"T-1", "P-1"}),
        ("模型调用 = 时间窗内 step/start", by["T-1"]["measured"]["model_calls"] == 5),
        ("工具分列", by["T-1"]["measured"]["tools"] == {"ask_user_question": 1, "case_list_materials": 1,
                                                    "case_read_material": 2, "case_save_draft": 1, "skill": 1}),
        ("计入预算的工具不含 save_draft、skill、ask_user_question", by["T-1"]["measured"]["tool_calls"] == 3),
        ("流水线取运行记录", by["P-1"]["measured"]["model_calls"] == 30),
        ("分钟", by["T-1"]["minutes"] == 2.0 and by["P-1"]["minutes"] == 2.5),
        ("没超预算", by["T-1"]["over_budget"] == [] and by["P-1"]["over_budget"] == []),
        ("服务日志旁证", by["T-1"]["service_log"] == {"task_begin": 1, "tool": 4, "task_end": 1}),
        ("自报列读得到", "criminal-reading-notes" in load_claims()),
        ("不读 arguments", "不该被读到的检索词" not in json.dumps(data, ensure_ascii=False)),
    ]
    budget2 = dict(budget, model_calls=4)
    t1 = json.loads((root / "工作区/任务/T-1/task.json").read_text(encoding="utf-8"))
    t1["budget"] = budget2
    put("工作区/任务/T-1/task.json", t1)
    over = {r["task_id"]: r["over_budget"] for r in collect([root], None, None, None)["rows"]}
    checks.append(("超预算判得出（实测 5 次 > 上限 4）", over["T-1"] == ["模型"] and over["P-1"] == []))
    md = to_markdown(data, load_claims())
    checks.append(("Markdown 表头与行", md.count("\n| T-1 |") == 1 and "| P-1 |" in md))
    bad = [name for name, okk in checks if not okk]
    for name, okk in checks:
        print(("✔ " if okk else "✘ ") + name)
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print("自测：" + ("通过" if not bad else f"不通过（{bad}）"))
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", action="append", type=pathlib.Path, default=[])
    ap.add_argument("--logs", type=pathlib.Path)
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--out", type=pathlib.Path, default=OUT)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.case:
        ap.error("至少给一个 --case")
    data = collect(a.case, a.logs, parse_time(a.since), parse_time(a.until))
    md, js = write(data, a.out)
    print(f"{len(data['rows'])} 个任务；写入 {md} 与 {js.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
