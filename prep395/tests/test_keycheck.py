"""Key 校验：用本机假 6000D 模拟 200 / 401 / 403 / 不可达（Spec 6.3）。"""
from __future__ import annotations

import asyncio

from conftest import BAD, FORBIDDEN, GOOD, closed_port
from prep395.keycheck import KeyChecker, KeyStatus, key_prefix


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def run(coro):
    return asyncio.run(coro)


def checker(url: str, clock=None) -> KeyChecker:
    return KeyChecker(url + "/v1/chat/completions", ttl_s=30, timeout_s=3, clock=clock or Clock())


def test_valid_is_cached_30_seconds(gateway):
    clock = Clock()
    kc = checker(gateway.url, clock)

    async def go():
        n0 = len(gateway.app.state.calls)
        assert await kc.check(GOOD) is KeyStatus.valid
        assert await kc.check(GOOD) is KeyStatus.valid
        n1 = len(gateway.app.state.calls)
        clock.t += 29.9
        assert await kc.check(GOOD) is KeyStatus.valid
        n2 = len(gateway.app.state.calls)
        clock.t += 0.2                              # 超过 30 秒，重新校验
        assert await kc.check(GOOD) is KeyStatus.valid
        n3 = len(gateway.app.state.calls)
        await kc.aclose()
        return n1 - n0, n2 - n1, n3 - n2

    assert run(go()) == (1, 0, 1)


def test_invalid_not_cached(gateway):
    kc = checker(gateway.url)

    async def go():
        n0 = len(gateway.app.state.calls)
        assert await kc.check(BAD) is KeyStatus.invalid
        assert await kc.check(BAD) is KeyStatus.invalid
        assert await kc.check(FORBIDDEN) is KeyStatus.invalid
        await kc.aclose()
        return len(gateway.app.state.calls) - n0

    assert run(go()) == 3


def test_request_shape(gateway):
    kc = checker(gateway.url)

    async def go():
        await kc.check(GOOD + "-shape")
        await kc.aclose()

    run(go())
    call = gateway.app.state.calls[-1]
    assert call["auth"] == f"Bearer {GOOD}-shape"
    b = call["body"]
    assert b["max_tokens"] == 1 and b["chat_template_kwargs"] == {"enable_thinking": False}
    assert b["model"] == "qwen38-27b" and b["stream"] is False


def test_unreachable_and_server_error_are_unavailable(gateway):
    async def go():
        kc = checker(f"http://127.0.0.1:{closed_port()}")
        a = await kc.check(GOOD)
        await kc.aclose()
        kc = checker(gateway.url)
        b = await kc.check("boom")                  # 假网关对它返回 500
        await kc.aclose()
        return a, b

    assert run(go()) == (KeyStatus.unavailable, KeyStatus.unavailable)


def test_empty_key_invalid_without_request(gateway):
    kc = checker(gateway.url)
    n0 = len(gateway.app.state.calls)
    assert run(kc.check("")) is KeyStatus.invalid
    assert len(gateway.app.state.calls) == n0


def test_key_prefix_is_sha256_8():
    import hashlib
    assert key_prefix("abc") == hashlib.sha256(b"abc").hexdigest()[:8]
