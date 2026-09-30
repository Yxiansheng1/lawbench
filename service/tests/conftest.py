"""共用夹具：临时应用数据目录、带令牌的测试客户端、跑在 127.0.0.1 随机端口上的假服务器。"""
from __future__ import annotations

import contextlib
import os
import pathlib
import shutil
import socket
import tempfile
import sys
import threading
import time
import warnings

import pytest
import uvicorn
from starlette.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from lawbench import logs  # noqa: E402
from lawbench.app import create_app  # noqa: E402
from lawbench.case import gate  # noqa: E402
from lawbench.config import REPO_ROOT, Config  # noqa: E402

TOKEN = "t" * 43
AUTH = {"Authorization": f"Bearer {TOKEN}"}
IS_WIN = os.name == "nt"


@pytest.fixture(autouse=True)
def _no_real_sync_folders(monkeypatch):
    """测试不受开发机真实 OneDrive 设置影响；需要时各测试自己设。"""
    for v in gate.SYNC_ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(gate, "_registry_onedrive_folders", lambda: [])
    yield
    logs.close()


def remove_reported(p: pathlib.Path) -> None:
    """删测试建的目录；删不干净时发警告报出来，不静默（T5 返修 Y3）。"""
    failed: list[str] = []
    shutil.rmtree(p, onexc=lambda _f, path, _e: failed.append(path))
    if failed or p.exists():
        warnings.warn(f"测试目录没删干净：{p}（{len(failed)} 处删除失败）", stacklevel=2)


@contextlib.contextmanager
def short_dir(prefix: str):
    """系统临时目录下的短路径目录（每次新建、用完删除并报告删除失败）。LibreOffice 配置目录路径不能超过 100 字符，
    测试在很深的 --basetemp 下跑时只能放这里（真实环境是 %APPDATA%\\lawbench，也很短）。"""
    p = pathlib.Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield p
    finally:
        logs.close()
        remove_reported(p)


@pytest.fixture
def appdata() -> pathlib.Path:
    """应用数据目录放在系统临时目录下的短路径里：LibreOffice 配置目录（<应用数据>\\临时\\lo\\…）仍不超过 100 字符。"""
    with short_dir("lbad-") as p:
        yield p


@pytest.fixture
def lo_base(appdata) -> pathlib.Path:
    """直接用 Converter 的测试：配置目录的上级和产品一样放在 <应用数据>/临时/lo（lo_base 必填，Y1）。"""
    return appdata / "临时" / "lo"


@pytest.fixture
def cases_dir(tmp_path) -> pathlib.Path:
    p = tmp_path / "cases"
    p.mkdir()
    return p


def servers(primary_llm: str, alt_llm: str | None, primary_prep: str, alt_prep: str | None) -> dict:
    return {"llm_base_url": primary_llm, "llm_alt_base_url": alt_llm,
            "prep_base_url": primary_prep, "prep_alt_base_url": alt_prep}


@pytest.fixture
def make_client(appdata):
    made: list[TestClient] = []

    def _make(skills_dirs=None, key=None, **kw) -> TestClient:
        cfg = Config(token=TOKEN, appdata=appdata, skills_dirs=skills_dirs or [REPO_ROOT / "skills"],
                     contracts_dir=REPO_ROOT / "contracts", **kw)
        app = create_app(cfg, key_getter=lambda: key)
        c = TestClient(app, raise_server_exceptions=False)
        c.headers.update(AUTH)
        made.append(c)
        return c

    yield _make
    for c in made:
        c.close()


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


# ---------- 真实监听的假服务器 ----------

class ServerThread:
    def __init__(self, app, port: int = 0):
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error",
                                                    access_log=False, lifespan="on", log_config=None))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> "ServerThread":
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if time.monotonic() > deadline or not self.thread.is_alive():
                raise RuntimeError("假服务器没起来")
            time.sleep(0.02)
        self.port = self.server.servers[0].sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        return self

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(10)


def closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def make_junction(link: pathlib.Path, target: pathlib.Path) -> None:
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


def try_symlink(link: pathlib.Path, target: pathlib.Path, is_dir: bool = False) -> bool:
    try:
        os.symlink(target, link, target_is_directory=is_dir)
        return True
    except OSError:
        return False
