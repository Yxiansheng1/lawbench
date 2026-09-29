"""共用夹具：本机假 6000D、真实 uvicorn 服务线程、契约校验器、测试图片。"""
from __future__ import annotations

import io
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "contracts"))
from check_examples import validator  # noqa: E402  契约校验的统一写法

from prep395.app import create_app  # noqa: E402
from prep395.backends import FakeBackend  # noqa: E402
from prep395.config import Settings  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures"
GOOD, BAD, FORBIDDEN = "test-key-good", "test-key-bad", "test-key-forbidden"


def v_ocr(pointer: str):
    return validator("prep395/ocr_page.schema.json", pointer)


def v_extract(pointer: str):
    return validator("prep395/extract.schema.json", pointer)


def assert_valid(v, data) -> None:
    errs = [e.message for e in v.iter_errors(data)]
    assert not errs, errs


# ---------------------------------------------------------------- 真实服务线程


class ServerThread:
    """在后台线程跑一个 uvicorn（端口 0，随机），用于需要真实连接断开的测试。"""

    def __init__(self, app) -> None:
        cfg = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", access_log=False,
                             lifespan="on")
        self.server = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> "ServerThread":
        self.thread.start()
        t = time.time()
        while not self.server.started:
            if time.time() - t > 10:
                raise RuntimeError("uvicorn 没有启动")
            time.sleep(0.02)
        self.port = self.server.servers[0].sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        return self

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(10)


def fake_6000d() -> FastAPI:
    app = FastAPI()
    app.state.calls = []

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        body = await request.json()
        auth = request.headers.get("authorization", "")
        app.state.calls.append({"auth": auth, "body": body})
        if auth == f"Bearer {GOOD}":
            return {"choices": [{"message": {"content": "1"}}]}
        if auth == f"Bearer {FORBIDDEN}":
            return JSONResponse({"error": "forbidden"}, status_code=403)
        if auth == "Bearer boom":
            return JSONResponse({"error": "x"}, status_code=500)
        return JSONResponse({"error": "invalid key"}, status_code=401)

    return app


@pytest.fixture(scope="session")
def gateway():
    app = fake_6000d()
    with ServerThread(app) as s:
        s.app = app
        yield s


def closed_port() -> int:
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        return sk.getsockname()[1]


@pytest.fixture
def isolated_tmp(tmp_path, monkeypatch):
    """把本进程的系统临时目录指到一个空目录，便于断言"没有新增临时文件"。"""
    t = tmp_path / "systemp"
    t.mkdir()
    for k in ("TMP", "TEMP", "TMPDIR"):
        monkeypatch.setenv(k, str(t))
    monkeypatch.setattr(tempfile, "tempdir", str(t))
    return t


@pytest.fixture
def settings(tmp_path, gateway, isolated_tmp) -> Settings:
    return Settings(llm_base=gateway.url, home=tmp_path / "home", admin_user="admin",
                    admin_pass_sha256="8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918")  # "admin"


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def client(settings, backend):
    from fastapi.testclient import TestClient
    with TestClient(create_app(settings, backend)) as c:
        yield c


def auth(key: str = GOOD) -> dict:
    return {"Authorization": f"Bearer {key}"}


def png_bytes(size=(800, 1100), color=(250, 250, 250)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def scan_pages() -> list[Image.Image]:
    """criminal-01 讯问笔录的三页扫描图（取 PDF 里嵌入的原始图片，1240×1754）。"""
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c
    doc = pdfium.PdfDocument(str(FIXTURES / "criminal-01" / "讯问笔录.pdf"))
    out = []
    for i in range(len(doc)):
        objs = list(doc[i].get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE]))
        out.append(objs[0].get_bitmap().to_pil().convert("RGB"))
    return out


def to_bytes(img: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()
