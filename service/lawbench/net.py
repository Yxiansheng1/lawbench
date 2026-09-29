"""统一 HTTP 客户端（Spec 14.3、第 15 节）。

- 地址白名单：只允许设置里 6000D、395 的所内、所外地址（主机 + 端口），以及 127.0.0.1；发送前检查。
- 不跟随重定向（follow_redirects=False），收到 3xx 视为错误；不读系统代理（trust_env=False）。
- 地址选择：先试所内地址（6000D 请求 /v1/models，395 请求 /health，各 1.5 秒），不通再试所外地址；
  结果缓存 60 秒；请求出现连接错误时重新探测一次。两者都不通报 SERVER_UNREACHABLE。
- 本机转发：只监听 127.0.0.1，把 /v1/chat/completions、/v1/models 流式转发到选中的 6000D 地址，
  其余路径 404；不需要启动令牌；不记录请求和回答内容，只记元数据。
"""
from __future__ import annotations

import contextlib
import threading
import time
from urllib.parse import urlsplit

import anyio
import httpx
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from . import logs
from .errors import MESSAGES, ApiError

LOOPBACK = "127.0.0.1"
PROBE_TIMEOUT = 1.5
CACHE_SECONDS = 60
CONNECT_TIMEOUT = 10.0
REQUEST_TIMEOUT = 1200.0

KINDS = {
    "llm": ("llm_base_url", "llm_alt_base_url", "/models"),
    "prep": ("prep_base_url", "prep_alt_base_url", "/health"),
}

# 转发时带过去的请求头（律师 Key 原样带过去）
FORWARD_REQ_HEADERS = {"authorization", "content-type", "accept", "x-session-id"}
FORWARD_RESP_HEADERS = {"content-type", "x-queue-wait-ms", "cache-control"}


def _host_port(url: str) -> tuple[str, int] | None:
    u = urlsplit(url)
    if u.scheme != "http" or not u.hostname:
        return None
    try:
        port = u.port or 80
    except ValueError:
        return None
    return u.hostname.lower(), port


class Allowlist:
    def __init__(self) -> None:
        self._targets: frozenset[tuple[str, int]] = frozenset()

    def update(self, servers: dict) -> None:
        targets = set()
        for key in ("llm_base_url", "prep_base_url", "llm_alt_base_url", "prep_alt_base_url"):
            url = servers.get(key)
            hp = _host_port(url) if url else None
            if hp:
                targets.add(hp)
        self._targets = frozenset(targets)

    def allowed(self, url: str) -> bool:
        hp = _host_port(str(url))
        if hp is None:
            return False
        return hp[0] == LOOPBACK or hp in self._targets

    def check(self, url) -> None:
        if not self.allowed(str(url)):
            logs.event("net", "request", status="denied", error="HOST_NOT_ALLOWED")
            raise ApiError("HOST_NOT_ALLOWED", "host_not_allowed")


def _check_redirect(response: httpx.Response) -> None:
    if response.is_redirect or 300 <= response.status_code < 400:
        logs.event("net", "redirect", status="denied", error="HOST_NOT_ALLOWED")
        raise ApiError("HOST_NOT_ALLOWED", "redirect")


async def _acheck_redirect(response: httpx.Response) -> None:
    _check_redirect(response)


