"""给界面的接口 /api/*（Spec 4.3、20.5；契约 contracts/api/）。

每个接口：按契约 $defs/request 校验请求（不合格 INVALID_ARGUMENT）→ 执行 → 包成 {ok, value}；
开发和测试环境再按 $defs/response 校验返回（Spec 20.11）。本卡实现 case_open、case_recent、settings、
capsules、capsules_reset、connection_test。
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
              no_input: bool = False):
    schema = f"api/{name}.schema.json"

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
        logs.event("api", name, case_id=case_id, duration_ms=(time.monotonic() - t0) * 1000)
        return JSONResponse(body)

    return handler


def routes(st) -> list[Route]:
    """st：app.state（带 config、cases、settings、capsules、net、key_getter）。"""

    def case_open(d: dict) -> dict:
        return st.cases.open(d["path"], d.get("template"))

    def case_recent(d: dict) -> dict:
        return {"cases": st.cases.recent()}

    def settings_get(d: dict) -> dict:
        return st.settings.get()

    def settings_put(d: dict) -> dict:
        return st.settings.put(d)

    def capsules_get(d: dict) -> dict:
        return st.capsules.get()

    def capsules_put(d: dict) -> dict:
        return st.capsules.put(d)

    def capsules_reset(d: dict) -> dict:
        return st.capsules.reset()

    def connection_test(d: dict) -> dict:
        return probe_connection(st, d["server"])

    E = lambda name, fn, **kw: _endpoint(st, name, fn, **kw)  # noqa: E731
    return [
        Route("/api/case/open", E("case_open", case_open), methods=["POST"]),
        Route("/api/case/recent", E("case_recent", case_recent, query=True), methods=["GET"]),
        Route("/api/settings", E("settings", settings_get, query=True, no_input=True), methods=["GET"]),
        Route("/api/settings", E("settings", settings_put), methods=["PUT"]),
        Route("/api/capsules", E("capsules", capsules_get, query=True, no_input=True), methods=["GET"]),
        Route("/api/capsules", E("capsules", capsules_put), methods=["PUT"]),
        Route("/api/capsules/reset", E("capsules_reset", capsules_reset), methods=["POST"]),
        Route("/api/connection/test", E("connection_test", connection_test), methods=["POST"]),
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
        key = st.key_getter()
        if not key:
            note = "，尚未设置 Key"
        else:
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
