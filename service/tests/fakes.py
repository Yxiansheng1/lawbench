"""假 6000D、假 395（Starlette 应用）。只返回固定内容，记下收到的请求头，用来核对转发和探测。"""
from __future__ import annotations

import threading

import anyio
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route

CHUNK1 = b'data: {"choices":[{"delta":{"content":"LBFAKE-CHUNK-1"}}]}\n\n'
CHUNK2 = b'data: {"choices":[{"delta":{"content":"LBFAKE-CHUNK-2"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'


class Fake6000D:
    def __init__(self, key_status: int = 200):
        self.key_status = key_status
        self.seen: list[dict] = []
        self.release = threading.Event()  # 流式第二段在测试读到第一段后才发出
        self.hits = 0

    def app(self) -> Starlette:
        async def models(request: Request):
            self.hits += 1
            self.seen.append({"path": request.url.path, "headers": dict(request.headers)})
            return JSONResponse({"object": "list", "data": [{"id": "qwen38-27b"}]})

        async def chat(request: Request):
            self.hits += 1
            body = await request.json()
            self.seen.append({"path": request.url.path, "headers": dict(request.headers), "body": body,
                              "query": str(request.url.query)})
            if not request.headers.get("authorization", "").startswith("Bearer "):
                return JSONResponse({"error": "no key"}, status_code=401)
            if not body.get("stream"):
                if self.key_status != 200:
                    return JSONResponse({"error": "key"}, status_code=self.key_status)
                return JSONResponse({"choices": [{"message": {"content": "x"}, "finish_reason": "length"}]})

            async def gen():
                yield CHUNK1
                await anyio.to_thread.run_sync(self.release.wait, 10)
                yield CHUNK2

            return StreamingResponse(gen(), media_type="text/event-stream", headers={"X-Queue-Wait-Ms": "12"})

        async def redirect(request: Request):
            self.hits += 1
            return RedirectResponse("http://127.0.0.1:1/elsewhere", status_code=302)

        async def other(request: Request):
            self.hits += 1
            return Response("upstream-other", status_code=200)

        return Starlette(routes=[
            Route("/v1/models", models, methods=["GET"]),
            Route("/v1/chat/completions", chat, methods=["POST"]),
            Route("/v1/redirect", redirect, methods=["GET"]),
            Route("/v1/embeddings", other, methods=["POST", "GET"]),
            Route("/admin", other, methods=["GET"]),
        ])


class Fake395:
    def __init__(self):
        self.hits = 0

    def app(self) -> Starlette:
        async def health(request: Request):
            self.hits += 1
            return JSONResponse({"status": "ok", "contract_version": "1.1"})

        return Starlette(routes=[Route("/health", health, methods=["GET"])])
