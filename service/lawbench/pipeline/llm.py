"""流水线调 6000D（Spec 20.7、8.3、8.4）：经 Net（地址白名单、所内所外自动切换、不跟随重定向）发流式请求。

- 请求：POST <选中的地址>/chat/completions，model 固定 qwen38-27b，stream: true，max_tokens、temperature，
  chat_template_kwargs.enable_thinking / reasoning_effort（"高"发 xhigh，Spec 8.2）；请求头 Authorization（律师 Key，
  从凭据管理器读，不落盘不进日志）、X-Session-Id（流水线任务编号）。
- 响应：逐行读 SSE，拼 choices[0].delta.content（思考内容 reasoning_content 不要）；finish_reason；X-Queue-Wait-Ms。
- 窗口（Spec 8.2）：发送前用 llm/tokens.py 计"系统提示 + 本步输入 + max_tokens"，超过律师选的窗口就不发，
  报 CONTEXT_TOO_LONG（最小版；"切小再发"是独立后续）。
- 错误（Spec 8.3）：连不上 → SERVER_UNREACHABLE（重试 1 次）；401/403 → KEY_INVALID；503 → SERVER_BUSY；
  400 且信息含 context length → CONTEXT_TOO_LONG；客户端计时超过 1200 秒 → TIMEOUT；其余 → INTERNAL。
  读超时 → TIMEOUT，连接中途断开等其余网络错误 → SERVER_UNREACHABLE（不再把异常类名当错误码）。
  finish_reason == "length" 不抛，返回给调用方（流水线照常核对，记进运行记录）。
- 取消（Spec 8.4、F-RUN-02）：每次请求单独一个 client，在后台线程里读；本线程每 0.1 秒查一次取消标志和 1200 秒计时，
  到了就关掉这个 client（断开连接：网关记 499、vLLM 中止生成），不等响应头、不等下一行（T16 返修 P2-1）。
- 并发（Spec 8.5）：进程内同时最多 2 个 6000D 请求（每位律师一台工作台），多个案件同时跑也不超（T16 返修 P3-2）；
  等名额的时间记在 local_wait_ms，和排队时间一样不计入 45 分钟。
- 日志只记元数据（耗时、状态、错误码），不记提示词和输出（Spec 20.8）。
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass

import httpx

from .. import logs
from ..errors import ApiError
from ..llm import tokens

MODEL = "qwen38-27b"
EFFORT = {"低": "low", "中": "medium", "高": "xhigh"}
REQUEST_SECONDS = 1200
POLL = 0.1
SLOTS = 2
_slots = threading.BoundedSemaphore(SLOTS)


class Cancelled(Exception):
    """流水线被取消。"""


@dataclass
class Reply:
    text: str
    finish_reason: str | None
    queue_wait_ms: int | None
    elapsed_s: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    local_wait_ms: int = 0


def abortable(fn, cancel: threading.Event, limit_s: float, abort=None, clock=time.monotonic):
    """在后台线程里跑 fn()；本线程每 POLL 秒查取消标志和时间上限，到了就调 abort()（关连接）并立刻抛
    Cancelled / ApiError(TIMEOUT)，不等 fn 自己返回。"""
    box: dict = {}
    done = threading.Event()

    def work():
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 交给调用线程抛
            box["error"] = e
        finally:
            done.set()

    t0 = clock()
    threading.Thread(target=work, name="pipeline-request", daemon=True).start()
    while not done.wait(POLL):
        stop = Cancelled() if cancel.is_set() else (
            ApiError("TIMEOUT", "request_seconds") if clock() - t0 > limit_s else None)
        if stop is not None:
            if abort is not None:
                try:
                    abort()
                except Exception:  # noqa: BLE001 关连接时对方线程正在读，报什么错都无所谓
                    pass
            raise stop
    if "error" in box:
        raise box["error"]
    return box["value"]


def thinking_fields(thinking: str) -> dict:
    if thinking == "关闭":
        return {"enable_thinking": False}
    return {"enable_thinking": True, "reasoning_effort": EFFORT[thinking]}


class LLM:
    def __init__(self, net, key_getter, cancel: threading.Event | None = None, clock=time.monotonic):
        self.net = net
        self.key_getter = key_getter
        self.cancel = cancel or threading.Event()
        self.clock = clock

    def chat(self, system: str, user: str, params: dict, session_id: str) -> Reply:
        key = self.key_getter()
        if not key:
            raise ApiError("KEY_INVALID", "no_key")
        body = {"model": MODEL, "stream": True, "max_tokens": params["max_tokens"],
                "temperature": params.get("temperature", 0.2),
                "chat_template_kwargs": thinking_fields(params["thinking"]),
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        need = tokens.count(system) + tokens.count(user) + params["max_tokens"]
        if need > tokens.WINDOWS[params["window"]]:
            raise ApiError("CONTEXT_TOO_LONG", "window")
        headers = {"Authorization": f"Bearer {key}", "X-Session-Id": session_id, "Accept": "text/event-stream"}
        waited = self._take_slot()
        try:
            for attempt in (0, 1):
                if self.cancel.is_set():
                    raise Cancelled()
                base, _ = self.net.select("llm", force=attempt > 0)
                try:
                    reply = self._stream(base, body, headers)
                    reply.local_wait_ms = waited
                    return reply
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    self.net.invalidate("llm")
                    if attempt:
                        raise ApiError("SERVER_UNREACHABLE", "connect_error") from None
                except httpx.TimeoutException:
                    raise ApiError("TIMEOUT", "read_timeout") from None
                except httpx.HTTPError:
                    raise ApiError("SERVER_UNREACHABLE", "transport_error") from None
            raise AssertionError("unreachable")
        finally:
            _slots.release()

    def _take_slot(self) -> int:
        t0 = time.monotonic()
        while not _slots.acquire(timeout=POLL):
            if self.cancel.is_set():
                raise Cancelled()
        return int((time.monotonic() - t0) * 1000)

    def _stream(self, base: str, body: dict, headers: dict) -> Reply:
        client = self.net.own_client()

        def read():
            try:
                return self._read(client, base, body, headers)
            finally:
                client.close()

        return abortable(read, self.cancel, REQUEST_SECONDS, client.close, self.clock)

    def _read(self, client: httpx.Client, base: str, body: dict, headers: dict) -> Reply:
        t0 = self.clock()
        parts: list[str] = []
        finish = None
        usage: dict = {}
        with client.stream("POST", base + "/chat/completions", json=body, headers=headers) as r:
            wait = r.headers.get("x-queue-wait-ms")
            queue_ms = int(wait) if wait and wait.isdigit() else None
            if r.status_code != 200:
                r.read()
                raise _http_error(r)
            for line in r.iter_lines():
                if self.cancel.is_set():
                    raise Cancelled()
                if self.clock() - t0 > REQUEST_SECONDS:
                    raise ApiError("TIMEOUT", "request_seconds")
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                if chunk.get("usage"):
                    usage = chunk["usage"]
                for ch in chunk.get("choices") or []:
                    delta = ch.get("delta") or {}
                    if delta.get("content"):
                        parts.append(delta["content"])
                    if ch.get("finish_reason"):
                        finish = ch["finish_reason"]
        return Reply("".join(parts), finish, queue_ms, self.clock() - t0,
                     usage.get("prompt_tokens"), usage.get("completion_tokens"))


def _http_error(r: httpx.Response) -> ApiError:
    if r.status_code in (401, 403):
        return ApiError("KEY_INVALID", f"http_{r.status_code}")
    if r.status_code == 503:
        return ApiError("SERVER_BUSY", "http_503")
    if r.status_code == 400 and "context length" in r.text.lower():
        return ApiError("CONTEXT_TOO_LONG", "http_400")
    logs.event("pipeline", "llm", status="fail", error=f"HTTP_{r.status_code}")
    return ApiError("INTERNAL", f"http_{r.status_code}")
