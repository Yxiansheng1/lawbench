"""Key 校验（Spec 6.3）：395 不另存 Key，用请求带来的 Key 向 6000D 发一个最小对话请求。

200 = 有效（内存缓存 30 秒）；401 / 403 = 无效（不缓存）；连不上、超时或其他状态 = 无法校验。
缓存的键是 Key 的 SHA-256，不在内存里长期保留 Key 原文。
"""
from __future__ import annotations

import hashlib
import time
from enum import Enum

import httpx


class KeyStatus(str, Enum):
    valid = "valid"
    invalid = "invalid"
    unavailable = "unavailable"


def key_digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def key_prefix(key: str) -> str:
    """日志与统计里用的 Key 标识：SHA-256 的前 8 位。"""
    return key_digest(key)[:8]


class KeyChecker:
    def __init__(self, url: str, ttl_s: float = 30.0, timeout_s: float = 10.0,
                 clock=time.monotonic) -> None:
        self.url = url
        self.ttl_s = ttl_s
        self.timeout_s = timeout_s
        self.clock = clock
        self._valid_until: dict[str, float] = {}
        self._client: httpx.AsyncClient | None = None

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            # trust_env=False：不走系统代理，只连配置里的 6000D 地址
            self._client = httpx.AsyncClient(timeout=self.timeout_s, trust_env=False)
        return self._client

    async def check(self, key: str) -> KeyStatus:
        if not key:
            return KeyStatus.invalid
        d = key_digest(key)
        now = self.clock()
        until = self._valid_until.get(d)
        if until is not None and until > now:
            return KeyStatus.valid
        self._valid_until.pop(d, None)
        body = {
            "model": "qwen38-27b",
            "messages": [{"role": "user", "content": "1"}],
            "max_tokens": 1,
            "temperature": 0,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            r = await self._http().post(self.url, json=body, headers={"Authorization": f"Bearer {key}"})
        except (httpx.HTTPError, OSError):
            return KeyStatus.unavailable
        if r.status_code == 200:
            self._valid_until[d] = self.clock() + self.ttl_s
            return KeyStatus.valid
        if r.status_code in (401, 403):
            return KeyStatus.invalid
        return KeyStatus.unavailable
