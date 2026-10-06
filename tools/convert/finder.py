"""查找 LibreOffice（soffice.exe）和 pandoc（Spec 13、14.1：小工具复用已安装客户端的那份，没有再自带或用系统的）。

查找顺序：
1. 环境变量 LAWBENCH_SOFFICE / LAWBENCH_PANDOC（调试或特殊部署时指定）；
2. 小工具所在的同一安装（打包后 exe 在 <安装目录>\\tools\\<工具>\\，同包的 LibreOffice、pandoc 在上一级 tools\\ 下，
   装到哪个目录都找得到）；再是默认安装位置的内置路径（按当前用户安装：%LOCALAPPDATA%\\Programs\\<客户端目录>\\tools\\libreoffice\\program\\soffice.exe、
   …\\tools\\pandoc\\pandoc.exe；T20 打包布局，载荷在 exe 旁）；
3. 小工具自带的一份（打包后程序所在目录下的 libreoffice\\、pandoc\\）；
4. 系统安装（Program Files、pandoc 默认的 %LOCALAPPDATA%\\Pandoc）和 PATH。
都找不到时返回 None，由调用方给出中文提示。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# 客户端安装目录名（electron-builder 按当前用户装到 %LOCALAPPDATA%\Programs\<产品名>）。软件名称未定，
# 第一个是占位名（同 dsh\apps\desktop\scripts\lawbench-product.mjs，候 owner N58），定了在这里对齐。
CLIENT_DIR_NAMES = ["连越律师工作台", "lawbench", "律师工作台"]

MISSING = {
    "soffice": "没有找到 LibreOffice。请先安装律师工作台客户端（其中自带 LibreOffice），或安装 LibreOffice 后重试。",
    "pandoc": "没有找到 pandoc。请先安装律师工作台客户端（其中自带 pandoc），或安装 pandoc 后重试。",
}


def _env(name: str) -> Path | None:
    v = os.environ.get(name)
    return Path(v) if v else None


def _client_roots() -> list[Path]:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return []
    return [Path(local) / "Programs" / n / "tools" for n in CLIENT_DIR_NAMES]


def _own_install_tools() -> list[Path]:
    """打包后小工具在 <安装目录>\\tools\\convert\\convert.exe：同一安装的 tools\\ 就是它上一级（装到非默认目录也找得到，
    T20 候选包复核 P3-5、令 2033）。开发期不是打包程序，不用这一项。"""
    if not getattr(sys, "frozen", False):
        return []
    return [Path(sys.executable).resolve().parent.parent]


def _bundled_root() -> Path:
    # PyInstaller 打包后 sys.executable 是小工具本身；开发时是 python.exe，不会命中
    return Path(sys.executable).resolve().parent


def _mac_client_tools() -> list[Path]:
    """T28 macOS（令 1424 第 4 条）：小工具是 dmg 里与主程序并排的独立 .app，拖进"应用程序"后按
    /Applications/<客户端>.app/Contents/Resources/tools 找主程序带的 LibreOffice、pandoc。"""
    return [Path("/Applications") / f"{n}.app" / "Contents" / "Resources" / "tools" for n in CLIENT_DIR_NAMES]


def _mac_soffice_candidates() -> list[Path]:
    c: list[Path | None] = [_env("LAWBENCH_SOFFICE")]
    c += [r / "LibreOffice.app" / "Contents" / "MacOS" / "soffice" for r in _mac_client_tools()]
    c.append(Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"))
    return [p for p in c if p]


def _mac_pandoc_candidates() -> list[Path]:
    c: list[Path | None] = [_env("LAWBENCH_PANDOC")]
    c += [r / "pandoc" / "bin" / "pandoc" for r in _mac_client_tools()]
    c += [Path("/opt/homebrew/bin/pandoc"), Path("/usr/local/bin/pandoc")]
    return [p for p in c if p]


def soffice_candidates() -> list[Path]:
    if sys.platform == "darwin":
        return _mac_soffice_candidates()
    c: list[Path | None] = [_env("LAWBENCH_SOFFICE")]
    c += [r / "libreoffice" / "program" / "soffice.exe" for r in _own_install_tools() + _client_roots()]
    c.append(_bundled_root() / "libreoffice" / "program" / "soffice.exe")
    for pf in (os.environ.get("ProgramFiles", r"C:\Program Files"),
               os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        c.append(Path(pf) / "LibreOffice" / "program" / "soffice.exe")
    return [p for p in c if p]


def pandoc_candidates() -> list[Path]:
    if sys.platform == "darwin":
        return _mac_pandoc_candidates()
    c: list[Path | None] = [_env("LAWBENCH_PANDOC")]
    c += [r / "pandoc" / "pandoc.exe" for r in _own_install_tools() + _client_roots()]
    c.append(_bundled_root() / "pandoc" / "pandoc.exe")
    if os.environ.get("LOCALAPPDATA"):
        c.append(Path(os.environ["LOCALAPPDATA"]) / "Pandoc" / "pandoc.exe")
    c.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Pandoc" / "pandoc.exe")
    return [p for p in c if p]


def _first(cands: list[Path], exe: str) -> Path | None:
    for p in cands:
        if p.is_file():
            return p
    w = shutil.which(exe)
    return Path(w) if w else None


def find_soffice() -> Path | None:
    return _first(soffice_candidates(), "soffice")


def find_pandoc() -> Path | None:
    return _first(pandoc_candidates(), "pandoc")
