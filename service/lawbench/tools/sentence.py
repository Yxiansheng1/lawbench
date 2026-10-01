"""case_calc_sentence（Spec 13.4；工单 T24）：刑期计算，实现在 calc/sentence.py。参数和返回同契约 tools/case_calc_sentence。"""
from __future__ import annotations

from ..calc import sentence
from . import ToolContext


def calc_sentence(ctx: ToolContext, a: dict) -> dict:
    return sentence.calc(a)
