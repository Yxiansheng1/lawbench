"""case_search（Spec 第 11 节；工单 T9）：全文检索，实现在 search/fts.py。参数和返回同契约 tools/case_search。"""
from __future__ import annotations

from ..search import fts
from . import ToolContext


def search(ctx: ToolContext, a: dict) -> dict:
    return fts.search(ctx.root, ctx.case_id, ctx.index(), a["query"], a.get("max_hits", 20))
