"""T28 macOS 版的服务端平台分支（令 1424）：Windows 上把 sys.platform 换成 darwin 跑；Windows 原有行为由原用例守着。

真 macOS 上才能验的（进程组整组结束、lsof / ps 的真实输出、LibreOffice.app 真转换）在 GitHub Actions 的 Mac 上跑。
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import types

import pytest

from lawbench import config, procs
from lawbench.case import gate
from lawbench.errors import ApiError
from lawbench.export import pandoc as P
from lawbench.ingest import libreoffice as lo
from lawbench.invoice import runner as R
from lawbench.office import convert as C
from lawbench.retainer import driver as D

FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "tests" / "fixtures"
COMPLAINT = FIXTURES / "closed-01" / "03一审" / "我方文件" / "民事起诉状.docx"


@pytest.fixture
def darwin(monkeypatch, tmp_path_factory):
    tmp_path_factory.getbasetemp()          # 复核 P3-7：先让 pytest 按 Windows 建好临时根目录，再换平台
    monkeypatch.setattr(sys, "platform", "darwin")


@pytest.fixture
def case(tmp_path):
    root = tmp_path / "案件"
    (root / "工作区" / "临时").mkdir(parents=True)
    gate.mkdir_work(str(root), "工作区/临时/j")
    return root


# ---------------------------------------------------------------- Word 转 PDF（令 1424 第 2 条）

def _no_com(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("darwin 下不该碰 Word / WPS 或 Windows 进程快照")
    monkeypatch.setattr(C, "processes", boom)
    monkeypatch.setattr(C.OfficeConverter, "_com", boom)


@pytest.mark.parametrize("choice", ["word", "wps"])
def test_convert_darwin_explicit_word_wps_unavailable(darwin, monkeypatch, case, tmp_path, choice):
    _no_com(monkeypatch)
    monkeypatch.setattr(C.OfficeConverter, "_lo", lambda *a: (_ for _ in ()).throw(AssertionError("不该悄悄换 LibreOffice")))
    with pytest.raises(ApiError) as e:
        C.OfficeConverter(tmp_path).to_pdf(str(case), COMPLAINT, "工作区/临时/j", choice)
    assert e.value.code == "CONVERTER_UNAVAILABLE" and e.value.reason == "darwin_no_com"


@pytest.mark.parametrize("choice", ["auto", "libreoffice"])
def test_convert_darwin_auto_only_libreoffice(darwin, monkeypatch, case, tmp_path, choice):
    _no_com(monkeypatch)
    monkeypatch.setattr(C, "word_has_external", lambda p: (_ for _ in ()).throw(AssertionError("只走 LO 时不查 COM 外链")))
    seen = []

    def fake_lo(self, root, local, sub):
        seen.append(local.name)
        out = local.with_name("out.pdf")
        out.write_bytes(b"%PDF-1.4")
        return out
    monkeypatch.setattr(C.OfficeConverter, "_lo", fake_lo)
    out, used = C.OfficeConverter(tmp_path).to_pdf(str(case), COMPLAINT, "工作区/临时/j", choice)
    assert used == "libreoffice" and seen == ["in.docx"] and out.is_file()


def test_convert_module_imports_without_wintypes(monkeypatch):
    """wintypes 导不进来时（非 Windows 可能如此）模块照样能导入、建出 _PE32。另起一个模块名执行源码，不动已导入的模块。"""
    import importlib.util
    import ctypes
    monkeypatch.setitem(sys.modules, "ctypes.wintypes", None)            # import 这一项时抛 ImportError
    monkeypatch.delattr(ctypes, "wintypes", raising=False)
    spec = importlib.util.spec_from_file_location("lawbench.office._convert_t28", C.__file__)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert isinstance(mod.wintypes, types.SimpleNamespace) and mod._PE32 is not None


# ---------------------------------------------------------------- 转换程序查找

def test_find_soffice_darwin_candidates(darwin, monkeypatch, tmp_path):
    monkeypatch.delenv("LAWBENCH_SOFFICE", raising=False)
    monkeypatch.setattr(lo.shutil, "which", lambda n: None)
    fake = tmp_path / "LibreOffice.app" / "Contents" / "MacOS" / "soffice"
    fake.parent.mkdir(parents=True)
    fake.write_text("")
    monkeypatch.setattr(lo, "MAC_CANDIDATES", [str(fake)])
    monkeypatch.setattr(lo, "CANDIDATES", [str(tmp_path / "不该看" / "soffice.exe")])
    assert lo.find_soffice() == str(fake)


def test_soffice_mac_default_location():
    assert lo.MAC_CANDIDATES == ["/Applications/LibreOffice.app/Contents/MacOS/soffice"]


def test_find_pandoc_darwin_candidates(darwin, monkeypatch, tmp_path):
    monkeypatch.delenv("LAWBENCH_PANDOC", raising=False)
    monkeypatch.setattr(P.shutil, "which", lambda n: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))                 # Windows 位置在 darwin 下不看
    (tmp_path / "Pandoc").mkdir()
    (tmp_path / "Pandoc" / "pandoc.exe").write_text("")
    brew = tmp_path / "homebrew" / "pandoc"
    brew.parent.mkdir()
    monkeypatch.setattr(P, "MAC_CANDIDATES", (str(tmp_path / "没有" / "pandoc"),))
    assert P.find_pandoc() is None
    brew.write_text("")
    monkeypatch.setattr(P, "MAC_CANDIDATES", (str(brew),))
    assert P.find_pandoc() == str(brew)


# ---------------------------------------------------------------- 进程收尾（真整组结束只能在 Mac 上验）

def test_own_group_only_off_windows(monkeypatch):
    monkeypatch.setattr(procs, "os", types.SimpleNamespace(name="nt"))   # 只换 procs 看到的 os，不动全局 os.name（pathlib 依赖它）
    assert procs.own_group() == {}
    monkeypatch.setattr(procs, "os", types.SimpleNamespace(name="posix"))
    assert procs.own_group() == {"start_new_session": True}


def test_kill_tree_darwin_kills_group(darwin, monkeypatch):
    calls = []
    monkeypatch.setattr(procs, "os", types.SimpleNamespace(name="posix", getpgid=lambda pid: pid,
                                                           killpg=lambda pid, sig: calls.append(("killpg", pid))))
    monkeypatch.setattr(procs.signal, "SIGKILL", 9, raising=False)

    class P_:
        pid = 4242
        def poll(self): return None
        def kill(self): calls.append(("kill", self.pid))
        def wait(self, timeout=None): return 0
    procs.kill_tree(P_())
    assert calls == [("killpg", 4242)]


def test_kill_tree_darwin_not_group_leader_falls_back(darwin, monkeypatch):
    monkeypatch.setattr(procs, "os", types.SimpleNamespace(name="posix", getpgid=lambda pid: 1))
    calls = []

    class P_:
        pid = 4242
        def poll(self): return None
        def kill(self): calls.append("kill")
        def wait(self, timeout=None): return 0
    procs.kill_tree(P_())
    assert calls == ["kill"]


# ---------------------------------------------------------------- 证件识别驱动

def test_driver_child_env_darwin(darwin, monkeypatch):
    for k, v in {"HOME": "/Users/x", "TMPDIR": "/var/t", "LANG": "zh_CN.UTF-8", "HTTPS_PROXY": "http://p", "SYSTEMROOT": "C:\\W"}.items():
        monkeypatch.setenv(k, v)
    env = D.child_env()
    assert {k: env[k] for k in ("HOME", "TMPDIR", "LANG")} == {"HOME": "/Users/x", "TMPDIR": "/var/t", "LANG": "zh_CN.UTF-8"}
    assert "HTTPS_PROXY" not in env and "SYSTEMROOT" not in env and env["PYTHONNOUSERSITE"] == "1"


def test_driver_listener_and_cmdline_darwin(darwin, monkeypatch, tmp_path):
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd[0])
        out = "5150\n" if cmd[0].endswith("lsof") else f"/x/python3 {(tmp_path / 'driver.py').resolve()} --port 17801\n"
        return subprocess.CompletedProcess(cmd, 0, stdout=out)
    monkeypatch.setattr(D.subprocess, "run", fake_run)
    assert D._listener_pid(17801) == 5150
    assert D._is_our_driver(5150, tmp_path) is True
    assert D._is_our_driver(5150, tmp_path / "别处") is False
    assert seen[0] == "/usr/sbin/lsof" and "/bin/ps" in seen and "netstat" not in seen and "powershell" not in seen


def test_driver_listener_none_darwin(darwin, monkeypatch):
    monkeypatch.setattr(D.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout=""))
    assert D._listener_pid(17801) is None


# ---------------------------------------------------------------- 发票整理（令 1424 第 1 条）

def test_invoice_darwin_unsupported_no_engine(darwin, monkeypatch, tmp_path):
    monkeypatch.setattr(R.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该起引擎")))

    class S:
        def get(self): return {"office": {"dir": str(tmp_path), "invoice_buyer": "x"}}
    with pytest.raises(ApiError) as e:
        R.InvoiceRunner(S(), tmp_path).run({"action": "history"})
    assert e.value.code == "ENGINE_FAILED" and e.value.message == "Mac 版暂不支持发票整理"


# ---------------------------------------------------------------- 云同步目录（令 1424 第 5 条）与文件名长度

def test_sync_markers_darwin_only(monkeypatch):
    p = "/Users/x/Library/CloudStorage/OneDrive-个人/案件"
    monkeypatch.setattr(gate, "sync_folder_roots", lambda: [])
    monkeypatch.setattr(sys, "platform", "win32")
    assert gate.in_sync_folder(p) is True                                 # 本来就含 OneDrive 字样
    q = "/Users/x/Library/Mobile Documents/com~apple~CloudDocs/案件"
    assert gate.in_sync_folder(q) is False                                # Windows 名单不变
    monkeypatch.setattr(sys, "platform", "darwin")
    assert gate.in_sync_folder(q) is True


def test_mac_sync_roots_documents_desktop(tmp_path):
    assert gate._mac_sync_roots(tmp_path) == [str(tmp_path / "Library" / "Mobile Documents"), str(tmp_path / "Library" / "CloudStorage")]
    (tmp_path / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Documents").mkdir(parents=True)
    roots = gate._mac_sync_roots(tmp_path)
    assert str(tmp_path / "Documents") in roots and str(tmp_path / "Desktop") in roots


def test_sync_roots_include_mac_only_on_darwin(monkeypatch, tmp_path):
    monkeypatch.setattr(gate.pathlib.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(gate, "_registry_onedrive_folders", lambda: [])
    for v in gate.SYNC_ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    assert gate.sync_folder_roots() == []
    monkeypatch.setattr(sys, "platform", "darwin")
    assert str(tmp_path / "Library" / "CloudStorage") in gate.sync_folder_roots()


def test_component_utf8_bytes_darwin(monkeypatch):
    name = "案" * 90                       # 90 字符 / 270 字节
    monkeypatch.setattr(sys, "platform", "win32")
    assert gate.check_ai_rel(f"材料/{name}.md")
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(gate.GateError):
        gate.check_ai_rel(f"材料/{name}.md")
    assert gate.check_ai_rel(f"材料/{'案' * 80}.md")                    # 243 字节，放得下


# ---------------------------------------------------------------- 应用数据目录

def test_default_appdata_darwin(darwin, monkeypatch, tmp_path):
    monkeypatch.setattr(config.pathlib.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "不该用"))
    assert config._default_appdata() == tmp_path / "Library" / "Application Support" / "lawbench"


# ---------------------------------------------------------------- 子进程自成进程组（复核 P3-3）

class _Exited:
    pid = 1
    returncode = 1
    def poll(self): return 1
    def wait(self, timeout=None): return 1
    def kill(self): pass


def test_libreoffice_popen_gets_own_group_off_windows(darwin, monkeypatch, tmp_path):
    from conftest import short_dir
    monkeypatch.setattr(procs, "os", types.SimpleNamespace(name="posix"))
    seen = {}

    def fake_popen(args, **kw):
        seen.update(kw)
        raise OSError("stop here")
    monkeypatch.setattr(lo.subprocess, "Popen", fake_popen)
    src = tmp_path / "a.docx"
    src.write_bytes(b"x")
    (tmp_path / "t").mkdir()
    with short_dir("lbt28-") as base:
        with pytest.raises(Exception):
            with lo.Converter(tmp_path / "t", base, soffice="/x/soffice").session() as s:
                s.convert(src, "pdf")
    assert seen.get("start_new_session") is True


def test_driver_popen_gets_own_group_off_windows(darwin, monkeypatch, tmp_path):
    monkeypatch.setattr(procs, "os", types.SimpleNamespace(name="posix"))
    monkeypatch.setattr(D, "models_ok", lambda d: True)
    monkeypatch.setattr(D.RetainerDriver, "_health", lambda self: None)
    monkeypatch.setattr(D.RetainerDriver, "_port_taken", lambda self: False)
    seen = {}

    def fake_popen(cmd, **kw):
        seen.update(kw)
        return _Exited()
    monkeypatch.setattr(D.subprocess, "Popen", fake_popen)
    r = D.RetainerDriver(python="/x/python3", driver_dir=tmp_path, ready_timeout_s=0.5).start()
    assert r["running"] is False and seen.get("start_new_session") is True


def test_own_group_empty_on_windows_popen(monkeypatch, tmp_path):
    monkeypatch.setattr(procs, "os", types.SimpleNamespace(name="nt"))
    assert procs.own_group() == {}
