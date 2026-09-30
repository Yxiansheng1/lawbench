"""不落盘与日志（Spec 6.2、6.6）：处理 50 张图片后临时目录和服务目录没有新文件；日志只有元数据。"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from conftest import FIXTURES, GOOD, auth, scan_pages, to_bytes
from prep395.app import create_app
from prep395.backends import FakeBackend
from prep395.config import TEMP_PREFIX
from prep395.logs import FIELDS

sys.path.insert(0, str(FIXTURES / "_gen"))
import case_criminal01  # noqa: E402  渲染前的扫描页文字，用来检查日志里有没有泄露


class WriteAudit:
    """用审计钩子记录"以写方式打开文件"和 tempfile 建临时文件的事件，能抓到写了又删掉的文件。"""

    WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

    def __init__(self, allow: list[Path]) -> None:
        self.allow = [str(p).lower() for p in allow]
        self.events: list[str] = []
        self.active = False
        sys.addaudithook(self._hook)        # 审计钩子不能撤销，用 active 开关控制记录范围

    def _hook(self, event, args):
        if not self.active:
            return
        if event in ("tempfile.mkstemp", "tempfile.mkdtemp"):
            self.events.append(f"{event} {args}")
        elif event == "open":
            path, mode, flags = (list(args) + [None, None])[:3]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or                 (isinstance(flags, int) and flags & self.WRITE_FLAGS)
            if writing and isinstance(path, (str, bytes, os.PathLike)):
                p = os.fsdecode(path).lower()
                if not any(p == a or p.startswith(a + os.sep) for a in self.allow):
                    self.events.append(f"open {p} {mode} {flags}")


_AUDIT: WriteAudit | None = None


def snapshot(d):
    return sorted(p.relative_to(d).as_posix() for p in d.rglob("*"))


def test_fifty_images_leave_no_files(settings, isolated_tmp):
    pages = [to_bytes(p) for p in scan_pages()]
    jpg = (FIXTURES / "criminal-01" / "转账截图.jpg").read_bytes()
    home = settings.home
    global _AUDIT
    if _AUDIT is None:
        _AUDIT = WriteAudit([])
    _AUDIT.allow = [str(settings.log_dir).lower()]
    _AUDIT.events = []
    with TestClient(create_app(settings, FakeBackend())) as c:
        before_tmp, before_home = snapshot(isolated_tmp), snapshot(home)
        _AUDIT.active = True
        for i in range(50):
            if i % 4 == 3:
                body, ctype = jpg, "image/jpeg"
            else:
                body, ctype = pages[i % 3], "image/png"
            q = "?dewatermark=true&return_image=true" if i % 2 else ""
            r = c.post("/v1/ocr/page" + q, content=body, headers={**auth(), "Content-Type": ctype})
            assert r.status_code == 200
        r = c.post("/v1/extract", json={"task": "classify", "text": "讯问笔录", "categories": ["讯问笔录", "其他"]},
                   headers=auth())
        assert r.status_code == 200
        _AUDIT.active = False
        after_tmp, after_home = snapshot(isolated_tmp), snapshot(home)
    assert _AUDIT.events == [], _AUDIT.events[:5]          # 请求期间没有写文件、没有建临时文件
    assert after_tmp == before_tmp == []
    assert after_home == before_home == ["logs", "logs/access.log"]


def test_log_has_only_metadata(settings):
    pages = [to_bytes(p) for p in scan_pages()]
    with TestClient(create_app(settings, FakeBackend())) as c:
        for p in pages:
            c.post("/v1/ocr/page?dewatermark=true", content=p, headers={**auth(), "Content-Type": "image/png"})
        c.post("/v1/ocr/page", content=b"junk", headers={**auth("wrong-key"), "Content-Type": "image/png"})
        c.post("/v1/extract", json={"task": "fields", "text": "【第1页】张某甲于2025年3月10日转账80,000元",
                                    "fields": ["日期", "金额"]}, headers=auth())
    text = (settings.log_dir / "access.log").read_text(encoding="utf-8")
    lines = [json.loads(x) for x in text.splitlines()]
    assert len(lines) >= 6
    for rec in lines:
        assert tuple(rec) == FIELDS
        assert rec["key"] is None or re.fullmatch(r"[0-9a-f]{8}", rec["key"])
        assert rec["err"] is None or re.fullmatch(r"[A-Za-z_]+", rec["err"])
    # 不含 Key 原文、图片里的任何文字、识别结果、抽取文本
    assert GOOD not in text and "wrong-key" not in text
    source = "".join(case_criminal01.XUNWEN)
    for i in range(0, len(source) - 4, 3):
        frag = source[i:i + 4]
        if re.search(r"[一-鿿]{2}", frag):
            assert frag not in text, frag
    for s in ("LBFX", "张某甲", "80,000", "2025年3月10日", "测试后端输出", "看不清"):
        assert s not in text


def test_startup_cleanup_only_own_top_level_files(settings, isolated_tmp, tmp_path):
    """只删系统临时目录和 <HOME>/tmp/ 顶层的 prep395- 普通文件；目录、链接、服务目录里的其他文件都不动。"""
    import subprocess
    (isolated_tmp / f"{TEMP_PREFIX}leftover.png").write_bytes(b"x")
    (isolated_tmp / "other-program.tmp").write_bytes(b"x")
    (isolated_tmp / f"{TEMP_PREFIX}somedir").mkdir()
    (isolated_tmp / f"{TEMP_PREFIX}somedir" / "keep.txt").write_bytes(b"x")
    home = settings.home
    (home / "tmp").mkdir(parents=True)
    (home / "tmp" / f"{TEMP_PREFIX}crash.bin").write_bytes(b"x")
    dist = home / f"{TEMP_PREFIX}1.0.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_bytes(b"x")
    (home / f"{TEMP_PREFIX}ocr.xml").write_bytes(b"<service/>")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / f"{TEMP_PREFIX}victim.txt").write_bytes(b"x")
    for link in (home / f"{TEMP_PREFIX}junction", home / "tmp" / f"{TEMP_PREFIX}junction"):
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
    with TestClient(create_app(settings, FakeBackend())):
        pass
    assert sorted(p.name for p in isolated_tmp.iterdir()) == ["other-program.tmp", f"{TEMP_PREFIX}somedir"]
    assert (isolated_tmp / f"{TEMP_PREFIX}somedir" / "keep.txt").exists()
    assert not (home / "tmp" / f"{TEMP_PREFIX}crash.bin").exists()
    assert (dist / "METADATA").exists() and (home / f"{TEMP_PREFIX}ocr.xml").exists()
    assert (outside / f"{TEMP_PREFIX}victim.txt").exists()
    assert (home / f"{TEMP_PREFIX}junction").exists() and (home / "tmp" / f"{TEMP_PREFIX}junction").exists()
    first = json.loads((settings.log_dir / "access.log").read_text(encoding="utf-8").splitlines()[0])
    assert first["api"] == "startup_cleanup" and first["pages"] == 2
    for link in (home / f"{TEMP_PREFIX}junction", home / "tmp" / f"{TEMP_PREFIX}junction"):
        os.rmdir(link)                       # 只拆联接本身


def test_uvicorn_access_log_off(monkeypatch, settings):
    from prep395.__main__ import uvicorn_config
    monkeypatch.setenv("PREP395_LLM_BASE", settings.llm_base)
    monkeypatch.setenv("PREP395_HOME", str(settings.home))
    cfg = uvicorn_config()
    assert cfg.access_log is False
