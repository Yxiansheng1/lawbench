"""跨线小项（2026-10-02 10:17 令，T20 打包配合）：
1. 转换程序探测先读 LAWBENCH_SOFFICE（pandoc 的 LAWBENCH_PANDOC 见 test_export）；
2. 服务起的所有 Python 子进程都带 PYTHONNOUSERSITE=1：发票引擎、证件识别驱动、Word / WPS 转换子进程、
   LibreOffice（自带 Python）——用各自的环境真起一个 Python，断言 sys.flags.no_user_site == 1。
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

from lawbench import procs
from lawbench.ingest import libreoffice as lo
from lawbench.invoice import runner as invoice_runner
from lawbench.office import convert
from lawbench.retainer import driver


def test_find_soffice_env_first(tmp_path, monkeypatch):
    exe = tmp_path / "tools" / "soffice.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"x")
    monkeypatch.setenv("LAWBENCH_SOFFICE", str(exe))
    assert lo.find_soffice() == str(exe)
    monkeypatch.delenv("LAWBENCH_SOFFICE")
    expected = lo.find_soffice()
    monkeypatch.setenv("LAWBENCH_SOFFICE", str(tmp_path / "没有" / "soffice.exe"))   # 设了但文件不在：照旧往下找
    assert lo.find_soffice() == expected


class _Settings:
    def get(self):
        return {"office": {"invoice_buyer": None}}


def _no_user_site(env: dict) -> str:
    env = dict(env)
    env.setdefault("SYSTEMROOT", __import__("os").environ.get("SYSTEMROOT", ""))
    out = subprocess.run([sys.executable, "-c", "import sys; print(sys.flags.no_user_site)"], env=env,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


@pytest.mark.parametrize("name,make", [
    ("发票引擎", lambda tmp: invoice_runner.InvoiceRunner(_Settings(), tmp).env()),
    ("证件识别驱动", lambda tmp: driver.child_env()),
    ("Word / WPS 转换子进程", lambda tmp: convert.worker_env()),
])
def test_python_children_no_user_site(name, make, tmp_path):
    env = make(tmp_path)
    assert env["PYTHONNOUSERSITE"] == "1", name
    assert _no_user_site(env) == "1", name


def test_python_env_helper():
    assert procs.python_env({"A": "1"}) == {"A": "1", "PYTHONNOUSERSITE": "1"}


def test_libreoffice_env_has_no_user_site(monkeypatch, tmp_path):
    """LibreOffice 自带 Python（宏、过滤器）：启动环境同样带上。"""
    seen = {}

    class P:
        def __init__(self, args, **kw):
            seen.update(kw["env"])
            raise OSError("stop")
    monkeypatch.setattr(lo.subprocess, "Popen", P)
    src = tmp_path / "a.docx"
    src.write_bytes(b"PK\x03\x04")
    with pytest.raises(Exception):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="lblo-") as lb:
            with lo.Converter(tmp_path / "t", pathlib.Path(lb), soffice="soffice.exe").session() as s:
                s.convert(src, "pdf")
    assert seen.get("PYTHONNOUSERSITE") == "1"
