"""case_archive_match、case_save_archive_plan（Spec 12.4；契约 tools/case_archive_match、tools/case_save_archive_plan）。"""
from __future__ import annotations

import json

from .. import contracts, logs
from ..archive import match as am
from ..case import gate
from . import ToolContext

PLAN_NAME = "归档方案.json"


def archive_match(ctx: ToolContext, a: dict) -> dict:
    catalog = am.load_catalog(ctx.skills_dirs, a["catalog"])
    return am.match(ctx.root, ctx.index(), catalog)


def save_archive_plan(ctx: ToolContext, a: dict) -> dict:
    """按契约校验（/core/tool 已校验 args）、按目录核编号和材料名后写 工作区/任务/<任务>/归档方案.json；
    算出缺失的必交项。办案结果、金助理编号、承办律师没填的给提醒（办案结果为空时生成会被拒绝）。"""
    catalog = am.load_catalog(ctx.skills_dirs, a["catalog"])
    missing, warnings = am.check_plan(catalog, a, ctx.index(), ctx.root)
    if a["result"] is None:
        warnings.append("办案结果未确认：生成归档文件前须由律师在归档面板确认")
    if a["jzl_no"] is None:
        warnings.append("金助理系统案件编号未填：立卷申请书和情况说明里会留【待填写】")
    if a["lawyer"] is None and not ctx.tasks.settings.get()["profile"].get("lawyer_name"):
        warnings.append("承办律师未填，设置里也没有本机律师姓名：结案报告里会留【待填写】")
    contracts.validate("tools/case_save_archive_plan.schema.json", "#/$defs/plan", a)
    rel = ctx.tasks.rel(ctx.task["task_id"], PLAN_NAME)
    gate.write_bytes(ctx.root, rel, json.dumps(a, ensure_ascii=False, indent=2).encode("utf-8"), op="archive_plan")
    logs.event("archive", "plan", case_id=ctx.case_id)
    return {"path": rel, "missing_required": missing, "warnings": warnings}
