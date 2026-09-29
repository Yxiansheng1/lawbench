"""推理后端（可插拔）：FakeBackend 供开发与测试，LlamaServerBackend 调本机 llama-server。

后端只做推理，不写文件、不记日志内容；图片以 base64 放在请求体里经本机 HTTP 发送（Spec 6.2）。
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
from typing import Protocol

import httpx

OCR_PROMPT = (
    "请把这张图片中的文字按原有顺序完整转写为 Markdown，只输出转写结果，不要解释。"
    "看不清的单个字用 ■ 代替；整行看不清的写 [看不清]。不要猜测，不要补全。"
    "印章、水印、手写批注中的文字，能看清的照写，并在前面标注（印章）或（批注）。"
)

FIELDS_PROMPT = (
    "从下面的材料文本中抽取这些字段：{fields}。材料里的位置标记形如【第N页】【第N段】【第N行】。"
    "只输出 JSON 数组，每个元素为 {{\"field\": 字段名, \"value\": 原文中原样出现的值, \"loc\": \"第N页\"}}，"
    "loc 写该值所在位置标记里的内容（去掉【】）；原文没有的字段不要输出。\n\n材料文本：\n{text}"
)

CLASSIFY_PROMPT = (
    "判断下面的材料属于哪一类，只能从这些类别中选一个：{cats}。只输出 JSON："
    "{{\"category\": 类别}}。\n\n材料文本：\n{text}"
)

LOC_RE = re.compile(r"【第([0-9]+)([页段行])】")


class Backend(Protocol):
    name: str

    async def ocr(self, png: bytes) -> str: ...

    async def extract_fields(self, text: str, fields: list[str]) -> list[dict]: ...

    async def classify(self, text: str, categories: list[str]) -> str: ...

    async def health(self) -> tuple[bool, bool]: ...

    async def aclose(self) -> None: ...


class FakeBackend:
    """开发和测试用：识别返回固定格式的 markdown；抽取用几条正则在带位置标记的文本里找。"""

    name = "fake"
    FIXED_MARKDOWN = "（测试后端输出）\n第一行文字■■\n[看不清]\n第三行文字"

    def __init__(self, delay_s: float = 0.0, ocr_ok: bool = True, llm_ok: bool = True) -> None:
        self.delay_s = delay_s
        self.ocr_ok = ocr_ok
        self.llm_ok = llm_ok
        self.started = 0
        self.finished = 0
        self.cancelled = 0
        self.active = 0
        self.gate: asyncio.Event | None = None      # 测试可以用它把推理卡住
        self.loop: asyncio.AbstractEventLoop | None = None

    def open_gate(self) -> None:
        """从别的线程放行被 gate 卡住的推理。"""
        self.loop.call_soon_threadsafe(self.gate.set)

    async def _work(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.started += 1
        self.active += 1
        try:
            if self.gate is not None:
                await self.gate.wait()
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            self.finished += 1
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.active -= 1

    async def ocr(self, png: bytes) -> str:
        await self._work()
        return self.FIXED_MARKDOWN

    PATTERNS = {
        "日期": r"\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{2}-\d{2}",
        "金额": r"\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+\.\d{2}",
        "案号": r"[（(]\d{4}[)）][^\s，。]{2,20}?号",
    }

    async def extract_fields(self, text: str, fields: list[str]) -> list[dict]:
        await self._work()
        out = []
        for f in fields:
            pat = self.PATTERNS.get(f)
            if not pat:
                continue
            m = re.search(pat, text)
            if not m:
                continue
            marks = list(LOC_RE.finditer(text, 0, m.start()))
            if marks:
                out.append({"field": f, "value": m.group(0), "loc": f"第{marks[-1].group(1)}{marks[-1].group(2)}"})
        return out

    async def classify(self, text: str, categories: list[str]) -> str:
        await self._work()
        for c in categories:
            if c in text[:2000]:
                return c
        return "其他" if "其他" in categories else categories[-1]

    async def health(self) -> tuple[bool, bool]:
        return self.ocr_ok, self.llm_ok

    async def aclose(self) -> None:
        return None


def _json_from(content: str):
    s = content.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if m:
        s = m.group(1).strip()
    return json.loads(s)


class LlamaServerBackend:
    """本机 llama-server 的 OpenAI 兼容接口：OCR 视觉模型在 9101，9B 在 9102（Spec 6.1）。"""

    name = "llama.cpp/vulkan"

    def __init__(self, ocr_url: str, llm9b_url: str, ocr_model: str = "ocr", llm9b_model: str = "llm9b",
                 timeout_s: float = 130.0) -> None:
        self.ocr_url = ocr_url
        self.llm9b_url = llm9b_url
        self.ocr_model = ocr_model
        self.llm9b_model = llm9b_model
        # trust_env=False：不走系统代理，只连本机
        self.client = httpx.AsyncClient(timeout=timeout_s, trust_env=False)

    async def _chat(self, base: str, model: str, content, max_tokens: int) -> str:
        body = {"model": model, "messages": [{"role": "user", "content": content}],
                "temperature": 0, "max_tokens": max_tokens, "stream": False,
                "chat_template_kwargs": {"enable_thinking": False}}
        r = await self.client.post(base + "/v1/chat/completions", json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""

    async def ocr(self, png: bytes) -> str:
        url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        content = [{"type": "text", "text": OCR_PROMPT}, {"type": "image_url", "image_url": {"url": url}}]
        return await self._chat(self.ocr_url, self.ocr_model, content, 4096)

    async def extract_fields(self, text: str, fields: list[str]) -> list[dict]:
        out = await self._chat(self.llm9b_url, self.llm9b_model,
                               FIELDS_PROMPT.format(fields="、".join(fields), text=text), 2048)
        data = _json_from(out)
        return data if isinstance(data, list) else []

    async def classify(self, text: str, categories: list[str]) -> str:
        out = await self._chat(self.llm9b_url, self.llm9b_model,
                               CLASSIFY_PROMPT.format(cats="、".join(categories), text=text), 64)
        data = _json_from(out)
        return str(data.get("category", "")) if isinstance(data, dict) else ""

    async def health(self) -> tuple[bool, bool]:
        async def one(base: str) -> bool:
            try:
                r = await self.client.get(base + "/health", timeout=3)
                return r.status_code == 200
            except (httpx.HTTPError, OSError):
                return False
        return await one(self.ocr_url), await one(self.llm9b_url)

    async def aclose(self) -> None:
        await self.client.aclose()
