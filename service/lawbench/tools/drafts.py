"""case_save_draft、case_suggest_wiki。"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime

from .. import checks, contracts, logs
from ..case import gate
from ..errors import ApiError
from . import ToolContext

PENDING_REL = "工作区/wiki/待确认.json"
PENDING_SCHEMA = "files/wiki_pending.schema.json"
_WIKI_LOCK = threading.Lock()  # 待确认.json 的读-改-写（P2-3）；只是本地读写，跨案件共用一把也不会久等


def citation_check(ctx: ToolContext, content: str) -> tuple[dict, list[dict]]:
    """出处核对（T10）：按任务 Skill 的 kind 区分 G 类；不查 D 类（裁决 1）。日志只记元数据。"""
    t0 = time.monotonic()
    kind = checks.skill_kind(ctx.skills_dirs, ctx.task.get("skill"))
    check, cites = checks.check_text(content, checks.MaterialSet.from_case(ctx.root, ctx.index()), kind)
    logs.event("checks", "draft", case_id=ctx.case_id, duration_ms=(time.monotonic() - t0) * 1000)
    return check, cites


def merge_citations(old: list[dict], new: list[dict]) -> list[dict]:
    """本任务全部草稿的出处，按（材料编号、位置）去重（裁决 6）。"""
    seen = {(c["material_id"], json.dumps(c["loc"], sort_keys=True)) for c in old}
    out = list(old)
    for c in new:
        key = (c["material_id"], json.dumps(c["loc"], sort_keys=True))
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def save_draft(ctx: ToolContext, a: dict) -> dict:
    title = a["title"].strip()
    if not title:
        raise ApiError("INVALID_ARGUMENT", "empty_title")
    tid = ctx.task["task_id"]
    drafts_rel = ctx.tasks.rel(tid, "草稿")
    # 取版本号、写文件、改 result.json 都在这个任务的锁里（P1-3、P2-2）；
    # 匹配已有版本不分大小写：NTFS 上 Report-v1.md 和 report-v1.md 是同一个文件
    with ctx.tasks.task_lock(tid):
        # 在任务锁里再核一次状态：/core/tool 在锁外查过，这之间 end 可能已经插进来（F2）
        if ctx.tasks.locate(tid)[2]["state"] != "running":
            raise ApiError("TASK_NOT_FOUND", "not_running")
        folder = gate.resolve_internal(ctx.root, drafts_rel, op="save_draft")
        pat = re.compile(re.escape(title.casefold()) + r"-v(\d+)\.md$")
        existing = [int(m.group(1)) for p in (folder.iterdir() if folder.is_dir() else [])
                    if (m := pat.match(p.name.casefold()))]
        version = max(existing, default=0) + 1
        rel = f"{drafts_rel}/{title}-v{version}.md"
        gate.write_bytes(ctx.root, rel, a["content"].encode("utf-8"), op="save_draft")  # 标题是设备名等：闸门拒绝
        check, cites = citation_check(ctx, a["content"])
        cov = ctx.tasks.coverage(ctx.root, ctx.case_id, tid)
        res = ctx.tasks.result(ctx.root, tid)
        res["drafts"].append({"title": title, "path": rel, "version": version})
        res.update(citation_check=check, coverage=cov, citations=merge_citations(res["citations"], cites))
        ctx.tasks.save_result(ctx.root, res)
    not_fully = [p["name"] for p in cov["partially_read"]] + cov["not_read"]
    return {"path": rel, "version": version, "citation_check": check, "coverage": cov, "not_fully_read": not_fully}


def suggest_wiki(ctx: ToolContext, a: dict) -> dict:
    with _WIKI_LOCK:
        return _suggest_wiki(ctx, a)


def _suggest_wiki(ctx: ToolContext, a: dict) -> dict:
    p = gate.resolve_internal(ctx.root, PENDING_REL, op="suggest_wiki")
    data = contracts.read_json(p) if p.is_file() else {"v": 1, "suggestions": []}
    contracts.validate(PENDING_SCHEMA, "", data)
    n = max((int(s["id"][1:]) for s in data["suggestions"]), default=0) + 1
    if n > 9999:
        raise ApiError("INVALID_ARGUMENT", "too_many_suggestions")
    sid = f"S{n:04d}"
    data["suggestions"].append({"id": sid, "field": a["field"], "value": a["value"], "source": a["source"],
                                "reason": a.get("reason"), "task_id": ctx.task["task_id"],
                                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                                "status": "pending"})
    contracts.validate(PENDING_SCHEMA, "", data)
    gate.write_bytes(ctx.root, PENDING_REL, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
                     op="suggest_wiki")
    return {"suggestion_id": sid}
