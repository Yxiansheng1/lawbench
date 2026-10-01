"""流水线调 6000D（Spec 20.7、8.3、8.4）：经 Net（地址白名单、所内所外自动切换、不跟随重定向）发流式请求。

- 请求：POST <选中的地址>/chat/completions，model 固定 qwen38-27b，stream: true，max_tokens、temperature，
  chat_template_kwargs.enable_thinking / reasoning_effort（"高"发 xhigh，Spec 8.2）；请求头 Authorization（律师 Key，
  从凭据管理器读，不落盘不进日志）、X-Session-Id（流水线任务编号）。
- 响应：逐行读 SSE，拼 choices[0].delta.content（思考内容 reasoning_content 不要）；finish_reason；X-Queue-Wait-Ms。
- 错误（Spec 8.3）：连不上 → SERVER_UNREACHABLE（重试 1 次）；401/403 → KEY_INVALID；503 → SERVER_BUSY；
  400 且信息含 context length → CONTEXT_TOO_LONG；客户端计时超过 1200 秒 → TIMEOUT；其余 → INTERNAL。
  finish_reason == "length" 不抛，返回给调用方（流水线照常核对，记进运行记录）。
- 取消：每读一行查一次取消标志，置位就关闭连接（网关记 499、vLLM 中止生成，Spec 8.4）。
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

MODEL = "qwen38-27b"
EFFORT = {"低": "low", "中": "medium", "高": "xhigh"}
REQUEST_SECONDS = 1200


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
        headers = {"Authorization": f"Bearer {key}", "X-Session-Id": session_id, "Accept": "text/event-stream"}
        for attempt in (0, 1):
            if self.cancel.is_set():
                raise Cancelled()
            base, _ = self.net.select("llm", force=attempt > 0)
            try:
                return self._stream(base, body, headers)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                self.net.invalidate("llm")
                if attempt:
                    raise ApiError("SERVER_UNREACHABLE", "connect_error") from None
        raise AssertionError("unreachable")

    def _stream(self, base: str, body: dict, headers: dict) -> Reply:
        t0 = self.clock()
        parts: list[str] = []
        finish = None
        usage: dict = {}
        with self.net.client.stream("POST", base + "/chat/completions", json=body, headers=headers) as r:
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
