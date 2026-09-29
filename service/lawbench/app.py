"""工作台服务的 ASGI 应用：令牌校验、/health、统一返回体与错误码（Spec 1.3、20.1）。"""
from __future__ import annotations

import hmac
import types

import httpx
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import contracts, logs
from .api import ui
from .capsules import CapsuleStore
from .case.registry import CaseRegistry
from .config import Config
from .errors import ApiError, fail_body
from .net import Net
from .settings import SettingsStore

KEYRING_SERVICE = "lawbench/LAWFIRM_KEY"  # Spec 8.1
KEYRING_USER = "lawbench"


def keyring_key() -> str | None:
    """从 Windows 凭据管理器读律师 Key；只读，不缓存到文件（Spec 8.1）。"""
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception as e:  # noqa: BLE001
        logs.event("app", "keyring_read", status="fail", error=type(e).__name__)
        return None


def create_app(config: Config, *, key_getter=None, transport: httpx.BaseTransport | None = None) -> Starlette:
    contracts.set_contracts_dir(config.contracts_dir)
    logs.setup(config.appdata)
    config.appdata.mkdir(parents=True, exist_ok=True)

    st = types.SimpleNamespace()
    st.config = config
    st.cases = CaseRegistry(config.appdata, config.contracts_dir / "case_db.sql")
    st.settings = SettingsStore(config.appdata)
    st.capsules = CapsuleStore(config.appdata, config.skills_dirs)
    st.net = Net(st.settings.get()["servers"], transport=transport)
    st.settings.on_change(lambda s: st.net.update(s["servers"]))
    st.key_getter = key_getter or keyring_key
    st.capsules.ensure()  # 首次启动复制默认胶囊配置；已有配置则补进默认配置新增的胶囊

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "contract_version": contracts.version()})

    app = Starlette(routes=[Route("/health", health, methods=["GET"]), *ui.routes(st)])
    app.state.lb = st
    token = config.token.encode("utf-8")

    async def auth(request: Request, call_next):
        if request.url.path != "/health":
            got = request.headers.get("authorization", "")
            if not (got.startswith("Bearer ") and hmac.compare_digest(got[7:].encode("utf-8"), token)):
                return Response(status_code=401)
        return await call_next(request)

    app.add_middleware(BaseHTTPMiddleware, dispatch=auth)

    async def on_api_error(request: Request, exc: ApiError) -> JSONResponse:
        logs.event("api", _op(request), status="denied" if exc.code == "OUT_OF_CASE" else "fail", error=exc.code)
        return JSONResponse(fail_body(exc.code), status_code=200)

    async def on_contract_error(request: Request, exc: contracts.ContractError) -> JSONResponse:
        logs.event("api", _op(request), status="fail", error=f"CONTRACT:{exc.schema}{exc.field_path}")
        return JSONResponse(fail_body("INTERNAL"), status_code=500)

    async def on_error(request: Request, exc: Exception) -> JSONResponse:
        logs.event("api", _op(request), status="fail", error=type(exc).__name__)  # 只记异常类名
        return JSONResponse(fail_body("INTERNAL"), status_code=500)

    async def on_404(request: Request, exc) -> JSONResponse:
        return JSONResponse(fail_body("INVALID_ARGUMENT"), status_code=404)

    app.add_exception_handler(ApiError, on_api_error)
    app.add_exception_handler(contracts.ContractError, on_contract_error)
    app.add_exception_handler(Exception, on_error)
    app.add_exception_handler(404, on_404)
    app.add_exception_handler(405, on_404)
    return app


def _op(request: Request) -> str:
    # 操作名取路由路径（固定字符串，不含查询参数和请求体）
    return request.scope.get("route").path if request.scope.get("route") else "unknown"
