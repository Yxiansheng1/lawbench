"""T28 macOS：小工具找 LibreOffice、pandoc 的位置（令 1424 第 4 条）。Windows 上把 sys.platform 换成 darwin 跑。"""
from __future__ import annotations

import sys
from pathlib import Path

from convert import finder


def test_mac_candidates(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("LAWBENCH_SOFFICE", raising=False)
    monkeypatch.delenv("LAWBENCH_PANDOC", raising=False)
    so = [p.as_posix() for p in finder.soffice_candidates()]
    pd = [p.as_posix() for p in finder.pandoc_candidates()]
    app = f"/Applications/{finder.CLIENT_DIR_NAMES[0]}.app/Contents/Resources/tools"
    assert so[0] == f"{app}/LibreOffice.app/Contents/MacOS/soffice"
    assert so[-1] == "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    assert pd[0] == f"{app}/pandoc/bin/pandoc"
    assert "/opt/homebrew/bin/pandoc" in pd
    assert not any(".exe" in p or "Program Files" in p for p in so + pd)


def test_mac_env_first(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("LAWBENCH_SOFFICE", str(tmp_path / "soffice"))
    assert finder.soffice_candidates()[0] == Path(tmp_path / "soffice")


def test_windows_unchanged(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("LAWBENCH_SOFFICE", raising=False)
    assert all(str(p).endswith("soffice.exe") for p in finder.soffice_candidates())
