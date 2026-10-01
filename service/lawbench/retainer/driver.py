"""委托材料的本机证件识别驱动：起、停、查状态（Spec 13.5；契约 api/retainer_driver.schema.json）。

- 用客户端自带的 Python 启动 engines/retainer/tools/ocr-driver/driver.py，只监听 127.0.0.1:17801；
  加 --engine rapidocr：不让它在 RapidOCR 起不来时退到 PaddleOCR（PaddleOCR 首次运行会联网下模型）。
- 启动前核对驱动自带的三个模型文件的 sha256（与驱动自己的 default_models.yaml 一致）：缺失或损坏时驱动会
  自己去 modelscope.cn 重新下载，所以这种情况下不启动，提示重装（Spec 14.1"运行时不下载任何东西"）。
- 子进程环境清空、只传运行必需的变量（不传代理）；驱动的输出丢弃（它的访问日志可能带文件名），不写日志。
- 端口已被占用：探测 /health，是驱动就复用，不是就不启动并说明。复用的驱动多半是本产品上次运行起的
  （服务崩溃或被结束后留下）：stop 时核对监听该端口的进程命令行确是本产品的 ocr-driver/driver.py，
  就连同子进程一起结束（T25 复核 A-P2-2）；核对不上就不动，并如实返回 running:true。
- 服务退出（Starlette lifespan）时 close()，与 stop 相同。
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

from .. import logs, procs
from ..config import REPO_ROOT
from ..errors import ApiError

DRIVER_DIR = REPO_ROOT / "engines" / "retainer" / "tools" / "ocr-driver"
HOST, PORT = "127.0.0.1", 17801
READY_TIMEOUT_S = 20.0
PASS_ENV = ("SYSTEMROOT", "LOCALAPPDATA", "USERPROFILE", "TEMP", "TMP")

MSG_RUNNING = "证件识别已就绪"
MSG_REUSED = "证件识别已就绪（沿用已在运行的驱动）"
MSG_STOPPED = "证件识别已关闭"
MSG_NOT_OURS = "端口 17801 上的证件识别不是本程序启动的，未关闭"
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
        """停自己起的进程；端口上还有复用来的驱动时，核对确是本产品的驱动再停。返回停之后的真实状态。"""
        self._terminate()
        h = self._health()
        if h is None:
            return self._value(False, MSG_STOPPED)
        if is_driver(h):
            pid = _listener_pid(self.port)
            if pid and _is_our_driver(pid, self.driver_dir):
                procs.kill_tree(_Pid(pid))
                if self._wait_port_free():
                    return self._value(False, MSG_STOPPED)
            return self._value(True, MSG_NOT_OURS)
        return self._value(False, MSG_STOPPED)                      # 端口上是别的程序：驱动本身没在跑

    def close(self) -> None:
        """服务退出时调用。"""
        with self._lock:
            try:
                self.stop()
            except Exception as e:  # noqa: BLE001 退出时尽力而为，不挡服务退出
                logs.event("retainer", "driver_close", status="fail", error=type(e).__name__)

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
        procs.kill_tree(p)
        self._wait_port_free()

    def _wait_port_free(self, seconds: float = 5.0) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._health() is None:
                return True
            time.sleep(0.1)
        return False


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


class _Pid:
    """procs.kill_tree 只用到 pid / poll / wait；复用来的驱动没有 Popen 对象，用这个顶上。"""

    def __init__(self, pid: int):
        self.pid = pid

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0

    def kill(self):
        if os.name != "nt":
            os.kill(self.pid, 9)


def _listener_pid(port: int) -> int | None:
    """监听 127.0.0.1:<port> 的进程号（netstat -ano）。"""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1] == f"{HOST}:{port}" and parts[3].upper() == "LISTENING":
            return int(parts[4]) if parts[4].isdigit() else None
    return None


def _is_our_driver(pid: int, driver_dir: pathlib.Path) -> bool:
    """进程命令行里有本产品的 ocr-driver/driver.py（按完整路径比，不认别处的同名脚本）。"""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                              f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"],
                             capture_output=True, text=True, timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    want = str((driver_dir / "driver.py").resolve()).casefold()
    return want in out.casefold()
