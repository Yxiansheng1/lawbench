"""委托材料的本机证件识别驱动：起、停、查状态（Spec 13.5；契约 api/retainer_driver.schema.json）。

- 用客户端自带的 Python 启动 engines/retainer/tools/ocr-driver/driver.py，只监听 127.0.0.1:17801；
  加 --engine rapidocr：不让它在 RapidOCR 起不来时退到 PaddleOCR（PaddleOCR 首次运行会联网下模型）。
- 启动前核对驱动自带的三个模型文件的 sha256（与驱动自己的 default_models.yaml 一致）：缺失或损坏时驱动会
  自己去 modelscope.cn 重新下载，所以这种情况下不启动，提示重装（Spec 14.1"运行时不下载任何东西"）。
- 子进程环境清空、只传运行必需的变量（不传代理）；驱动的输出丢弃（它的访问日志可能带文件名），不写日志。
- 端口已被占用：探测 /health，是驱动就复用（不归我们停），不是就不启动并说明。
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import subprocess
import sys
import threading
import time

import httpx

from .. import logs
from ..config import REPO_ROOT
from ..errors import ApiError

DRIVER_DIR = REPO_ROOT / "engines" / "retainer" / "tools" / "ocr-driver"
HOST, PORT = "127.0.0.1", 17801
READY_TIMEOUT_S = 20.0
PASS_ENV = ("SYSTEMROOT", "LOCALAPPDATA", "USERPROFILE", "TEMP", "TMP")

MSG_RUNNING = "证件识别已就绪"
MSG_REUSED = "证件识别已就绪（沿用已在运行的驱动）"
MSG_STOPPED = "证件识别已关闭"
MSG_NOT_RUNNING = "证件识别未运行"
MSG_PORT_TAKEN = "端口 17801 被其他程序占用，证件识别无法启动；委托材料的其他功能不受影响"
MSG_START_FAILED = "证件识别启动失败；委托材料的其他功能不受影响，可手工填写"


class RetainerDriver:
    def __init__(self, python: str | None = None, driver_dir: pathlib.Path = DRIVER_DIR, port: int = PORT,
                 ready_timeout_s: float = READY_TIMEOUT_S):
        self.python = python or sys.executable
        self.driver_dir = pathlib.Path(driver_dir)
        self.port = port
        self.ready_timeout_s = ready_timeout_s
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def handle(self, req: dict) -> dict:
        action = req["action"]
        t0 = time.monotonic()
        with self._lock:
            value = {"start": self.start, "stop": self.stop, "status": self.status}[action]()
        logs.event("retainer", f"driver_{action}", status="ok" if value["running"] or action == "stop" else "fail",
                   duration_ms=(time.monotonic() - t0) * 1000)
        return value

    # ---------------------------------------------------------------- 动作

    def status(self) -> dict:
        h = self._health()
        running = bool(h and h.get("ready"))
        return self._value(running, MSG_RUNNING if running else MSG_NOT_RUNNING)

    def start(self) -> dict:
        if self._proc is not None and self._proc.poll() is None:
            h = self._health()
            if h and h.get("ready"):
                return self._value(True, MSG_RUNNING)
        h = self._health()
        if h is not None:                                           # 端口上已有东西在听
            if is_driver(h):
                return self._value(bool(h.get("ready")), MSG_REUSED if h.get("ready") else MSG_START_FAILED)
            return self._value(False, MSG_PORT_TAKEN)
        if self._port_taken():
            return self._value(False, MSG_PORT_TAKEN)
        if not models_ok(self.driver_dir):
            # 模型缺失或损坏时驱动会自己联网重下：不启动，报 ENGINE_FAILED（1701 令 P11）
            raise ApiError("ENGINE_FAILED", "driver_models")
        cmd = [self.python, str(self.driver_dir / "driver.py"), "--port", str(self.port), "--host", HOST,
               "--engine", "rapidocr"]
        self._proc = subprocess.Popen(cmd, cwd=str(self.driver_dir), env=child_env(), stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + self.ready_timeout_s
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                break
            h = self._health()
            if h and is_driver(h) and h.get("ready"):
                return self._value(True, MSG_RUNNING)
            time.sleep(0.3)
        self._terminate()
        return self._value(False, MSG_START_FAILED)

    def stop(self) -> dict:
        """只停自己起的进程；复用的别人起的驱动不动。"""
        if self._proc is None or self._proc.poll() is not None:
            self._proc = None
            return self._value(False, MSG_STOPPED)
        self._terminate()
        return self._value(False, MSG_STOPPED)

    def close(self) -> None:
        with self._lock:
            self._terminate()

    # ---------------------------------------------------------------- 内部

    def _value(self, running: bool, message: str) -> dict:
        return {"running": running, "port": PORT, "message": message}

    def _health(self) -> dict | None:
        try:
            r = httpx.get(f"http://{HOST}:{self.port}/health", timeout=1.0, follow_redirects=False,
                          trust_env=False)                            # 不读代理环境变量
            return r.json() if r.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return None

    def _port_taken(self) -> bool:
        import socket
        s = socket.socket()
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s.bind((HOST, self.port))
            return False
        except OSError:
            return True
        finally:
            s.close()

    def _terminate(self) -> None:
        """连子进程一起结束（Windows 上虚拟环境的 python.exe 只是启动器，真正的解释器是它的子进程），
        再等端口真正放开，免得紧接着的 start 误判"已在运行"。"""
        p, self._proc = self._proc, None
        if p is None:
            return
        if p.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and self._health() is not None:
            time.sleep(0.1)


def is_driver(h: dict) -> bool:
    """驱动 /health 的特征：ok、offline=true、有 engine 与 maxBytes 字段（driver.py do_GET）。"""
    return isinstance(h, dict) and h.get("ok") is True and h.get("offline") is True and "engine" in h \
        and "maxBytes" in h


def child_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in PASS_ENV if os.environ.get(k)}
    env["PYTHONUTF8"] = "1"
    return env


def expected_models(driver_dir: pathlib.Path) -> dict[str, str]:
    """驱动自己的 default_models.yaml：文件名 → 期望 sha256（按 model_dir 地址的文件名对应）。"""
    text = (driver_dir / "vendor" / "rapidocr" / "default_models.yaml").read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for m in re.finditer(r"model_dir:\s*(\S+)\s*\n\s*SHA256:\s*([0-9a-f]{64})", text):
        out.setdefault(m.group(1).rsplit("/", 1)[-1], m.group(2))
    return out


def models_ok(driver_dir: pathlib.Path) -> bool:
    models = driver_dir / "vendor" / "rapidocr" / "models"
    try:
        want = expected_models(driver_dir)
        files = sorted(models.glob("*.onnx"))
        if len(files) < 3:
            return False
        for f in files:
            if want.get(f.name) != hashlib.sha256(f.read_bytes()).hexdigest():
                return False
        return True
    except OSError:
        return False
