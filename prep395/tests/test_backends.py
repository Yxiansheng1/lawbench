"""LlamaServerBackend：对本机假 llama-server 核对请求格式、结果解析、健康检查和取消。"""
from __future__ import annotations

import asyncio
import base64
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from conftest import ServerThread, png_bytes
from prep395.backends import LlamaServerBackend


def fake_llama(reply: str, slow: bool = False) -> FastAPI:
    app = FastAPI()
    app.state.bodies = []
    app.state.disconnected = 0

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        body = await request.json()
        app.state.bodies.append(body)
        if slow:
            for _ in range(200):
                if await request.is_disconnected():
                    app.state.disconnected += 1
                    return JSONResponse({}, status_code=499)
                await asyncio.sleep(0.05)
        return {"choices": [{"message": {"content": reply}}]}

    return app


def test_ocr_request_carries_base64_image():
    app = fake_llama("第一行\n■看不清")
    with ServerThread(app) as s:
        be = LlamaServerBackend(s.url, s.url)
        img = png_bytes(size=(20, 30))

        async def go():
            md = await be.ocr(img)
            ok = await be.health()
            await be.aclose()
            return md, ok

        md, ok = asyncio.run(go())
    assert md == "第一行\n■看不清" and ok == (True, True)
    body = app.state.bodies[0]
    parts = body["messages"][0]["content"]
    url = [p for p in parts if p["type"] == "image_url"][0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == img
    assert body["stream"] is False and body["chat_template_kwargs"] == {"enable_thinking": False}


def _ocr_body(model: str) -> tuple[dict, str]:
    app = fake_llama("ok")
    with ServerThread(app) as s:
        be = LlamaServerBackend(s.url, s.url, ocr_model=model)

        async def go():
            await be.ocr(png_bytes(size=(20, 30)))
            await be.aclose()

        asyncio.run(go())
    return app.state.bodies[0], be.name


def test_ocr_template_default_keeps_paddle_prompt():
    """PREP395_OCR_MODEL 不带 xiaomi（默认 "ocr"、PaddleOCR-VL 的文件名）：原来的中文提示词，文字在前、图在后。"""
    from prep395.backends import OCR_PROMPT
    for model in ("ocr", "PaddleOCR-VL-1.6-Q8_0.gguf"):
        body, name = _ocr_body(model)
        parts = body["messages"][0]["content"]
        assert [p["type"] for p in parts] == ["text", "image_url"] and parts[0]["text"] == OCR_PROMPT
        assert body["model"] == model and name == "llama.cpp/vulkan"


def test_ocr_template_xiaomi_uses_model_card_prompt():
    """PREP395_OCR_MODEL 带 xiaomi：模型卡 Document 任务的提示词原文，图在前、提示词在后；backend 名带模板名。"""
    body, name = _ocr_body("Xiaomi-OCR-0.BF16.gguf")
    parts = body["messages"][0]["content"]
    assert [p["type"] for p in parts] == ["image_url", "text"]
    assert parts[1]["text"] == (
        "Extract all information from the main body of the document image and represent it in markdown format, "
        "ignoring headers and footers. Tables should be expressed in OTSL format, formulas in the document should be "
        "represented using LATEX format, and the parsing should be organized according to the reading order.")
    assert name == "llama.cpp/vulkan:xiaomi-ocr-0"
    assert body["chat_template_kwargs"] == {"enable_thinking": False} and body["temperature"] == 0


def test_extract_parses_json_in_code_fence():
    app = fake_llama('```json\n[{"field": "金额", "value": "80,000", "loc": "第2页"}]\n```')
    with ServerThread(app) as s:
        be = LlamaServerBackend(s.url, s.url)

        async def go():
            r = await be.extract_fields("【第2页】80,000", ["金额"])
            await be.aclose()
            return r

        assert asyncio.run(go()) == [{"field": "金额", "value": "80,000", "loc": "第2页"}]


def test_cancel_disconnects_backend_request():
    app = fake_llama("x", slow=True)
    with ServerThread(app) as s:
        be = LlamaServerBackend(s.url, s.url)

        async def go():
            t = asyncio.create_task(be.ocr(png_bytes(size=(10, 10))))
            await asyncio.sleep(0.5)
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
            await be.aclose()

        asyncio.run(go())
        t0 = time.time()
        while app.state.disconnected == 0 and time.time() - t0 < 5:
            time.sleep(0.05)
    assert app.state.disconnected == 1               # 推理后端看到连接断开，会停止生成


def test_health_down_when_backend_missing():
    from conftest import closed_port
    be = LlamaServerBackend(f"http://127.0.0.1:{closed_port()}", f"http://127.0.0.1:{closed_port()}")

    async def go():
        r = await be.health()
        await be.aclose()
        return r

    assert asyncio.run(go()) == (False, False)
