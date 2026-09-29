"""T5 对路径闸门的两处新增（copy_original、delete_work_file）和 _mkdirs 的边界修正：直接测闸门本身。"""
from __future__ import annotations

import pathlib

import pytest

from lawbench import logs
from lawbench.case import gate
from lawbench.errors import ApiError

from conftest import IS_WIN, make_junction


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "案件"
    (r / "证据").mkdir(parents=True)
    (r / "工作区" / "临时").mkdir(parents=True)
    (r / "证据" / "已有.txt").write_text("原件", encoding="utf-8")
    logs.setup(tmp_path / "ad")
    src = tmp_path / "外部.txt"
    src.write_text("新内容", encoding="utf-8")
    return gate.check_root(str(r)), src, tmp_path


# ---------- copy_original：只在原件区新建，从不覆盖 ----------

def test_copy_original_never_overwrites(root):
    r, src, _ = root
    target = pathlib.Path(r) / "证据" / "已有.txt"
    with pytest.raises(FileExistsError):
        gate.copy_original(r, "证据/已有.txt", src)
    assert target.read_text(encoding="utf-8") == "原件"
    assert not list(target.parent.glob(".~lb-*"))  # 临时文件已清掉


def test_copy_original_to_case_root(root):
    """目标就在案件根目录（没有 02案件材料 时的默认位置）。"""
    r, src, _ = root
    p = gate.copy_original(r, "外部.txt", src)
    assert p.read_text(encoding="utf-8") == "新内容"


def test_copy_original_creates_parents(root):
    r, src, _ = root
    assert gate.copy_original(r, "02案件材料/补充/外部.txt", src).is_file()


@pytest.mark.parametrize("rel", ["工作区/外部.txt", "成果/外部.txt", ".dsh/外部.txt", "../外部.txt", "C:\\外部.txt",
                                 "证据/NUL.txt"])
def test_copy_original_rejects_outside_originals(root, rel):
    r, src, tmp = root
    with pytest.raises(ApiError) as ei:
        gate.copy_original(r, rel, src)
    assert ei.value.code == "OUT_OF_CASE"


@pytest.mark.skipif(not IS_WIN, reason="junction")
def test_copy_original_through_junction_rejected(root):
    r, src, tmp = root
    outside = tmp / "案外"
    outside.mkdir()
    make_junction(pathlib.Path(r) / "证据" / "链", outside)
    with pytest.raises(ApiError):
        gate.copy_original(r, "证据/链/外部.txt", src)
    assert list(outside.iterdir()) == []


# ---------- delete_work_file：只能删 工作区/ 下的文件 ----------

def test_delete_work_file_ok(root):
    r, _, _ = root
    f = pathlib.Path(r) / "工作区" / "临时" / "截图.png"
    f.write_bytes(b"x")
    gate.delete_work_file(r, "工作区/临时/截图.png")
    assert not f.exists()


@pytest.mark.parametrize("rel", ["证据/已有.txt", "成果/x.md", "../外部.txt", "工作区/../证据/已有.txt"])
def test_delete_work_file_rejects_others(root, rel):
    r, src, _ = root
    with pytest.raises(ApiError) as ei:
        gate.delete_work_file(r, rel)
    assert ei.value.code == "OUT_OF_CASE"
    assert (pathlib.Path(r) / "证据" / "已有.txt").read_text(encoding="utf-8") == "原件"
    assert src.exists()


@pytest.mark.skipif(not IS_WIN, reason="junction")
def test_delete_work_file_through_junction_rejected(root):
    r, _, tmp = root
    outside = tmp / "案外2"
    outside.mkdir()
    (outside / "x.txt").write_text("x", encoding="utf-8")
    make_junction(pathlib.Path(r) / "工作区" / "链", outside)
    with pytest.raises(ApiError):
        gate.delete_work_file(r, "工作区/链/x.txt")
    assert (outside / "x.txt").exists()
