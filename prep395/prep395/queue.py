"""并发、排队和取消（Spec 6.5）。

- 同时处理 N 个（识别默认 2、9B 固定 1），其余在内存中排队；排队满 20 个时拒绝（503 + Retry-After）。
- 客户端断开：排队中的直接出队；推理中的取消对推理后端的请求（httpx 请求被取消即断开连接，
  llama-server 随之停止生成）。
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Awaitable, Callable

Disconnected = Callable[[], Awaitable[bool]]
POLL_S = 0.1


class QueueFull(Exception):
    pass


class ClientGone(Exception):
    pass


class Timeout(Exception):
    pass


class Slots:
    def __init__(self, concurrency: int, max_waiting: int) -> None:
        self.concurrency = concurrency
        self.max_waiting = max_waiting
        self.running = 0
        self._waiters: deque[asyncio.Future] = deque()

    @property
    def waiting(self) -> int:
        return len(self._waiters)

    async def acquire(self, disconnected: Disconnected) -> None:
        """拿到一个处理名额；排队已满抛 QueueFull，排队中客户端断开抛 ClientGone。"""
        if self.running < self.concurrency and not self._waiters:
            self.running += 1
            return
        if len(self._waiters) >= self.max_waiting:
            raise QueueFull
        fut = asyncio.get_running_loop().create_future()
        self._waiters.append(fut)
        try:
            while True:
                done, _ = await asyncio.wait({fut}, timeout=POLL_S)
                if await disconnected():        # 拿到名额时客户端已走，也不开始推理
                    raise ClientGone
                if done:
                    return                      # release() 把名额直接交给了我
        except BaseException:
            if fut.done() and not fut.cancelled():
                self.release()                  # 已拿到名额又不用了，交给下一个
            else:
                fut.cancel()
                try:
                    self._waiters.remove(fut)
                except ValueError:
                    pass
            raise

    def release(self) -> None:
        while self._waiters:
            fut = self._waiters.popleft()
            if not fut.done():
                fut.set_result(None)            # 名额直接交接，running 不变
                return
        self.running -= 1


async def run_cancellable(coro: Awaitable, disconnected: Disconnected, timeout_s: float):
    """执行推理；客户端断开抛 ClientGone、超时抛 Timeout，两种情况都取消推理任务。"""
    task = asyncio.ensure_future(coro)
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise Timeout
            done, _ = await asyncio.wait({task}, timeout=min(POLL_S, left))
            if done:
                return task.result()
            if await disconnected():
                raise ClientGone
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except BaseException:  # noqa: BLE001  取消或后端报错都不再关心
                pass
