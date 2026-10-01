"""发一页图片到 395 的 /v1/ocr/page，把结果归成识别队列要的几类（Spec 7.3；契约 prep395/ocr_page）。

地址按 Net 的所内 / 所外自动切换选；每页用一个一次性 httpx 客户端（同样的地址白名单、不跟随跳转），
取消时由别的线程 close() 它，正在等的请求立即断开。第一版不去水印：查询参数里从不带 dewatermark（Spec 6.7）。
"""
from __future__ import annotations

import threading

import httpx

from ..errors import ApiError

PAGE_PATH = "/v1/ocr/page"
READ_TIMEOUT = 300.0          # 395 单页实测 6–29 秒；排队加识别给足余量，超时按连接问题处理
DEFAULT_RETRY_AFTER = 30.0


class Offline(Exception):
    """连不上 395、或等结果超时：任务暂停，每 30 秒探测 /health。"""


class Busy(Exception):
    """503：按 Retry-After 等待后重试，不计入失败次数。"""

    def __init__(self, retry_after: float):
        super().__init__(retry_after)
        self.retry_after = retry_after


class ServerError(Exception):
    """504 或其他 5xx：该页重试，最多 3 次。"""

    def __init__(self, status: int):
        super().__init__(status)
        self.status = status


class KeyInvalid(Exception):
    """401，或本机没有设置 Key：整个任务暂停。"""


class PageRejected(Exception):
    """400 / 413：该页失败，附中文原因。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Cancelled(Exception):
    """律师取消，请求被断开。"""


REJECT_REASONS = {400: "395 无法识别这页图片", 413: "这页图片太大，395 不接收"}


class PageSender:
    """一次只发一页。cancel() 可在别的线程调用。"""

    def __init__(self, net, key_getter):
        self.net = net
        self.key_getter = key_getter
        self._client: httpx.Client | None = None
        self._cancelled = threading.Event()
        self._lock = threading.Lock()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            c = self._client
        if c is not None:
            c.close()

    def send(self, png: bytes) -> dict:
        if self._cancelled.is_set():
            raise Cancelled()
        try:
            key = self.key_getter()
        except Exception:  # noqa: BLE001 凭据管理器读取出错：按 Key 不可用处理，不发请求
            raise KeyInvalid() from None
        if not key:
            raise KeyInvalid()
        try:
            base, _route = self.net.select("prep")
        except ApiError:
            raise Offline() from None
        client = self.net.new_client(read_timeout=READ_TIMEOUT)
        with self._lock:
            self._client = client
        try:
            if self._cancelled.is_set():
                raise Cancelled()
            r = client.post(base + PAGE_PATH, content=png,
                            headers={"Authorization": f"Bearer {key}", "Content-Type": "image/png"})
        except Cancelled:
            raise
        except (httpx.TransportError, RuntimeError):
            # 取消时 close() 会让正在进行的请求抛连接类错误（或"客户端已关闭"的 RuntimeError）
            if self._cancelled.is_set():
                raise Cancelled() from None
            self.net.invalidate("prep")
            raise Offline() from None
        except ApiError:                                        # 地址白名单、跳转：按连不上处理
            raise Offline() from None
        finally:
            with self._lock:
                self._client = None
            client.close()
        return classify(r)


def classify(r: httpx.Response) -> dict:
    s = r.status_code
    if s == 200:
        try:
            body = r.json()
            return {"markdown": str(body["markdown"]), "unclear": int(body.get("unclear", 0))}
        except (ValueError, KeyError, TypeError):
            raise ServerError(s) from None
    if s == 401:
        raise KeyInvalid()
    if s == 503:
        try:
            wait = float(r.headers.get("Retry-After", DEFAULT_RETRY_AFTER))
        except ValueError:
            wait = DEFAULT_RETRY_AFTER
        raise Busy(max(1.0, min(wait, 300.0)))
    if s in REJECT_REASONS:
        raise PageRejected(REJECT_REASONS[s])
    if s >= 500:
        raise ServerError(s)
    raise PageRejected(f"395 返回 {s}")
