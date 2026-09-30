"""委托材料的证件识别驱动 /api/retainer/driver（T25；Spec 13.5；契约 api/retainer_driver.schema.json）。"""
from __future__ import annotations

import http.server
import io
import random
import shutil
import socket
import threading

import httpx
import pytest

from lawbench.retainer import driver as D

from test_api_case import ok


def free_port() -> int:
    for _ in range(200):
        p = random.randint(17900, 17999)
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    raise RuntimeError("找不到空闲端口")


def listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture
def drv():
    d = D.RetainerDriver(port=free_port())
    yield d
    d.close()


def test_bundled_models_match_expected_hashes():
    """驱动自带三个模型文件与它自己的 default_models.yaml 一致：首次运行不会去下载。"""
    assert D.models_ok(D.DRIVER_DIR)
    names = {f.name for f in (D.DRIVER_DIR / "vendor" / "rapidocr" / "models").glob("*.onnx")}
    assert names == {"PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx", "ch_ppocr_mobile_v2.0_cls_mobile.onnx"}


def test_damaged_model_refuses_to_start(tmp_path):
    """模型缺失或被改：不启动（否则驱动会自己联网重新下载）。"""
    fake = tmp_path / "ocr-driver"
    (fake / "vendor" / "rapidocr" / "models").mkdir(parents=True)
    shutil.copy(D.DRIVER_DIR / "vendor" / "rapidocr" / "default_models.yaml", fake / "vendor" / "rapidocr")
    for f in (D.DRIVER_DIR / "vendor" / "rapidocr" / "models").glob("*.onnx"):
        shutil.copy(f, fake / "vendor" / "rapidocr" / "models")
    assert D.models_ok(fake)
    victim = next((fake / "vendor" / "rapidocr" / "models").glob("*cls*.onnx"))
    victim.write_bytes(victim.read_bytes()[:-1] + b"\0")
    assert not D.models_ok(fake)
    d = D.RetainerDriver(driver_dir=fake, port=free_port())
    from lawbench.errors import ApiError
    with pytest.raises(ApiError) as e:
        d.start()
    assert e.value.code == "ENGINE_FAILED" and d._proc is None           # 不启动（1701 令 P11）
    victim.unlink()
    assert not D.models_ok(fake)


def test_start_ocr_status_stop(drv):
    """真驱动：启动 → 就绪 → 识别一张虚构图片 → 停止；只监听 127.0.0.1。"""
    v = drv.start()
    assert v == {"running": True, "port": 17801, "message": D.MSG_RUNNING}
    h = httpx.get(f"http://127.0.0.1:{drv.port}/health", trust_env=False).json()
    assert D.is_driver(h) and h["engine"] == "rapidocr" and h["offline"] is True
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (400, 120), "white")
    ImageDraw.Draw(img).text((20, 40), "ID 110101199001011234", fill="black")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    r = httpx.post(f"http://127.0.0.1:{drv.port}/ocr", content=buf.getvalue(),
                   headers={"X-File-Name": "test.png"}, timeout=60, trust_env=False)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert drv.status()["running"] is True
    # 只在 127.0.0.1 上听：本机其他地址连不上
    others = [a for a in socket.gethostbyname_ex(socket.gethostname())[2] if not a.startswith("127.")]
    for a in others[:2]:
        with socket.socket() as s:
            s.settimeout(0.5)
            assert s.connect_ex((a, drv.port)) != 0
    assert drv.stop() == {"running": False, "port": 17801, "message": D.MSG_STOPPED}
    assert not listening(drv.port)
    assert drv.status()["running"] is False


def test_reuse_existing_driver_and_do_not_stop_it(drv):
    assert drv.start()["running"] is True
    other = D.RetainerDriver(port=drv.port)
    assert other.start() == {"running": True, "port": 17801, "message": D.MSG_REUSED}
    other.stop()                                               # 不是它起的，不停
    assert listening(drv.port) and drv.status()["running"] is True
    drv.stop()
    assert not listening(drv.port)


def test_port_taken_by_something_else(drv):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", drv.port), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        assert drv.start() == {"running": False, "port": 17801, "message": D.MSG_PORT_TAKEN}
    finally:
        srv.shutdown()
        srv.server_close()


def test_port_taken_by_non_http(drv):
    s = socket.socket()
    s.bind(("127.0.0.1", drv.port))
    s.listen(1)
    try:
        assert drv.start()["message"] == D.MSG_PORT_TAKEN
    finally:
        s.close()


def test_child_env_has_no_proxy(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("PYTHONPATH", "C:\\evil")
    env = D.child_env()
    assert set(env) <= set(D.PASS_ENV) | {"PYTHONUTF8"}


def test_api_contract(client, monkeypatch):
    st = client.app.state.lb
    monkeypatch.setattr(st.retainer, "status", lambda: {"running": False, "port": 17801, "message": D.MSG_NOT_RUNNING})
    v = ok(client.post("/api/retainer/driver", json={"action": "status"}), "retainer_driver")
    assert v["running"] is False
    r = client.post("/api/retainer/driver", json={"action": "restart"})
    assert r.json()["error"]["code"] == "INVALID_ARGUMENT"
