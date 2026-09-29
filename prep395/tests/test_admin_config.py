"""/admin（HTTP Basic，只读统计）与配置里的地址白名单。"""
from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from conftest import auth, png_bytes
from prep395.app import create_app
from prep395.backends import FakeBackend
from prep395.config import ConfigError, Settings
from prep395.keycheck import key_prefix


def basic(u: str, p: str) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode()}


def test_admin_requires_basic_auth(client):
    assert client.get("/admin").status_code == 401
    assert client.get("/admin", headers=basic("admin", "wrong")).status_code == 401
    assert client.get("/admin", headers=auth()).status_code == 401      # Bearer 不能进管理页
    r = client.get("/admin", headers=basic("admin", "admin"))
    assert r.status_code == 200 and "prep395" in r.text


def test_admin_stats_by_key_prefix(client):
    for _ in range(3):
        client.post("/v1/ocr/page", content=png_bytes(), headers={**auth(), "Content-Type": "image/png"})
    r = client.get("/admin", headers={**basic("admin", "admin"), "Accept": "application/json"})
    data = r.json()
    from conftest import GOOD
    s = data["today"]["by_key"][key_prefix(GOOD)]
    assert s["requests"] == 3 and s["pages"] == 3
    assert data["queue"] == {"ocr": 0, "extract": 0}
    assert GOOD not in r.text


def test_admin_disabled_without_account(tmp_path, gateway, isolated_tmp):
    s = Settings(llm_base=gateway.url, home=tmp_path / "h")
    with TestClient(create_app(s, FakeBackend())) as c:
        assert c.get("/admin", headers=basic("admin", "admin")).status_code == 503


@pytest.mark.parametrize("kw", [
    {"llm_base": "http://8.8.8.8:8000"},
    {"llm_base": "http://192.168.8.77:9999"},
    {"llm_base": "https://192.168.8.77:8000"},
    {"ocr_url": "http://192.168.8.124:9101"},
    {"llm9b_url": "http://10.126.126.1:8000"},
    {"backend": "cloud"},
])
def test_config_rejects_other_addresses(tmp_path, kw):
    with pytest.raises(ConfigError):
        Settings(home=tmp_path, **kw)


def test_config_allows_both_6000d_addresses(tmp_path):
    assert Settings(home=tmp_path, llm_base="http://10.126.126.1:8000").key_check_url == \
        "http://10.126.126.1:8000/v1/chat/completions"
    assert Settings(home=tmp_path, llm_base="http://192.168.8.77:8000/v1").key_check_url == \
        "http://192.168.8.77:8000/v1/chat/completions"


def test_from_env(tmp_path):
    s = Settings.from_env({"PREP395_LLM_BASE": "http://127.0.0.1:1", "PREP395_OCR_CONCURRENCY": "3",
                           "PREP395_HOME": str(tmp_path), "PREP395_BACKEND": "llama"})
    assert s.ocr_concurrency == 3 and s.backend == "llama" and s.log_dir == tmp_path / "logs"
