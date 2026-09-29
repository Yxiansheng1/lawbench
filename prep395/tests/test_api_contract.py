"""每个接口的返回和错误体都通过契约校验（contracts/prep395/*.schema.json）。"""
from __future__ import annotations

import base64
import io
import json

import pytest
from PIL import Image

from conftest import (BAD, FORBIDDEN, assert_valid, auth, closed_port, png_bytes, v_extract, v_ocr,
                      validator)
from prep395.app import create_app
from prep395.backends import FakeBackend
from prep395.config import Settings

ERR_OCR = v_ocr("#/$defs/error")
ERR_EXT = v_extract("#/$defs/error")


def expect_error(r, status: int, code: str, v=ERR_OCR) -> None:
    assert r.status_code == status, (r.status_code, r.text)
    assert_valid(v, r.json())
    assert r.json()["error"]["code"] == code


def test_health_contract(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert_valid(validator("prep395/health.schema.json"), r.json())
    assert r.json()["contract_version"] == "1.1"


def test_health_degraded(settings):
    from fastapi.testclient import TestClient
    with TestClient(create_app(settings, FakeBackend(ocr_ok=False))) as c:
        body = c.get("/health").json()
    assert_valid(validator("prep395/health.schema.json"), body)
    assert body["status"] == "degraded" and body["ocr"] == "down" and body["llm9b"] == "ok"


def test_ocr_ok_contract(client):
    r = client.post("/v1/ocr/page", content=png_bytes(), headers={**auth(), "Content-Type": "image/png"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert_valid(v_ocr("#/$defs/response"), body)
    assert body["image_png_base64"] is None
    assert body["unclear"] == 3            # 固定输出里有 2 个 ■ 和 1 个 [看不清]
    assert body["backend"] == "fake"


def test_ocr_jpeg_and_return_image(client):
    buf = io.BytesIO()
    Image.new("RGB", (600, 900), (240, 240, 240)).save(buf, "JPEG")
    r = client.post("/v1/ocr/page?return_image=true&deskew=false&dewatermark=true", content=buf.getvalue(),
                    headers={**auth(), "Content-Type": "image/jpeg"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert_valid(v_ocr("#/$defs/response"), body)
    img = Image.open(io.BytesIO(base64.b64decode(body["image_png_base64"])))
    assert img.format == "PNG" and img.size == (600, 900)


def test_query_contract_is_what_server_accepts():
    q = validator("prep395/ocr_page.schema.json", "#/$defs/query")
    assert not list(q.iter_errors({"dewatermark": True, "deskew": False, "return_image": True}))
    assert list(q.iter_errors({"foo": True}))


@pytest.mark.parametrize("query", ["foo=1", "dewatermark=maybe"])
def test_ocr_bad_query(client, query):
    r = client.post(f"/v1/ocr/page?{query}", content=png_bytes(), headers={**auth(), "Content-Type": "image/png"})
    expect_error(r, 400, "BAD_REQUEST")


@pytest.mark.parametrize("ctype,content", [
    ("text/plain", b"hello"),
    ("image/png", b"not an image at all"),
    ("image/png", png_bytes(size=(3000, 400))),      # 长边超过 2480
])
def test_ocr_bad_image(client, ctype, content):
    r = client.post("/v1/ocr/page", content=content, headers={**auth(), "Content-Type": ctype})
    expect_error(r, 400, "BAD_IMAGE")


def test_ocr_gif_rejected(client):
    buf = io.BytesIO()
    Image.new("RGB", (50, 50)).save(buf, "GIF")
    r = client.post("/v1/ocr/page", content=buf.getvalue(), headers={**auth(), "Content-Type": "image/png"})
    expect_error(r, 400, "BAD_IMAGE")


@pytest.mark.parametrize("headers", [{}, auth(BAD), auth(FORBIDDEN), {"Authorization": "Basic xx"}])
def test_ocr_key_invalid(client, headers):
    r = client.post("/v1/ocr/page", content=png_bytes(), headers={**headers, "Content-Type": "image/png"})
    expect_error(r, 401, "KEY_INVALID")


def test_ocr_too_large_by_content_length(client, backend):
    big = b"\0" * (10 * 1024 * 1024 + 1)
    r = client.post("/v1/ocr/page", content=big, headers={**auth(), "Content-Type": "image/png"})
    expect_error(r, 413, "TOO_LARGE")
    assert backend.started == 0


def test_ocr_too_large_chunked(client):
    def gen():
        for _ in range(11):
            yield b"\0" * (1024 * 1024)
    r = client.post("/v1/ocr/page", content=gen(), headers={**auth(), "Content-Type": "image/png"})
    expect_error(r, 413, "TOO_LARGE")


def test_key_check_unavailable(tmp_path, isolated_tmp):
    from fastapi.testclient import TestClient
    s = Settings(llm_base=f"http://127.0.0.1:{closed_port()}", home=tmp_path / "h")
    with TestClient(create_app(s, FakeBackend())) as c:
        r = c.post("/v1/ocr/page", content=png_bytes(), headers={**auth(), "Content-Type": "image/png"})
        expect_error(r, 503, "KEY_CHECK_UNAVAILABLE")
        r = c.post("/v1/extract", json={"task": "classify", "text": "x", "categories": ["a", "b"]},
                   headers=auth())
        expect_error(r, 503, "KEY_CHECK_UNAVAILABLE", ERR_EXT)


def test_ocr_timeout(tmp_path, gateway, isolated_tmp):
    from fastapi.testclient import TestClient
    s = Settings(llm_base=gateway.url, home=tmp_path / "h", ocr_timeout_s=0.3)
    be = FakeBackend(delay_s=5)
    with TestClient(create_app(s, be)) as c:
        r = c.post("/v1/ocr/page", content=png_bytes(), headers={**auth(), "Content-Type": "image/png"})
        expect_error(r, 504, "TIMEOUT")
    assert be.cancelled == 1


def test_extract_fields_contract(client):
    text = "【第1页】\n虚构市公安局\n【第2页】\n2025年3月10日转账人民币80,000元，案号（2026）虚0102刑初118号"
    req = {"task": "fields", "text": text, "fields": ["日期", "金额", "案号", "当事人"]}
    assert_valid(v_extract("#/$defs/request"), req)
    r = client.post("/v1/extract", json=req, headers=auth())
    assert r.status_code == 200, r.text
    body = r.json()
    assert_valid(v_extract("#/$defs/response"), body)
    got = {x["field"]: (x["value"], x["loc"]) for x in body["result"]}
    assert got["日期"] == ("2025年3月10日", "第2页")
    assert got["金额"] == ("80,000", "第2页")


def test_extract_classify_contract(client):
    req = {"task": "classify", "text": "讯问笔录\n问：……", "categories": ["起诉意见书", "讯问笔录", "其他"]}
    r = client.post("/v1/extract", json=req, headers=auth())
    assert r.status_code == 200
    assert_valid(v_extract("#/$defs/response"), r.json())
    assert r.json()["result"] == {"category": "讯问笔录"}


@pytest.mark.parametrize("body", [
    b"{not json",
    json.dumps({"task": "toc", "text": "x"}).encode(),
    json.dumps({"task": "fields", "text": "x", "fields": []}).encode(),
    json.dumps({"task": "classify", "text": "x", "categories": ["only"]}).encode(),
    json.dumps({"task": "fields", "text": "x", "fields": ["a"], "extra": 1}).encode(),
    json.dumps({"task": "fields", "text": "字" * 16001, "fields": ["a"]}).encode(),
], ids=["not-json", "unknown-task", "no-fields", "one-category", "extra-key", "text-too-long"])
def test_extract_bad_request(client, body):
    r = client.post("/v1/extract", content=body, headers={**auth(), "Content-Type": "application/json"})
    expect_error(r, 400, "BAD_REQUEST", ERR_EXT)


def test_extract_key_invalid(client):
    r = client.post("/v1/extract", json={"task": "classify", "text": "x", "categories": ["a", "b"]},
                    headers=auth(BAD))
    expect_error(r, 401, "KEY_INVALID", ERR_EXT)


def test_extract_drops_items_that_break_contract(settings):
    """模型输出不守规矩时，只返回符合契约的条目。"""
    from fastapi.testclient import TestClient

    class Sloppy(FakeBackend):
        async def extract_fields(self, text, fields):
            return [{"field": "金额", "value": "1.00", "loc": "第3页"},
                    {"field": "金额", "value": "2.00", "loc": "【第3页】"},
                    {"field": "未请求", "value": "x", "loc": "第1页"},
                    {"field": "日期", "value": "", "loc": "第1页"},
                    "garbage"]

        async def classify(self, text, categories):
            return "不在列表里"

    with TestClient(create_app(settings, Sloppy())) as c:
        r = c.post("/v1/extract", json={"task": "fields", "text": "x", "fields": ["金额", "日期"]}, headers=auth())
        assert r.json()["result"] == [{"field": "金额", "value": "1.00", "loc": "第3页"}]
        assert_valid(v_extract("#/$defs/response"), r.json())
        r = c.post("/v1/extract", json={"task": "classify", "text": "x", "categories": ["书证", "其他"]},
                   headers=auth())
        assert r.json()["result"] == {"category": "其他"}
        r = c.post("/v1/extract", json={"task": "classify", "text": "x", "categories": ["书证", "合同"]},
                   headers=auth())
        expect_error(r, 500, "INTERNAL", ERR_EXT)
