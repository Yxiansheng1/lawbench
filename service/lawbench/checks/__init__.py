"""出处核对（Spec 9.4；工单 T10）：parse 解析出处与定位材料位置，citations 核金额日期与七类问题，evidence 核引语。

成果类型 kind 读任务所用 Skill 的 SKILL.md 头部（excerpt / analysis / draft）；读不到按 analysis（裁决 6）。
"""
from __future__ import annotations

import pathlib
import re

from .citations import KINDS, check_text
from .parse import MaterialSet

_KIND = re.compile(r"""^kind:\s*(["']?)([a-z]+)\1\s*$""", re.M)

__all__ = ["KINDS", "MaterialSet", "check_text", "skill_kind"]


def skill_kind(skills_dirs, skill: str | None) -> str:
    if not skill or not re.fullmatch(r"[A-Za-z0-9_-]+", skill):
        return "analysis"
    # Spec 10.1：两处目录同名时后者（管理员下发）覆盖前者（安装目录），所以倒着找（复核 P3-4）
    for d in reversed(list(skills_dirs or ())):
        p = pathlib.Path(d) / skill / "SKILL.md"
        try:
            text = p.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")   # \u4e0d\u662f UTF-8 \u4e5f\u4e0d\u629b
        except OSError:
            continue
        head = text.split("---", 2)[1] if text.startswith("---") and text.count("---") >= 2 else ""
        m = _KIND.search(head)
        if m and m.group(2) in KINDS:
            return m.group(2)
        return "analysis"
    return "analysis"
