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


# 2026-10-10 在 395 上 Xiaomi-OCR-0 对一页虚构扣押清单的真实输出（evidence\T11\g5-xiaomi.md 第三节），原样
REAL_OTSL = ("## 扣押物品清单\n\n被扣押人：张某甲 扣押时间：2026年3月12日\n\n下列物品已依法扣押，清单如下：\n\n"
             "<fcel>序号<fcel>物品名称<fcel>数量<fcel>备注<nl><fcel>1<fcel>手机（黑色）<fcel>1部<fcel>已封存<nl>"
             "<fcel>2<fcel>银行卡<fcel>3张<fcel>尾号4417、8802、0935<nl><fcel>3<fcel>现金<fcel>人民币86,420元<ecel><nl>"
             "<fcel>4<fcel>笔记本电脑<fcel>1台<fcel>已封存<nl>\n\n以上物品经当场清点无误。\n\n见证人：李某丁")
REAL_TABLE = ("| 序号 | 物品名称 | 数量 | 备注 |\n|---|---|---|---|\n| 1 | 手机（黑色） | 1部 | 已封存 |\n"
              "| 2 | 银行卡 | 3张 | 尾号4417、8802、0935 |\n| 3 | 现金 | 人民币86,420元 |  |\n| 4 | 笔记本电脑 | 1台 | 已封存 |")


def _ocr_reply(model: str, reply: str) -> str:
    app = fake_llama(reply)
    with ServerThread(app) as s:
        be = LlamaServerBackend(s.url, s.url, ocr_model=model)

        async def go():
            md = await be.ocr(png_bytes(size=(20, 30)))
            await be.aclose()
            return md

        return asyncio.run(go())


def test_xiaomi_otsl_table_becomes_markdown():
    """xiaomi 模板：真实 OTSL 片段转成 Markdown 表格（首行表头、<ecel> 留空），表格前后各一个空行，其余文字不动。"""
    md = _ocr_reply("Xiaomi-OCR-0.BF16.gguf", REAL_OTSL)
    assert md == ("## 扣押物品清单\n\n被扣押人：张某甲 扣押时间：2026年3月12日\n\n下列物品已依法扣押，清单如下：\n\n"
                  + REAL_TABLE + "\n\n以上物品经当场清点无误。\n\n见证人：李某丁")
    assert "<fcel>" not in md and "<nl>" not in md


def test_text_without_table_unchanged_and_default_template_not_converted():
    plain = "讯问笔录\n\n问：你是否认识吴某？\n答：认识。a < b，x|y"
    assert _ocr_reply("Xiaomi-OCR-0.BF16.gguf", plain) == plain            # 没有 OTSL：一个字不动
    assert _ocr_reply("PaddleOCR-VL-1.6.gguf", REAL_OTSL) == REAL_OTSL      # default 模板：不转


def test_otsl_merge_marks_pipe_escape_and_ragged_rows():
    """合并占位（<lcel>/<ucel>/<xcel>）按空单元格；单元格里的 | 转义；列数不齐按最长补空；紧挨文字时补空行。"""
    from prep395.backends import otsl_to_markdown
    got = otsl_to_markdown("前文\n<fcel>项目|说明<lcel><fcel>金额<nl><fcel>甲<ucel><xcel><nl><fcel>乙<nl>\n后文")
    assert got == "前文\n\n| 项目\\|说明 |  | 金额 |\n|---|---|---|\n| 甲 |  |  |\n| 乙 |  |  |\n\n后文"


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
