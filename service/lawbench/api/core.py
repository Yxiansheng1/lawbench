"""Agent 插件调用的 /core/*（Spec 20.3；契约 contracts/core/）。

五个命令：task/begin、context、tool、progress、task/end。返回体、令牌、错误码与 /api/* 相同（Spec 20.1）。
/core/tool 按工具契约校验 args，不合格 INVALID_ARGUMENT；开发和测试环境再按 $defs/result 校验返回。
"""
from __future__ import annotations

from starlette.routing import Route

from .. import tools
from ..case import context
from ..errors import ApiError
from .ui import _endpoint


def routes(st) -> list[Route]:
    def task_begin(d: dict) -> dict:
        return st.tasks.begin(d["session_id"], d["cwd"])

    def ctx(d: dict) -> dict:
        case_id, root, task = st.tasks.locate(d["task_id"])
        return context.build(root, task, st.materials.index(case_id), st.tasks.read_input)

    def tool(d: dict) -> dict:
        case_id, root, task = st.tasks.locate(d["task_id"])
        if task["state"] != "running":
            raise ApiError("TASK_NOT_FOUND", "task_not_running")
        tc = tools.ToolContext(root=root, case_id=case_id, task=task, tasks=st.tasks, materials=st.materials,
                               skills_dirs=tuple(st.config.skills_dirs))
        return tools.run(tc, d["tool"], d["args"], validate_result=st.config.validate_responses)

    def progress(d: dict) -> dict:
        return st.tasks.progress(d["task_id"], d["text"], d["model_calls"], d["tool_calls"])

    def task_end(d: dict) -> dict:
        return st.tasks.end(d["task_id"], d["reason"], d["model_calls"], d["tool_calls"], d["elapsed_s"])

    E = lambda name, fn: _endpoint(st, name, fn, family="core")  # noqa: E731
    return [
        Route("/core/task/begin", E("task_begin", task_begin), methods=["POST"]),
        Route("/core/context", E("context", ctx), methods=["POST"]),
        Route("/core/tool", E("tool", tool), methods=["POST"]),
        Route("/core/progress", E("progress", progress), methods=["POST"]),
        Route("/core/task/end", E("task_end", task_end), methods=["POST"]),
    ]
