from __future__ import annotations

import hashlib
import sys
from pathlib import Path

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
    for p in Path(tempfile.gettempdir()).glob("lbt-*"):
        try:
            if p.is_dir() and not p.is_symlink() and not os.path.isjunction(p) and now - p.stat().st_mtime > 600:
                from convert import core
                shutil.rmtree(core.long_form(str(p.resolve())), ignore_errors=True)
        except OSError:
            pass
