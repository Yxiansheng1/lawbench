"""深路径（返修令 2145 第 4 节）：本机没开 Windows 长路径支持时，路径超过 260 字符的只让那一份材料失败，
不让整次导入或扫描返回 500；复制原件用的临时文件名不比目标文件名长。"""
from __future__ import annotations

import json
import os
import pathlib

import pytest

from lawbench.ingest import REASONS

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows 260 字符上限")


def _pad_to(parent: pathlib.Path, total: int) -> pathlib.Path:
    """在 parent 下建一个目录，使其完整路径正好 total 个字符。"""
    need = total - len(str(parent)) - 1
    assert need > 5, "临时目录本身太深，无法构造"
    return parent / ("深" * 2 + "x" * (need - 2))


def test_text_path_too_long_fails_only_that_material(make_client, cases_dir):
    # 原件 root\证据\a.txt 和 index.json（连同临时文件，root+25）放得下；
    # 材料文本 root\工作区\材料\文本\证据\ 下的原子写临时文件（root+31）放不下
    root = _pad_to(cases_dir, 230)
    (root / "证据").mkdir(parents=True)
    (root / "证据" / "a.txt").write_text("深路径里的材料", encoding="utf-8")
    (root / "b.txt").write_text("根目录里的材料", encoding="utf-8")
    c = make_client()
    cid = c.post("/api/case/open", json={"path": str(root)}).json()["value"]["case_id"]
    r = c.post("/api/materials/scan", json={"case_id": cid})
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    idx = json.loads((root / "工作区" / "材料" / "index.json").read_text(encoding="utf-8"))
    mats = {m["rel_path"]: m for m in idx["materials"]}
    assert mats["证据/a.txt"]["status"] == "failed" and mats["证据/a.txt"]["error"] == REASONS["path_too_long"]
    assert mats["b.txt"]["status"] == "parsed"


def test_import_copy_temp_name_not_longer_than_target(make_client, cases_dir, tmp_path):
    """目标路径接近上限时，复制用的临时文件不能先超限（原来是 .~lb-<32 位>.tmp，比短文件名长得多）。"""
    # 目标 root\02案件材料\借条.txt 是 root+12；原来的临时名 root+49 超限，现在的 root+19 不超
    root = _pad_to(cases_dir, 220)
    (root / "02案件材料").mkdir(parents=True)
    src = tmp_path / "借条.txt"
    src.write_text("x", encoding="utf-8")
    c = make_client()
    cid = c.post("/api/case/open", json={"path": str(root)}).json()["value"]["case_id"]
    v = c.post("/api/materials/import", json={"case_id": cid, "paths": [str(src)], "target": None,
                                               "unzip": False}).json()["value"]
    assert v["copied"] == [{"from": str(src), "to": "02案件材料/借条.txt"}], v
    assert len(str(root / "02案件材料" / "借条.txt")) <= 259
