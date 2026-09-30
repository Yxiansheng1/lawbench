from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parent
FIXTURES = REPO / "tests" / "fixtures"
SAMPLES = TOOLS / "splitter" / "samples"
sys.path.insert(0, str(TOOLS))


def sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def pytest_sessionstart(session):
    """上次测试被强行中断时可能在真实系统临时目录里留下 lbt-* 目录：开跑前清掉超过 10 分钟的（只删本测试前缀的顶层目录）。"""
    import os
    import shutil
    import tempfile
    import time
    now = time.time()
    for p in [*Path(tempfile.gettempdir()).glob("lbt-*"), *Path(tempfile.gettempdir()).glob("lbp-*")]:
        try:
            if p.is_dir() and not p.is_symlink() and not os.path.isjunction(p) and now - p.stat().st_mtime > 600:
                from convert import core
                shutil.rmtree(core.long_form(str(p.resolve())), ignore_errors=True)
        except OSError:
            pass


REAL_TEMP = tempfile.gettempdir()


@pytest.fixture(scope="session", autouse=True)
def short_profile_root():
    """整个测试会话：LibreOffice 配置目录的上级指到真实系统临时目录下的短路径（lbp-*，测完删除），
    不往真实的 %LOCALAPPDATA%\\lawbench\\lo 里建东西；会话级，才能先于模块级的样本 fixture 生效。
    不改 LOCALAPPDATA 本身（pandoc 的查找要用它）。返回产品里原来的 profile_root，供需要它的测试使用。"""
    import shutil
    from convert import core
    root = Path(tempfile.mkdtemp(prefix="lbp-", dir=REAL_TEMP)) / "lo"
    original = core.profile_root
    mp = pytest.MonkeyPatch()
    mp.setattr(core, "profile_root", lambda: root)
    yield original
    mp.undo()
    shutil.rmtree(core.long_form(str(root.parent)), ignore_errors=True)
