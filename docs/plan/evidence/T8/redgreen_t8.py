r"""T8 红绿验证：/core、8 个工具、任务单的关键防护逐一改坏 → 红 → 复原 → 绿。复用 T3 的 redgreen.py。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T8\redgreen_t8.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_T3 = pathlib.Path(__file__).resolve().parents[1] / "T3" / "redgreen.py"
_spec = importlib.util.spec_from_file_location("redgreen_t3", _T3)
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

CORE = "tests/test_core.py"
TOOLS = "tests/test_tools.py"

rg.TITLE = "T8 红绿验证"
rg.MUTATIONS = [
    ("材料文本路径：先把 index.json 的 rel_path 过闸门再拼", "case/texts.py", [
        ('    gate.check_ai_rel(material["rel_path"], op="material_text")\n', ""),
    ], f"{TOOLS} -k tampered"),
    ("/api/task：选用的输入只能是草稿或成果", "case/task.py", [
        ('            if not ok or not rel.endswith(".md"):\n', "            if False:\n"),
    ], f"{CORE} -k inputs_validated"),
    ("选用的输入被改过报 INPUT_CHANGED", "case/task.py", [
        ('        if not p.is_file() or sha256_file(p) != ref["sha256"]:\n', "        if not p.is_file():\n"),
    ], f"{CORE} -k input_changed"),
    ("覆盖清单只认当前版本的读取记录", "case/task.py", [
        ('                if r["material_id"] == m["material_id"] and r["material_version"] == m["sha256"]:\n',
         '                if r["material_id"] == m["material_id"]:\n'),
    ], f"{TOOLS} -k old_version"),
    ("cwd 不在注册表中一律 CASE_NOT_FOUND", "case/registry.py", [
        ('                if os.path.normcase(c["root"]) == real:\n', "                if True:\n"),
    ], f"{CORE} -k unknown_cwd"),
    ("任务结束后不能再调工具", "api/core.py", [
        ('        if task["state"] != "running":\n', "        if False:\n"),
    ], f"{CORE} -k without_draft"),
    ("没存过正式草稿：进行中.md 改名为 未完成-<时间>.md", "case/task.py", [
        ('        if not res["drafts"]:\n', "        if False:\n"),
    ], f"{CORE} -k without_draft"),
    ("打开案件时把仍在执行的任务标 abnormal", "api/ui.py", [
        ('        st.tasks.mark_abnormal(value["case_id"])', "        pass"),
    ], f"{CORE} -k abnormal"),
    ("L0 不超过 6000 字", "case/context.py", [
        ("    if len(text) > L0_MAX_CHARS:\n", "    if False:\n"),
    ], f"{CORE} -k l0_capped"),
    ("L1 按窗口的 40% 装入，放不下的只列目录", "case/context.py", [
        ("        if not toc and used + n <= budget:\n", "        if True:\n"),
    ], f"{CORE} -k l1_window"),
    ("草稿同标题再存版本加 1，旧版本保留", "tools/drafts.py", [
        ("    version = max(existing, default=0) + 1\n", "    version = 1\n"),
    ], f"{TOOLS} -k versions"),
    ("修改清单：find 跨越超链接或域代码算范围外", "tools/edit_list.py", [
        ("    if len(flags) > 1:\n        return R_CROSS\n", ""),
    ], f"{TOOLS} -k edit_list_scope"),
    ("修改清单：原文已有修订整份范围外", "tools/edit_list.py", [
        ("            reason = R_REVISED if revised else _judge(e, items, has_extras)\n",
         "            reason = _judge(e, items, has_extras)\n"),
    ], f"{TOOLS} -k revised"),
    ("检索：全角转半角、去千分位", "tools/materials.py", [
        ('    s = unicodedata.normalize("NFKC", s)\n', ""),
    ], f"{TOOLS} -k normalization"),
]

if __name__ == "__main__":
    sys.exit(rg.main())
