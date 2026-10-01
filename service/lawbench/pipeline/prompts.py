"""流水线提示词（Spec 9.1；formats.md 第 6 节）：Skill 目录的 `流水线提示词.md`，按 `## 标题` 分段。

系统提示 = "通用规则"段 + 本步骤段。改规则只改那个文件，不改程序。Skill 目录按 Spec 10.1 的顺序找，
同名时后一个目录（管理员下发）覆盖前一个（安装目录）。
"""
from __future__ import annotations

import pathlib
import re

from ..errors import ApiError

FILE = "流水线提示词.md"
COMMON = "通用规则"
_HEAD = re.compile(r"^## ", re.M)


def find(skills_dirs, skill: str) -> pathlib.Path:
    for d in reversed(list(skills_dirs or ())):
        p = pathlib.Path(d) / skill / FILE
        if p.is_file():
            return p
    raise ApiError("INTERNAL", "pipeline_prompts_missing")


def parse(text: str) -> dict[str, str]:
    parts = _HEAD.split(text.lstrip("﻿"))
    out: dict[str, str] = {}
    for p in parts[1:]:
        title, _, body = p.partition("\n")
        out[title.strip()] = body.strip()
    return out


class Prompts:
    def __init__(self, sections: dict[str, str], required: tuple[str, ...]):
        missing = [s for s in (COMMON, *required) if s not in sections]
        if missing:
            raise ApiError("INTERNAL", "pipeline_prompts_incomplete")
        self.sections = sections

    @classmethod
    def load(cls, skills_dirs, skill: str, required: tuple[str, ...]) -> "Prompts":
        return cls(parse(find(skills_dirs, skill).read_text(encoding="utf-8", errors="replace")), required)

    def system(self, step: str, extra: str | None = None) -> str:
        s = self.sections[COMMON] + "\n\n" + self.sections[step]
        if extra:
            s += "\n\n（原任务要求）\n" + self.sections[extra]
        return s
