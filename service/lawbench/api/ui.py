"""给界面的接口 /api/*（Spec 4.3、20.5；契约 contracts/api/）。

每个接口：按契约 $defs/request 校验请求（不合格 INVALID_ARGUMENT）→ 执行 → 包成 {ok, value}；
开发和测试环境再按 $defs/response 校验返回（Spec 20.11）。本卡实现 case_open、case_recent、settings、
capsules、capsules_reset、connection_test；T5 加 materials_scan、materials_list、materials_import。
"""
from __future__ import annotations

import json
import time
from typing import Callable

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import contracts, logs
from ..errors import MESSAGES, ApiError

LLM_MODEL = "qwen38-27b"  # Spec 20.7：发给网关的模型名固定
KEY_TIMEOUT = 10.0


def _endpoint(app_state, name: str, fn: Callable[[dict], dict], *, query: bool = False,
              no_input: bool = False, family: str = "api", path_params: bool = False):
    """family：契约目录（api 或 core）；日志的模块名也用它。"""
    schema = f"{family}/{name}.schema.json"

    async def handler(request: Request) -> JSONResponse:
        t0 = time.monotonic()
        if query:
            data: object = dict(request.query_params)
        else:
            raw = await request.body()
            try:
                data = json.loads(raw) if raw.strip() else {}
            except ValueError:
                raise ApiError("INVALID_ARGUMENT", "bad_json")
        if request.path_params and isinstance(data, dict):
            data = {**data, **request.path_params}   # /api/pipeline/{task_id} 等：路径里的参数并进请求（T16）
        if no_input:
            # settings、capsules 的 $defs/request 是 PUT 的请求体；GET 不带任何参数
            if data:
                raise ApiError("INVALID_ARGUMENT", "unexpected_query")
        elif contracts.errors(schema, "#/$defs/request", data):
            raise ApiError("INVALID_ARGUMENT", "request_contract")
        value = await run_in_threadpool(fn, data)
        body = {"ok": True, "value": value}
        if app_state.config.validate_responses:
            contracts.validate(schema, "#/$defs/response", body)
        case_id = value.get("case_id") if isinstance(value, dict) else None
        logs.event(family, name, case_id=case_id, duration_ms=(time.monotonic() - t0) * 1000)
        return JSONResponse(body)

    return handler


