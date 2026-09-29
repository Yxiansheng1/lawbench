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
    assert not list(target.parent.glob(".~lb*"))  # 临时文件已清掉


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


@pytest.mark.skipif(not IS_WIN, reason="junction")
def test_copy_original_post_check_rejects_link(root, monkeypatch):
    """复制完成后复查：目标在改名那一刻被换成了链接（模拟并发替换），要拒绝（copy_escape）。"""
    r, src, tmp = root
    outside = tmp / "案外3"
    outside.mkdir()
    real_rename = gate.os.rename

    def swap(a, b):
        os_ = gate.os
        os_.unlink(a)
        make_junction(pathlib.Path(b), outside)

    monkeypatch.setattr(gate.os, "rename", swap)
    with pytest.raises(ApiError) as ei:
        gate.copy_original(r, "证据/被换.txt", src)
    monkeypatch.setattr(gate.os, "rename", real_rename)
    assert ei.value.code == "OUT_OF_CASE" and ei.value.reason == "copy_escape"


def test_import_device_or_dot_name_skips_only_that_file(make_client, cases_dir, tmp_path):
    """源文件名是设备名或以 . 开头：只跳过这一个，其余照常复制（返修令 2145 第 5 节）。"""
    folder = tmp_path / "补充"
    folder.mkdir()
    (folder / "con.txt").write_text("x", encoding="utf-8")      # 文件夹里的设备名
    (folder / "正常.txt").write_text("x", encoding="utf-8")
    env = tmp_path / ".env"                                     # 放到案件根目录时第一级以 . 开头
    env.write_text("x", encoding="utf-8")
    nul = tmp_path / "NUL.txt"
    nul.write_text("x", encoding="utf-8")
    ok_file = tmp_path / "说明.txt"
    ok_file.write_text("x", encoding="utf-8")
    c = make_client()
    root = cases_dir / "设备名"
    root.mkdir()  # 没有 02案件材料：目标是案件根目录
    cid = c.post("/api/case/open", json={"path": str(root)}).json()["value"]["case_id"]
    r = c.post("/api/materials/import", json={"case_id": cid, "paths": [str(folder), str(env), str(nul), str(ok_file)],
                                               "target": None, "unzip": False}).json()
    assert r["ok"] is True, r
    assert sorted(x["to"] for x in r["value"]["copied"]) == sorted(["补充/正常.txt", "说明.txt"])
    assert sorted(x["path"] for x in r["value"]["skipped"]) == sorted([str(folder / "con.txt"), str(env), str(nul)])
    assert all(x["reason"] == "无法读取" for x in r["value"]["skipped"])


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


def test_delete_work_file_first_layer(root, monkeypatch):
    """只看第一层：让第二层（解析后的真实第一级）失效，第一级不是 工作区 的路径仍要被拒绝。"""
    r, _, _ = root
    victim = pathlib.Path(r) / "证据" / "已有.txt"
    monkeypatch.setattr(gate, "_real_top", lambda root_, path, op="internal": gate.WORK.casefold())
    with pytest.raises(ApiError) as ei:
        gate.delete_work_file(r, "证据/已有.txt")
    assert ei.value.code == "OUT_OF_CASE"
    assert victim.exists()


def test_delete_work_file_second_layer(root, monkeypatch):
    """第一级写着 工作区、解析后却落在别处（别名等）：第二层（解析后的真实第一级）拒绝。"""
    r, _, _ = root
    victim = pathlib.Path(r) / "证据" / "已有.txt"
    monkeypatch.setattr(gate, "_resolve", lambda root_, parts, op: victim)
    with pytest.raises(ApiError) as ei:
        gate.delete_work_file(r, "工作区/别名/已有.txt")
    assert ei.value.code == "OUT_OF_CASE"
    assert victim.exists()


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
