"""启动入口 python -m lawbench：真起一个进程，只监听 127.0.0.1，令牌生效，转发端口只有两个路径。"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import httpx
import pytest

from lawbench.config import REPO_ROOT

from conftest import TOKEN, closed_port

SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _wait(url: str, proc: subprocess.Popen) -> httpx.Response:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"服务进程退出，退出码 {proc.returncode}")
        try:
            return httpx.get(url, trust_env=False, timeout=1)
        except httpx.TransportError:
            time.sleep(0.2)
    raise AssertionError("服务 30 秒内没有起来")


@pytest.mark.parametrize("via_env", [False, True])
def test_entrypoint(tmp_path, via_env):
    port, fport = closed_port(), closed_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("LB_")}
    args = [sys.executable, "-m", "lawbench"]
    if via_env:
        env.update(LB_PORT=str(port), LB_TOKEN=TOKEN, LB_APPDATA=str(tmp_path / "ad"), LB_FORWARD_PORT=str(fport))
    else:
        args += ["--port", str(port), "--token", TOKEN, "--appdata", str(tmp_path / "ad"),
                 "--forward-port", str(fport)]
    proc = subprocess.Popen(args, cwd=SERVICE_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        r = _wait(f"http://127.0.0.1:{port}/health", proc)
        want = (REPO_ROOT / "contracts" / "VERSION").read_text(encoding="utf-8").strip()   # 不写死版本号（契约 1.3 起）
        assert r.json() == {"status": "ok", "contract_version": want}
        assert httpx.get(f"http://127.0.0.1:{port}/api/case/recent", trust_env=False).status_code == 401
        r = httpx.get(f"http://127.0.0.1:{port}/api/case/recent", trust_env=False,
                      headers={"Authorization": f"Bearer {TOKEN}"})
        assert r.json() == {"ok": True, "value": {"cases": []}}
        _wait(f"http://127.0.0.1:{fport}/", proc)
        assert httpx.get(f"http://127.0.0.1:{fport}/admin", trust_env=False).status_code == 404
        assert (tmp_path / "ad" / "capsules.json").is_file()  # 首次启动复制默认胶囊配置
    finally:
        proc.terminate()
        out = proc.communicate(timeout=15)[0].decode("utf-8", "replace")
    assert TOKEN not in out


def test_entrypoint_needs_token(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("LB_")}
    p = subprocess.run([sys.executable, "-m", "lawbench", "--port", str(closed_port()), "--appdata",
                        str(tmp_path)], cwd=SERVICE_DIR, env=env, capture_output=True, timeout=60)
    assert p.returncode != 0


def test_listens_on_loopback_only():
    from lawbench.__main__ import _server
    from lawbench.net import LOOPBACK
    assert LOOPBACK == "127.0.0.1"
    assert _server(object(), 0).config.host == "127.0.0.1"
