"""395 预处理服务（Spec 第 6 节、20.6；契约 contracts/prep395/）。

每个请求在同一请求内处理完并返回，不保存跨请求的内容；全程不产生临时文件（Spec 6.2）。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import io
import json
import os
import re
import tempfile
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.requests import ClientDisconnect
from PIL import Image, UnidentifiedImageError

from . import CONTRACT_VERSION, __version__
from .backends import Backend, FakeBackend, LlamaServerBackend
from .config import TEMP_PREFIX, Settings
from .dewatermark import deskew, dewatermark
from .keycheck import KeyChecker, KeyStatus, key_prefix
from .logs import AccessLog
from .queue import ClientGone, QueueFull, Slots, Timeout, run_cancellable

OCR_QUERY = ("dewatermark", "deskew", "return_image")
LOC_OK = re.compile(r"^第[0-9]+[页段行]$")
CLIENT_GONE = 499   # 只写进日志：客户端已断开，没有响应可发

MESSAGES = {
    "BAD_IMAGE": "图片格式或尺寸不对（只接受 PNG、JPEG，长边不超过 2480 像素）",
    "BAD_REQUEST": "请求格式不对",
    "KEY_INVALID": "Key 无效或已停用",
    "TOO_LARGE": "文件过大（不超过 10MB）",
    "QUEUE_FULL": "排队已满，请稍后重试",
    "KEY_CHECK_UNAVAILABLE": "无法验证 Key（6000D 暂时连不上）",
    "TIMEOUT": "识别超时",
    "INTERNAL": "服务内部错误",
}
STATUS = {"BAD_IMAGE": 400, "BAD_REQUEST": 400, "KEY_INVALID": 401, "TOO_LARGE": 413, "QUEUE_FULL": 503,
          "KEY_CHECK_UNAVAILABLE": 503, "TIMEOUT": 504, "INTERNAL": 500}


class Fail(Exception):
    def __init__(self, code: str, headers: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.headers = headers or {}


def error_response(code: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": MESSAGES[code]}}, status_code=STATUS[code],
                        headers=headers)


def startup_cleanup(settings: Settings) -> int:
    """删除本服务前缀的残留文件（进程被强制结束时的兜底）。

    只看两处的**顶层**：系统临时目录、服务目录下专用的 tmp 子目录；只删普通文件，
    不删目录、不碰链接和联接，不递归（服务目录里的程序文件、WinSW 配置等不受影响）。
    """
    n = 0
    for d in (Path(tempfile.gettempdir()), settings.home / "tmp"):
        if not d.is_dir():
            continue
        for p in d.glob(TEMP_PREFIX + "*"):
            try:
                if p.is_symlink() or os.path.isjunction(p) or not p.is_file():
                    continue
                p.unlink()
                n += 1
            except OSError:
                pass
    return n


class Stats:
    """/admin 用的内存统计：按 Key 前缀统计当天的页数和耗时，跨天清零。"""

    def __init__(self) -> None:
        self.day = date.today()
        self.by_key: dict[str, dict[str, int]] = {}

    def add(self, prefix: str, pages: int, elapsed_ms: int) -> None:
        if date.today() != self.day:
            self.day, self.by_key = date.today(), {}
        s = self.by_key.setdefault(prefix, {"requests": 0, "pages": 0, "elapsed_ms": 0})
        s["requests"] += 1
        s["pages"] += pages
        s["elapsed_ms"] += elapsed_ms


def _bearer(request: Request) -> str:
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h[:7].lower() == "bearer " else ""


def _parse_bool(v: str) -> bool:
    if v.lower() in ("true", "1"):
        return True
    if v.lower() in ("false", "0"):
        return False
    raise Fail("BAD_REQUEST")


async def _read_body(request: Request, limit: int) -> bytes:
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > limit:
            raise Fail("TOO_LARGE")
    return bytes(buf)


def _open_image(body: bytes, max_long_side: int) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(body))
        if img.format not in ("PNG", "JPEG") or max(img.size) > max_long_side or min(img.size) < 1:
            raise Fail("BAD_IMAGE")
        img.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise Fail("BAD_IMAGE") from None
    return img.convert("RGB")


def _preprocess(img: Image.Image, do_deskew: bool, do_dewatermark: bool) -> tuple[bytes, Image.Image]:
    if do_deskew:
        img, _ = deskew(img)
    if do_dewatermark:
        img, _ = dewatermark(img)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue(), img


def create_app(settings: Settings | None = None, backend: Backend | None = None,
               keychecker: KeyChecker | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if backend is None:
        backend = FakeBackend() if settings.backend == "fake" else LlamaServerBackend(
            settings.ocr_url, settings.llm9b_url, settings.ocr_model, settings.llm9b_model,
            timeout_s=settings.ocr_timeout_s + 10)
    keychecker = keychecker or KeyChecker(settings.key_check_url, settings.key_cache_ttl_s,
                                          settings.key_check_timeout_s)
    log = AccessLog(settings.log_dir)
    ocr_slots = Slots(settings.ocr_concurrency, settings.queue_max)
    llm_slots = Slots(1, settings.queue_max)
    stats = Stats()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        n = startup_cleanup(settings)
        log.event("startup_cleanup", n)
        yield
        await backend.aclose()
        await keychecker.aclose()
        log.close()

    app = FastAPI(title="prep395", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.backend = backend
    app.state.keychecker = keychecker
    app.state.ocr_slots = ocr_slots
    app.state.llm_slots = llm_slots
    app.state.stats = stats
    app.state.log = log

    @app.exception_handler(RequestValidationError)
    async def _bad_request(request: Request, exc: RequestValidationError):
        return error_response("BAD_REQUEST")

    @app.exception_handler(Exception)
    async def _internal(request: Request, exc: Exception):
        log.write(key=None, api=request.url.path.lstrip("/"), pages=0, nbytes=0, elapsed_ms=0, status=500,
                  err=type(exc).__name__)
        return error_response("INTERNAL")

    async def authorize(request: Request) -> str:
        key = _bearer(request)
        if not key or not key.isascii():      # 含非 ASCII 字符的不可能是有效 Key，不发给 6000D
            raise Fail("KEY_INVALID")
        st = await keychecker.check(key)
        if st is KeyStatus.invalid:
            raise Fail("KEY_INVALID")
        if st is KeyStatus.unavailable:
            raise Fail("KEY_CHECK_UNAVAILABLE")
        return key

    def check_length(request: Request) -> None:
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                if int(cl) > settings.max_body_bytes:
                    raise Fail("TOO_LARGE")
            except ValueError:
                raise Fail("BAD_REQUEST") from None

    async def guarded(request: Request, api: str, handler) -> Response:
        """统一处理：计时、错误体、写日志（只写元数据）。handler 返回 (响应体, 页数)。"""
        t0 = time.monotonic()
        ctx = {"key": None, "bytes": 0}
        status, err, pages = 200, None, 0
        try:
            body, pages = await handler(ctx)
            resp: Response = JSONResponse(body)
        except Fail as f:
            status, err = STATUS[f.code], f.code
            resp = error_response(f.code, f.headers)
        except (ClientGone, ClientDisconnect):   # 排队、推理或上传途中客户端断开
            status, err = CLIENT_GONE, "ClientGone"
            resp = Response(status_code=204)     # 连接已断，这个响应不会送达
        except Exception as e:  # noqa: BLE001
            status, err = 500, type(e).__name__
            resp = error_response("INTERNAL")
        elapsed = int((time.monotonic() - t0) * 1000)
        prefix = key_prefix(ctx["key"]) if ctx["key"] else None
        log.write(key=prefix, api=api, pages=pages, nbytes=ctx["bytes"], elapsed_ms=elapsed, status=status,
                  err=err)
        if prefix and status == 200:
            stats.add(prefix, pages, elapsed)
        return resp

    @app.get("/health")
    async def health():
        ocr_ok, llm_ok = await backend.health()
        return {
            # 测试后端返回的是假文本，部署漏配时不能报 ok
            "status": "ok" if ocr_ok and llm_ok and backend.name != "fake" else "degraded",
            "ocr": "ok" if ocr_ok else "down",
            "llm9b": "ok" if llm_ok else "down",
            "queue": ocr_slots.waiting + llm_slots.waiting,
            "version": __version__,
            "contract_version": CONTRACT_VERSION,
        }

    @app.post("/v1/ocr/page")
    async def ocr_page(request: Request):
        t0 = time.monotonic()

        async def handler(ctx):
            check_length(request)
            opts = {"dewatermark": False, "deskew": True, "return_image": False}
            for k, v in request.query_params.multi_items():
                if k not in OCR_QUERY:
                    raise Fail("BAD_REQUEST")
                opts[k] = _parse_bool(v)
            ctx["key"] = await authorize(request)
            ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype not in ("image/png", "image/jpeg"):
                raise Fail("BAD_IMAGE")
            body = await _read_body(request, settings.max_body_bytes)
            ctx["bytes"] = len(body)
            img = _open_image(body, settings.max_long_side)
            del body
            try:
                await ocr_slots.acquire(request.is_disconnected)
            except QueueFull:
                raise Fail("QUEUE_FULL", {"Retry-After": str(settings.retry_after_s)}) from None
            try:
                async def work():
                    png, _ = await asyncio.to_thread(_preprocess, img, opts["deskew"], opts["dewatermark"])
                    md = await backend.ocr(png)
                    shot = None
                    if opts["return_image"]:
                        shot = base64.b64encode(png).decode("ascii")
                    return md, shot
                md, shot = await run_cancellable(work(), request.is_disconnected, settings.ocr_timeout_s)
            except Timeout:
                raise Fail("TIMEOUT") from None
            finally:
                ocr_slots.release()
            unclear = md.count("■") + md.count("[看不清]")
            elapsed = int((time.monotonic() - t0) * 1000)
            return {"markdown": md, "unclear": unclear, "elapsed_ms": elapsed, "backend": backend.name,
                    "image_png_base64": shot}, 1

        return await guarded(request, "ocr/page", handler)

    @app.post("/v1/extract")
    async def extract(request: Request):
        async def handler(ctx):
            check_length(request)
            if request.query_params:
                raise Fail("BAD_REQUEST")
            ctx["key"] = await authorize(request)
            raw = await _read_body(request, settings.max_body_bytes)
            ctx["bytes"] = len(raw)
            try:
                req = json.loads(raw)
            except (ValueError, UnicodeDecodeError, RecursionError):
                raise Fail("BAD_REQUEST") from None
            task, items = _validate_extract(req, settings.max_text_chars)
            try:
                await llm_slots.acquire(request.is_disconnected)
            except QueueFull:
                raise Fail("QUEUE_FULL", {"Retry-After": str(settings.retry_after_s)}) from None
            t0 = time.monotonic()
            try:
                if task == "fields":
                    coro = backend.extract_fields(req["text"], items)
                else:
                    coro = backend.classify(req["text"], items)
                out = await run_cancellable(coro, request.is_disconnected, settings.extract_timeout_s)
            except Timeout:
                raise Fail("TIMEOUT") from None
            finally:
                llm_slots.release()
            elapsed = int((time.monotonic() - t0) * 1000)
            if task == "fields":
                result = _clean_fields(out, items)
            else:
                result = {"category": _clean_category(out, items)}
            return {"task": task, "result": result, "elapsed_ms": elapsed}, 0

        return await guarded(request, "extract", handler)

    @app.get("/admin")
    async def admin(request: Request):
        if not (settings.admin_user and settings.admin_pass_sha256):
            return Response("未配置管理员账号", status_code=503, media_type="text/plain; charset=utf-8")
        if not _basic_ok(request, settings.admin_user, settings.admin_pass_sha256):
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="prep395"'})
        data = {
            "queue": {"ocr": ocr_slots.waiting, "extract": llm_slots.waiting},
            "running": {"ocr": ocr_slots.running, "extract": llm_slots.running},
            "today": {"date": stats.day.isoformat(), "by_key": stats.by_key},
        }
        if "application/json" in request.headers.get("accept", ""):
            return data
        rows = "".join(
            f"<tr><td>{html.escape(k)}</td><td>{v['requests']}</td><td>{v['pages']}</td>"
            f"<td>{v['elapsed_ms']}</td></tr>" for k, v in sorted(stats.by_key.items()))
        return HTMLResponse(
            "<!doctype html><meta charset='utf-8'><title>prep395 管理</title>"
            f"<h1>prep395 {__version__}</h1>"
            f"<p>排队：识别 {data['queue']['ocr']}，抽取 {data['queue']['extract']}；"
            f"处理中：识别 {data['running']['ocr']}，抽取 {data['running']['extract']}</p>"
            f"<h2>今日（{data['today']['date']}）按 Key 前缀</h2>"
            "<table border=1><tr><th>Key 前缀</th><th>请求数</th><th>页数</th><th>耗时（毫秒）</th></tr>"
            f"{rows}</table>")

    return app


def _basic_ok(request: Request, user: str, pass_sha256: str) -> bool:
    h = request.headers.get("authorization", "")
    if h[:6].lower() != "basic ":
        return False
    try:
        u, _, p = base64.b64decode(h[6:]).decode("utf-8").partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    digest = hashlib.sha256(p.encode("utf-8")).hexdigest()
    return hmac.compare_digest(u.encode("utf-8"), user.encode("utf-8")) &         hmac.compare_digest(digest.encode("ascii"), pass_sha256.lower().encode("utf-8"))


def _validate_extract(req, max_chars: int) -> tuple[str, list[str]]:
    if not isinstance(req, dict):
        raise Fail("BAD_REQUEST")
    task = req.get("task")
    list_key = {"fields": "fields", "classify": "categories"}.get(task)
    if list_key is None or set(req) != {"task", "text", list_key}:
        raise Fail("BAD_REQUEST")
    text, items = req["text"], req[list_key]
    if not isinstance(text, str) or len(text) > max_chars:
        raise Fail("BAD_REQUEST")
    if not isinstance(items, list) or not all(isinstance(x, str) for x in items):
        raise Fail("BAD_REQUEST")
    if len(items) < (1 if task == "fields" else 2):
        raise Fail("BAD_REQUEST")
    return task, items


def _clean_fields(out, fields: list[str]) -> list[dict]:
    """模型输出不是对象数组时按内部错误处理；数组里值不合格的条目（字段不是请求里的、值为空、
    位置不是 第N页/段/行）丢掉。"""
    if not isinstance(out, list) or not all(isinstance(it, dict) for it in out):
        raise Fail("INTERNAL")
    res = []
    for it in out:
        f, v, loc = it.get("field"), it.get("value"), it.get("loc")
        if f in fields and isinstance(v, str) and v and isinstance(loc, str) and LOC_OK.match(loc):
            res.append({"field": f, "value": v, "loc": loc})
    return res


def _clean_category(out, categories: list[str]) -> str:
    """分类结果必须是给定类别之一，否则按内部错误处理（不代选"其他"）。"""
    if isinstance(out, str) and out in categories:
        return out
    raise Fail("INTERNAL")
