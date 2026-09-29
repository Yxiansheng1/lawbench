"""工作台服务的 ASGI 应用：令牌校验、/health、统一返回体与错误码（Spec 1.3、20.1）。"""
from __future__ import annotations

import copy
import hmac
import types

import httpx
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import contracts, logs
from .api import core, ui
from .capsules import CapsuleStore
from .case.materials import Materials
from .ingest import libreoffice
from .case.registry import CaseRegistry
from .case.task import TaskStore
from .config import Config
from .errors import ApiError, fail_body
from .net import Net
from .settings import DEFAULTS, SettingsStore

KEYRING_SERVICE = "lawbench/LAWFIRM_KEY"  # Spec 8.1
KEYRING_USER = "lawbench"


def keyring_key() -> str | None:
    """从 Windows 凭据管理器读律师 Key；只读，不缓存到文件（Spec 8.1）。没设置返回 None，读取出错照常抛出。"""
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception as e:
        logs.event("app", "keyring_read", status="fail", error=type(e).__name__)
        raise


def create_app(config: Config, *, key_getter=None, transport: httpx.BaseTransport | None = None) -> Starlette:
    contracts.set_contracts_dir(config.contracts_dir)
    logs.setup(config.appdata)
    config.appdata.mkdir(parents=True, exist_ok=True)

    st = types.SimpleNamespace()
    st.config = config
    st.cases = CaseRegistry(config.appdata, config.contracts_dir / "case_db.sql")
    lo_base = config.appdata / "临时" / "lo"
    libreoffice.cleanup_base(lo_base)  # 清掉上次留下的 LibreOffice 配置目录（里面有"最近打开的文件"记录，SEC-11）
    st.materials = Materials(st.cases, lo_base=lo_base)
    st.settings = SettingsStore(config.appdata)
    st.tasks = TaskStore(st.cases, st.settings, st.materials)
    st.capsules = CapsuleStore(config.appdata, config.skills_dirs)
    try:
        servers = st.settings.get()["servers"]
    except Exception as e:  # noqa: BLE001 settings.json 损坏：服务照常起来，先用默认地址，设置接口返回错误
        logs.event("app", "settings_load", status="fail", error=type(e).__name__)
        servers = copy.deepcopy(DEFAULTS["servers"])
    try:
        st.net = Net(servers, transport=transport, forward_port=config.forward_port)
    except ApiError as e:  # 设置里的 6000D 地址指向了转发端口自己：先用默认地址
        logs.event("app", "settings_load", status="fail", error=f"{e.code}:{e.reason}")
        st.net = Net(copy.deepcopy(DEFAULTS["servers"]), transport=transport, forward_port=config.forward_port)
    st.settings.on_change(lambda s: st.net.update(s["servers"]))
    st.key_getter = key_getter or keyring_key
    try:
        st.capsules.ensure()  # 首次启动复制默认胶囊配置；已有配置则补进默认配置新增的胶囊
    except Exception as e:  # noqa: BLE001 capsules.json 损坏：服务照常起来，/api/capsules/reset 可恢复
        logs.event("app", "capsules_load", status="fail", error=type(e).__name__)

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "contract_version": contracts.version()})

    app = Starlette(routes=[Route("/health", health, methods=["GET"]), *ui.routes(st), *core.routes(st)])
    app.state.lb = st
    token = config.token.encode("utf-8")

    async def auth(request: Request, call_next):
        if request.url.path != "/health":
            got = request.headers.get("authorization", "")
            if not (got.startswith("Bearer ") and hmac.compare_digest(got[7:].encode("utf-8"), token)):
                return Response(status_code=401)
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001 内部异常：返回失败体后不再抛出（否则 uvicorn 会断开这条 keep-alive 连接）
            logs.event("api", _op(request), status="fail", error=type(exc).__name__)  # 只记异常类名
            return JSONResponse(fail_body("INTERNAL"), status_code=500)

    app.add_middleware(BaseHTTPMiddleware, dispatch=auth)

    async def on_api_error(request: Request, exc: ApiError) -> JSONResponse:
        error = f"{exc.code}:{exc.reason}" if exc.reason else exc.code  # 原因是固定代号，不含内容
        logs.event("api", _op(request), status="denied" if exc.code == "OUT_OF_CASE" else "fail", error=error)
        return JSONResponse(fail_body(exc.code), status_code=200)

    async def on_contract_error(request: Request, exc: contracts.ContractError) -> JSONResponse:
        logs.event("api", _op(request), status="fail", error=f"CONTRACT:{exc.schema}{exc.field_path}")
        return JSONResponse(fail_body("INTERNAL"), status_code=500)

    async def on_404(request: Request, exc) -> JSONResponse:
        return JSONResponse(fail_body("INVALID_ARGUMENT"), status_code=404)

    app.add_exception_handler(ApiError, on_api_error)
    app.add_exception_handler(contracts.ContractError, on_contract_error)
    app.add_exception_handler(404, on_404)
    app.add_exception_handler(405, on_404)
    return app


def _op(request: Request) -> str:
    # 操作名取路由路径（固定字符串，不含查询参数和请求体）
    return request.scope.get("route").path if request.scope.get("route") else "unknown"