class Net:
    def __init__(self, servers: dict, clock=time.monotonic, transport: httpx.BaseTransport | None = None):
        self.allow = Allowlist()
        self._clock = clock
        self._lock = threading.Lock()
        self._routes: dict[str, tuple[str, str, float]] = {}
        self._servers: dict = {}
        self.update(servers)
        self.client = httpx.Client(
            follow_redirects=False, trust_env=False, transport=transport,
            timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT),
            event_hooks={"request": [lambda r: self.allow.check(r.url)], "response": [_check_redirect]})

    def close(self) -> None:
        self.client.close()

    def update(self, servers: dict) -> None:
        with self._lock:
            self._servers = dict(servers)
            self.allow.update(servers)
            self._routes.clear()

    def invalidate(self, kind: str | None = None) -> None:
        with self._lock:
            if kind:
                self._routes.pop(kind, None)
            else:
                self._routes.clear()

    # ---------- 地址选择 ----------

    def candidates(self, kind: str) -> list[tuple[str, str]]:
        primary_key, alt_key, _ = KINDS[kind]
        out = [(self._servers[primary_key].rstrip("/"), "primary")]
        if self._servers.get(alt_key):
            out.append((self._servers[alt_key].rstrip("/"), "alternate"))
        return out

    def probe(self, kind: str, base: str) -> bool:
        try:
            r = self.client.get(base + KINDS[kind][2], timeout=PROBE_TIMEOUT)
        except (httpx.TransportError, ApiError):
            return False
        return 200 <= r.status_code < 300

    def select(self, kind: str, force: bool = False) -> tuple[str, str]:
        """返回 (base_url, route)；route 为 primary（所内）或 alternate（所外）。"""
        now = self._clock()
        with self._lock:
            cached = self._routes.get(kind)
            if cached and not force and cached[2] > now:
                return cached[0], cached[1]
            cands = self.candidates(kind)
        for base, route in cands:
            if self.probe(kind, base):
                with self._lock:
                    self._routes[kind] = (base, route, self._clock() + CACHE_SECONDS)
                logs.event("net", "select_" + kind, status="ok", error=None)
                return base, route
        self.invalidate(kind)
        logs.event("net", "select_" + kind, status="fail", error="SERVER_UNREACHABLE")
        raise ApiError("SERVER_UNREACHABLE", "all_routes_down")

    def request(self, kind: str, method: str, path: str, **kw) -> tuple[httpx.Response, str]:
        """按选中的地址发请求；连接出错时重新探测一次再发。返回 (响应, route)。"""
        base, route = self.select(kind)
        try:
            return self.client.request(method, base + path, **kw), route
        except (httpx.ConnectError, httpx.ConnectTimeout):
            self.invalidate(kind)
        base, route = self.select(kind, force=True)
        try:
            return self.client.request(method, base + path, **kw), route
        except (httpx.ConnectError, httpx.ConnectTimeout):
            self.invalidate(kind)
            raise ApiError("SERVER_UNREACHABLE", "connect_error")

    # ---------- 本机转发 ----------

    def async_client(self, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
        async def check(r: httpx.Request) -> None:
            self.allow.check(r.url)

        return httpx.AsyncClient(
            follow_redirects=False, trust_env=False, transport=transport,
            timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT),
            event_hooks={"request": [check], "response": [_acheck_redirect]})


_FORWARD_ROUTES = {("POST", "/v1/chat/completions"): "chat", ("GET", "/v1/models"): "models"}


def _upstream_error(code: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": MESSAGES[code]}}, status_code=status)


def forward_app(net: Net, transport: httpx.AsyncBaseTransport | None = None) -> Starlette:
    state: dict = {}

    @contextlib.asynccontextmanager
    async def lifespan(app):
        state["client"] = net.async_client(transport)
        try:
            yield
        finally:
            await state["client"].aclose()

    async def handle(request: Request) -> Response:
        op = _FORWARD_ROUTES.get((request.method, request.url.path))
        if op is None:
            return Response(status_code=404)
        t0 = time.monotonic()
        client: httpx.AsyncClient = state["client"]
        headers = {k: v for k, v in request.headers.items() if k.lower() in FORWARD_REQ_HEADERS}
        headers["accept-encoding"] = "identity"
        body = await request.body()
        resp = None
        for attempt in (0, 1):
            try:
                base, _ = await anyio.to_thread.run_sync(net.select, "llm", attempt == 1)
                up = client.build_request(request.method, base + request.url.path[len("/v1"):],
                                          params=request.query_params, headers=headers, content=body)
                resp = await client.send(up, stream=True)
                break
            except (httpx.ConnectError, httpx.ConnectTimeout):
                net.invalidate("llm")
            except ApiError as e:
                logs.event("forward", op, status="fail", error=e.code, duration_ms=(time.monotonic() - t0) * 1000)
                return _upstream_error(e.code, 502)
        if resp is None:
            logs.event("forward", op, status="fail", error="SERVER_UNREACHABLE",
                       duration_ms=(time.monotonic() - t0) * 1000)
            return _upstream_error("SERVER_UNREACHABLE", 502)
        out_headers = {k: v for k, v in resp.headers.items() if k.lower() in FORWARD_RESP_HEADERS}

        async def done() -> None:
            await resp.aclose()
            logs.event("forward", op, status="ok" if resp.status_code < 400 else "fail",
                       error=None if resp.status_code < 400 else f"HTTP{resp.status_code}",
                       duration_ms=(time.monotonic() - t0) * 1000)

        return StreamingResponse(resp.aiter_raw(), status_code=resp.status_code, headers=out_headers,
                                 background=BackgroundTask(done))

    app = Starlette(routes=[Route("/v1/chat/completions", handle, methods=["POST"]),
                            Route("/v1/models", handle, methods=["GET"])],
                    lifespan=lifespan)
    app.add_exception_handler(404, lambda r, e: Response(status_code=404))
    app.add_exception_handler(405, lambda r, e: Response(status_code=404))
    return app
