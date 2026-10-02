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

import importlib.util

# 起真驱动的用例要 onnxruntime 等（service 的 [retainer] 依赖组）；没装的解释器上跳过并写明原因
needs_ort = pytest.mark.skipif(importlib.util.find_spec("onnxruntime") is None,
                               reason="本解释器没装证件识别驱动的依赖（pip install .[retainer]）")

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


@needs_ort
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


@needs_ort
def test_restart_reuses_then_stop_really_stops(drv):
    """模拟服务重启：新实例 start 复用上次留下的驱动；stop 核对确是本产品的驱动后真的停掉、端口放开（A-P2-2）。"""
    assert drv.start()["running"] is True
    fresh = D.RetainerDriver(port=drv.port)                         # 重启后的服务：内存里没有那个进程
    assert fresh.start() == {"running": True, "port": 17801, "message": D.MSG_REUSED}
    assert fresh.stop() == {"running": False, "port": 17801, "message": D.MSG_STOPPED}
    assert fresh.status()["running"] is False and not listening(drv.port)
    assert drv._proc.poll() is not None                              # 原进程确实结束了


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
    assert set(env) <= set(D.PASS_ENV) | {"PYTHONUTF8", "PYTHONNOUSERSITE"} and env["PYTHONNOUSERSITE"] == "1"


def test_api_contract(client, monkeypatch):
    st = client.app.state.lb
    monkeypatch.setattr(st.retainer, "status", lambda: {"running": False, "port": 17801, "message": D.MSG_NOT_RUNNING})
    v = ok(client.post("/api/retainer/driver", json={"action": "status"}), "retainer_driver")
    assert v["running"] is False
    r = client.post("/api/retainer/driver", json={"action": "restart"})
    assert r.json()["error"]["code"] == "INVALID_ARGUMENT"



def test_driver_command_has_engine_rapidocr(monkeypatch):
    """起驱动的命令固定带 --engine rapidocr（RapidOCR 起不来时不退到会联网下模型的 PaddleOCR）。"""
    seen = {}

    class Dead:
        pid = 0

        def poll(self):
            return 1

        def wait(self, timeout=None):
            return 1

    def fake_popen(cmd, **kw):
        seen["cmd"] = cmd
        return Dead()
    monkeypatch.setattr(D.subprocess, "Popen", fake_popen)
    d = D.RetainerDriver(port=free_port(), ready_timeout_s=0.5)
    assert d.start()["running"] is False
    cmd = seen["cmd"]
    assert cmd[cmd.index("--engine") + 1] == "rapidocr"
    assert cmd[cmd.index("--host") + 1] == "127.0.0.1"


def test_stop_leaves_lookalike_that_is_not_ours(drv):
    """端口上有个长得像驱动的 HTTP 服务、但不是本产品的 driver.py：stop 不动它，如实返回 running:true。"""
    import json as _json

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(_json.dumps({"ok": True, "offline": True, "engine": "x", "maxBytes": 1,
                                          "ready": True}).encode())

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", drv.port), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        assert drv.stop() == {"running": True, "port": 17801, "message": D.MSG_NOT_OURS}
        assert listening(drv.port)
    finally:
        srv.shutdown()
        srv.server_close()



def test_lifespan_exit_closes_driver(appdata, monkeypatch):
    """服务退出（Starlette lifespan 结束）时调一次 st.retainer.close()（把它换成 pass 会让本用例变红）。"""
    from starlette.testclient import TestClient
    from lawbench.app import create_app
    from lawbench.config import Config
    app = create_app(Config(token="t" * 43, appdata=appdata), key_getter=lambda: None)
    calls = []
    monkeypatch.setattr(app.state.lb.retainer, "close", lambda: calls.append(1))
    with TestClient(app):
        assert calls == []
    assert calls == [1]


def test_stop_ours_but_port_not_freed(drv, monkeypatch, tmp_path):
    """确认是本产品的驱动、已结束进程树，但 5 秒内端口没放开：如实 running:true、"关闭未完成"，日志记失败。"""
    from lawbench import logs
    monkeypatch.setattr(drv, "_health", lambda: {"ok": True, "offline": True, "engine": "rapidocr",
                                                  "maxBytes": 1, "ready": True})
    monkeypatch.setattr(D, "_listener_pid", lambda port: 4242)
    monkeypatch.setattr(D, "_is_our_driver", lambda pid, d: True)
    killed = []
    monkeypatch.setattr(D.procs, "kill_tree", lambda p, drain=False: killed.append(p.pid))
    monkeypatch.setattr(drv, "_wait_port_free", lambda seconds=5.0: False)
    log_dir = logs.setup(tmp_path)
    v = drv.handle({"action": "stop"})
    logs.close()
    assert v == {"running": True, "port": 17801, "message": D.MSG_STOP_PENDING} and killed == [4242]
    line = (log_dir / "service.log").read_text(encoding="utf-8")
    assert '"status": "fail"' in line and '"error": "stop_pending"' in line
