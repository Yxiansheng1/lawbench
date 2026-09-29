"""统一 HTTP 客户端（Spec 14.3、第 15 节）。

- 地址白名单：只允许设置里 6000D、395 的所内、所外地址（主机 + 端口），以及 127.0.0.1；发送前检查。
- 不跟随重定向（follow_redirects=False），收到 3xx 视为错误；不读系统代理（trust_env=False）。
- 地址选择：先试所内地址（6000D 请求 /v1/models，395 请求 /health，各 1.5 秒），不通再试所外地址；
  结果缓存 60 秒；请求出现连接错误时重新探测一次。两者都不通报 SERVER_UNREACHABLE。
- 本机转发：只监听 127.0.0.1，把 /v1/chat/completions、/v1/models 流式转发到选中的 6000D 地址，
  其余路径 404；不需要启动令牌；不记录请求和回答内容，只记元数据。
"""
from __future__ import annotations

import json
import threading
import time
from urllib.parse import urlsplit

import anyio
import httpx

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
    def __init__(self, servers: dict, clock=time.monotonic, transport: httpx.BaseTransport | None = None,
                 forward_port: int | None = None):
        self.allow = Allowlist()
        self.forward_port = forward_port
        self._clock = clock
        self._lock = threading.Lock()
        self._routes: dict[str, tuple[str, str, float]] = {}
        self._servers: dict = {}
        self.update(servers)
        self.client = httpx.Client(
            follow_redirects=False, trust_env=False, transport=transport,
            timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT),
            event_hooks={"request": [lambda r: self.allow.check(r.url)], "response": [_check_redirect]})

    def check_servers(self, servers: dict) -> None:
        """6000D 地址不能是本机转发端口自己（否则会自己探测自己）：INVALID_ARGUMENT。"""
        if not self.forward_port:
            return
        for key in ("llm_base_url", "llm_alt_base_url"):
            hp = _host_port(servers[key]) if servers.get(key) else None
            if hp and hp[0] in (LOOPBACK, "localhost") and hp[1] == self.forward_port:
                raise ApiError("INVALID_ARGUMENT", "llm_is_forward_port")

    def update(self, servers: dict) -> None:
        self.check_servers(servers)
        with self._lock:
            self._servers = dict(servers)
            self.allow.update(servers)
            self._routes.clear()

    def invalidate(self, kind: str) -> None:
        with self._lock:
            self._routes.pop(kind, None)

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


def _error_body(code: str) -> bytes:
    return json.dumps({"error": {"code": code, "message": MESSAGES[code]}}, ensure_ascii=False).encode("utf-8")


async def _send_simple(send, status: int, body: bytes = b"", content_type: bytes = b"application/json") -> None:
    headers = [(b"content-length", str(len(body)).encode())]
    if body:
        headers.append((b"content-type", content_type))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body, "more_body": False})


def forward_app(net: Net, transport: httpx.AsyncBaseTransport | None = None):
    """本机转发（纯 ASGI）。

    - 只接受 POST /v1/chat/completions、GET /v1/models；Host 必须是 127.0.0.1:<本端口> 或 localhost:<本端口>；
      带 Origin 请求头（来自网页）一律 404，不发往上游（Spec 第 15 节）。
    - 全程监听客户端断开：断开时取消上游请求（包括还没回响应头的排队阶段）并关闭上游流，记 fail / CANCELLED。
    - 失败都记 module=forward、status=fail：回响应头之前的失败返回 502 失败体；流式中途上游断开时直接断开客户端连接。
    """
    state: dict = {}

    async def lifespan(receive, send) -> None:
        while True:
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                state["client"] = net.async_client(transport)
                await send({"type": "lifespan.startup.complete"})
            elif msg["type"] == "lifespan.shutdown":
                client = state.pop("client", None)
                if client is not None:
                    await client.aclose()
                await send({"type": "lifespan.shutdown.complete"})
                return

    async def app(scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            await lifespan(receive, send)
            return
        if scope["type"] != "http":
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        op = _FORWARD_ROUTES.get((scope["method"], scope["path"]))
        port = (scope.get("server") or ("", 0))[1]
        host = headers.get("host", "").lower()
        if op is None or host not in (f"{LOOPBACK}:{port}", f"localhost:{port}") or "origin" in headers:
            await _send_simple(send, 404)
            return
        await _forward(op, scope, headers, receive, send)

    async def _forward(op: str, scope, headers: dict, receive, send) -> None:
        t0 = time.monotonic()
        outcome = {"status": "fail", "error": "CANCELLED"}

        def log() -> None:
            logs.event("forward", op, status=outcome["status"], error=outcome["error"],
                       duration_ms=(time.monotonic() - t0) * 1000)

        def finish(status: str, error: str | None) -> None:
            """在发出最后一段之前定下结果；之后收到的 disconnect 不再改成 CANCELLED。"""
            outcome.update(status=status, error=error, final=True)

        body = bytearray()
        while True:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                log()
                return
            body += msg.get("body", b"")
            if not msg.get("more_body"):
                break

        up_headers = {k: v for k, v in headers.items() if k in FORWARD_REQ_HEADERS}
        up_headers["accept-encoding"] = "identity"
        query = scope.get("query_string", b"").decode("latin-1")
        client: httpx.AsyncClient = state["client"]

        async def work(cancel_scope: anyio.CancelScope) -> None:
            resp = None
            try:
                for attempt in (0, 1):
                    try:
                        base, _ = await anyio.to_thread.run_sync(net.select, "llm", attempt == 1)
                        url = base + scope["path"][len("/v1"):] + (f"?{query}" if query else "")
                        up = client.build_request(scope["method"], url, headers=up_headers, content=bytes(body))
                        resp = await client.send(up, stream=True)
                        break
                    except (httpx.ConnectError, httpx.ConnectTimeout):
                        net.invalidate("llm")
                if resp is None:
                    finish("fail", "SERVER_UNREACHABLE")
                    await _send_simple(send, 502, _error_body("SERVER_UNREACHABLE"))
                    return
                out = [(k.encode("latin-1"), v.encode("latin-1")) for k, v in resp.headers.items()
                       if k.lower() in FORWARD_RESP_HEADERS]
                await send({"type": "http.response.start", "status": resp.status_code, "headers": out})
                try:
                    async for chunk in resp.aiter_raw():
                        await send({"type": "http.response.body", "body": chunk, "more_body": True})
                except httpx.HTTPError as e:
                    finish("fail", type(e).__name__)  # 上游流式中途断开：不补结尾，让客户端看到连接中断
                    return
                ok = resp.status_code < 400
                finish("ok" if ok else "fail", None if ok else f"HTTP{resp.status_code}")
                await send({"type": "http.response.body", "body": b"", "more_body": False})
            except ApiError as e:
                finish("fail", e.code)
                await _send_simple(send, 502, _error_body(e.code))
            except httpx.HTTPError as e:
                finish("fail", type(e).__name__)
                await _send_simple(send, 502, _error_body("SERVER_UNREACHABLE"))
            finally:
                if resp is not None:
                    with anyio.CancelScope(shield=True):
                        await resp.aclose()
                cancel_scope.cancel()

        async def watch(cancel_scope: anyio.CancelScope) -> None:
            while True:
                msg = await receive()
                if msg["type"] == "http.disconnect":
                    # 响应已经发完后 uvicorn 也会报 disconnect：那不是客户端取消
                    if not outcome.get("final"):
                        outcome.update(status="fail", error="CANCELLED")
                        cancel_scope.cancel()
                    return

        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(work, tg.cancel_scope)
                tg.start_soon(watch, tg.cancel_scope)
        finally:
            log()

    return app
