"""case_save_draft、case_suggest_wiki。"""
from __future__ import annotations

import json
import re
from datetime import datetime

from .. import contracts
from ..case import gate
from ..errors import ApiError
from . import ToolContext

PENDING_REL = "工作区/wiki/待确认.json"
PENDING_SCHEMA = "files/wiki_pending.schema.json"


def empty_citation_check() -> dict:
    """出处核对由 T10 接入；本卡返回空结果（工单 T8 第 4 步）。"""
    return {"passed": True, "problems": [], "stats": {"citations": 0, "must_fix": 0, "hints": 0}}


def save_draft(ctx: ToolContext, a: dict) -> dict:
    title = a["title"].strip()
    if not title:
        raise ApiError("INVALID_ARGUMENT", "empty_title")
    tid = ctx.task["task_id"]
    drafts_rel = ctx.tasks.rel(tid, "草稿")
    folder = gate.resolve_internal(ctx.root, drafts_rel, op="save_draft")
    pat = re.compile(re.escape(title) + r"-v(\d+)\.md$")
    existing = [int(m.group(1)) for p in (folder.iterdir() if folder.is_dir() else []) if (m := pat.match(p.name))]
    version = max(existing, default=0) + 1
    rel = f"{drafts_rel}/{title}-v{version}.md"
    gate.write_bytes(ctx.root, rel, a["content"].encode("utf-8"), op="save_draft")  # 标题是设备名等：闸门拒绝
    check = empty_citation_check()
    cov = ctx.tasks.coverage(ctx.root, ctx.case_id, tid)
    res = ctx.tasks.result(ctx.root, tid)
    res["drafts"].append({"title": title, "path": rel, "version": version})
    res.update(citation_check=check, coverage=cov)
    ctx.tasks.save_result(ctx.root, res)
    not_fully = [p["name"] for p in cov["partially_read"]] + cov["not_read"]
    return {"path": rel, "version": version, "citation_check": check, "coverage": cov, "not_fully_read": not_fully}


def suggest_wiki(ctx: ToolContext, a: dict) -> dict:
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