def routes(st) -> list[Route]:
    """st：app.state（带 config、cases、settings、capsules、net、key_getter）。"""

    def case_open(d: dict) -> dict:
        value = st.cases.open(d["path"], d.get("template"))
        st.tasks.mark_abnormal(value["case_id"])  # 上次硬退出时仍在执行的任务标"异常中断"（Spec 9.2）
        st.ocr.resume_case(value["case_id"])      # 案件文件夹拔掉又插回等：接着做它未完成的识别任务（T12 复核）
        return value

    def task_create(d: dict) -> dict:
        return st.tasks.create(d)

    def tasks_list(d: dict) -> dict:
        return st.tasks.list(d["case_id"])

    def task_current(d: dict) -> dict:
        return st.tasks.current(d["session_id"])

    def outputs_list(d: dict) -> dict:
        return st.tasks.outputs(d["case_id"])

    def search(d: dict) -> dict:  # T9：律师检索，返回结构同 case_search
        from ..search import fts
        return fts.search(st.cases.root_of(d["case_id"]), d["case_id"], st.materials.index(d["case_id"]), d["q"])

    def case_recent(d: dict) -> dict:
        return {"cases": st.cases.recent()}

    def settings_get(d: dict) -> dict:
        return st.settings.get()

    def settings_put(d: dict) -> dict:
        st.net.check_servers(d["servers"])  # 6000D 地址不能指向本机转发端口自己
        return st.settings.put(d)

    def capsules_get(d: dict) -> dict:
        return st.capsules.get()

    def capsules_put(d: dict) -> dict:
        return st.capsules.put(d)

    def capsules_reset(d: dict) -> dict:
        return st.capsules.reset()

    def materials_scan(d: dict) -> dict:
        return st.materials.scan(d["case_id"])

    def materials_list(d: dict) -> dict:
        return st.materials.list(d["case_id"])

    def materials_import(d: dict) -> dict:
        return st.materials.import_(d["case_id"], d["paths"], d["target"], d["unzip"])

    def connection_test(d: dict) -> dict:
        return probe_connection(st, d["server"])

    # T16：流水线与 wiki 修改建议
    def pipeline_run(d: dict) -> dict:
        return st.pipelines.run(d)

    def pipeline_status(d: dict) -> dict:
        return st.pipelines.status(d["task_id"])

    def pipeline_cancel(d: dict) -> dict:
        return st.pipelines.cancel(d["task_id"])

    def wiki_suggestions(d: dict) -> dict:
        from ..wiki import suggestions
        return suggestions.handle(st.cases.root_of(d["case_id"]), d.get("id"), d.get("accept"))
    def invoice_run(d: dict) -> dict:
        return st.invoice.run(d)

    def retainer_driver(d: dict) -> dict:
        return st.retainer.handle(d)

    def outputs_confirm(d: dict) -> dict:
        return st.exporter.confirm(d)

    def redline(d: dict) -> dict:
        return st.exporter.redline(d)

    def ocr_submit(d: dict) -> dict:
        return st.ocr.submit(d)

    def ocr_list(d: dict) -> dict:
        return st.ocr.list(d["case_id"])

    def ocr_cancel(d: dict) -> dict:
        return st.ocr.cancel(d["job_id"])

    E = lambda name, fn, **kw: _endpoint(st, name, fn, **kw)  # noqa: E731
    return [
        Route("/api/case/open", E("case_open", case_open), methods=["POST"]),
        Route("/api/case/recent", E("case_recent", case_recent, query=True), methods=["GET"]),
        Route("/api/settings", E("settings", settings_get, query=True, no_input=True), methods=["GET"]),
        Route("/api/settings", E("settings", settings_put), methods=["PUT"]),
        Route("/api/capsules", E("capsules", capsules_get, query=True, no_input=True), methods=["GET"]),
        Route("/api/capsules", E("capsules", capsules_put), methods=["PUT"]),
        Route("/api/capsules/reset", E("capsules_reset", capsules_reset), methods=["POST"]),
        Route("/api/materials/scan", E("materials_scan", materials_scan), methods=["POST"]),
        Route("/api/materials", E("materials_list", materials_list, query=True), methods=["GET"]),
        Route("/api/materials/import", E("materials_import", materials_import), methods=["POST"]),
        Route("/api/connection/test", E("connection_test", connection_test), methods=["POST"]),
        Route("/api/task", E("task_create", task_create), methods=["POST"]),
        Route("/api/tasks", E("tasks_list", tasks_list, query=True), methods=["GET"]),
        Route("/api/task/current", E("task_current", task_current, query=True), methods=["GET"]),
        Route("/api/outputs", E("outputs_list", outputs_list, query=True), methods=["GET"]),
        Route("/api/outputs/confirm", E("outputs_confirm", outputs_confirm), methods=["POST"]),
        Route("/api/redline", E("redline", redline), methods=["POST"]),
        Route("/api/search", E("search", search, query=True), methods=["GET"]),
        Route("/api/pipeline/run", E("pipeline_run", pipeline_run), methods=["POST"]),
        Route("/api/pipeline/{task_id}", E("pipeline_status", pipeline_status, query=True), methods=["GET"]),
        Route("/api/pipeline/{task_id}/cancel", E("pipeline_cancel", pipeline_cancel), methods=["POST"]),
        Route("/api/wiki/suggestions", E("wiki_suggestions", wiki_suggestions, query=True), methods=["GET"]),
        Route("/api/wiki/suggestions/{id}", E("wiki_suggestions", wiki_suggestions), methods=["POST"]),
        Route("/api/invoice/run", E("invoice_run", invoice_run), methods=["POST"]),
        Route("/api/retainer/driver", E("retainer_driver", retainer_driver), methods=["POST"]),
        Route("/api/ocr/jobs", E("ocr_submit", ocr_submit), methods=["POST"]),
        Route("/api/ocr/jobs", E("ocr_list", ocr_list, query=True), methods=["GET"]),
        Route("/api/ocr/jobs/{job_id}/cancel", E("ocr_cancel", ocr_cancel, path_params=True), methods=["POST"]),
    ]


def probe_connection(st, server: str) -> dict:
    """对所内、所外地址依次探测；6000D 另发 max_tokens=1 请求判断 Key（Spec 20.7；6000D 目前不校验 Key）。"""
    net = st.net
    t0 = time.monotonic()
    try:
        base, route = net.select(server, force=True)
    except ApiError as e:
        return {"reachable": False, "key_valid": None, "latency_ms": None, "route": None,
                "message": MESSAGES[e.code]}
    latency = int((time.monotonic() - t0) * 1000)
    where = "所内" if route == "primary" else "所外"
    key_valid = None
    note = ""
    if server == "llm":
        try:
            key = st.key_getter()
        except Exception:  # noqa: BLE001 凭据管理器读取出错（已按类名记日志）：不能说成"尚未设置"
            key, note = None, "，Key 暂时无法验证"
        else:
            if not key:
                note = "，尚未设置 Key"
        if key:
            try:
                r = net.client.post(base + "/chat/completions", timeout=KEY_TIMEOUT,
                                    headers={"Authorization": f"Bearer {key}"},
                                    json={"model": LLM_MODEL, "messages": [{"role": "user", "content": "ping"}],
                                          "max_tokens": 1, "stream": False})
                if r.status_code == 200:
                    key_valid = True
                elif r.status_code in (401, 403):
                    key_valid = False
                    note = "，" + MESSAGES["KEY_INVALID"]
                else:
                    note = "，Key 暂时无法验证"
            except Exception as e:  # noqa: BLE001 连接中断等：连通性已确认，Key 状态未知
                logs.event("api", "connection_test_key", status="fail", error=type(e).__name__)
                note = "，Key 暂时无法验证"
    return {"reachable": True, "key_valid": key_valid, "latency_ms": latency, "route": route,
            "message": f"已连接（{where}）{note}"}
