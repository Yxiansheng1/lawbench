"""并发、排队满、取消（Spec 6.5）。用真实 uvicorn 服务，客户端断开是真的断开 TCP 连接。"""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from conftest import ServerThread, auth, png_bytes, v_ocr, assert_valid
from prep395.app import create_app
from prep395.backends import FakeBackend
from prep395.queue import ClientGone, QueueFull, Slots

IMG = png_bytes(size=(200, 300))
HDR = {**auth(), "Content-Type": "image/png"}


def wait_until(cond, timeout=5.0) -> float:
    t0 = time.time()
    while not cond():
        if time.time() - t0 > timeout:
            raise AssertionError("等待超时")
        time.sleep(0.02)
    return time.time() - t0


@pytest.fixture
def served(settings):
    be = FakeBackend()
    be.gate = asyncio.Event()       # 3.10 起 Event 在第一次 wait 时才绑定事件循环
    app = create_app(settings, be)
    with ServerThread(app) as s:
        yield s, app, be


def test_queue_full_then_all_complete(served):
    s, app, be = served
    slots = app.state.ocr_slots

    async def go():
        async with httpx.AsyncClient(timeout=30) as c:
            tasks = [asyncio.create_task(c.post(s.url + "/v1/ocr/page", content=IMG, headers=HDR))
                     for _ in range(22)]
            await asyncio.to_thread(wait_until, lambda: slots.running == 2 and slots.waiting == 20)
            r = await c.post(s.url + "/v1/ocr/page", content=IMG, headers=HDR)
            assert r.status_code == 503
            assert r.json()["error"]["code"] == "QUEUE_FULL"
            assert int(r.headers["Retry-After"]) > 0
            assert_valid(v_ocr("#/$defs/error"), r.json())
            assert be.active == 2                   # 同时只处理 2 页
            be.open_gate()
            rs = await asyncio.gather(*tasks)
            assert all(x.status_code == 200 for x in rs)

    asyncio.run(go())
    assert slots.running == 0 and slots.waiting == 0 and be.finished == 22


def test_cancel_queued_and_running(served):
    """提交 20 页后立即断开：排队数 5 秒内归零，推理中的 2 页被取消。"""
    s, app, be = served
    slots = app.state.ocr_slots

    async def go():
        c = httpx.AsyncClient(timeout=30)
        tasks = [asyncio.create_task(c.post(s.url + "/v1/ocr/page", content=IMG, headers=HDR))
                 for _ in range(20)]
        await asyncio.to_thread(wait_until, lambda: slots.running == 2 and slots.waiting == 18)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await c.aclose()                            # 关闭连接 = 客户端断开

    asyncio.run(go())
    took = wait_until(lambda: slots.waiting == 0 and slots.running == 0, timeout=5)
    assert took < 5
    wait_until(lambda: be.active == 0, timeout=2)
    assert be.cancelled == 2 and be.finished == 0
    assert be.started == 2                          # 排队中的 18 页没有进入推理


def test_extract_runs_one_at_a_time(served):
    s, app, be = served
    body = {"task": "classify", "text": "讯问笔录", "categories": ["讯问笔录", "其他"]}

    async def go():
        async with httpx.AsyncClient(timeout=30) as c:
            tasks = [asyncio.create_task(c.post(s.url + "/v1/extract", json=body, headers=auth()))
                     for _ in range(3)]
            await asyncio.to_thread(wait_until, lambda: app.state.llm_slots.waiting == 2)
            assert be.active == 1
            be.open_gate()
            rs = await asyncio.gather(*tasks)
            assert all(r.status_code == 200 for r in rs)

    asyncio.run(go())


# ---------------------------------------------------------------- Slots 单元


def test_slots_handoff_and_full():
    async def go():
        sl = Slots(1, 1)
        never = lambda: asyncio.sleep(0, result=False)  # noqa: E731
        await sl.acquire(never)
        waiter = asyncio.create_task(sl.acquire(never))
        await asyncio.sleep(0.05)
        assert sl.waiting == 1
        with pytest.raises(QueueFull):
            await sl.acquire(never)
        sl.release()
        await waiter
        assert sl.running == 1 and sl.waiting == 0
        sl.release()
        assert sl.running == 0

    asyncio.run(go())


def test_slots_waiter_disconnect_leaves_queue():
    async def go():
        sl = Slots(1, 5)
        gone = {"v": False}

        async def disc():
            return gone["v"]

        await sl.acquire(disc)
        waiter = asyncio.create_task(sl.acquire(disc))
        await asyncio.sleep(0.05)
        gone["v"] = True
        with pytest.raises(ClientGone):
            await waiter
        assert sl.waiting == 0
        sl.release()
        assert sl.running == 0

    asyncio.run(go())
