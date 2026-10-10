"""契约 1.4：POST /api/materials/remove —— 原件移到回收站、清掉文本 / 识别页 / 检索，index.json 留编号（status removed）。

测试里把"移到回收站"换成移到临时目录（不往本机回收站里放测试文件）；真回收站只在设了 LB_TEST_RECYCLE=1 时跑一例。
"""
from __future__ import annotations

import json
import os
import shutil

import pytest

from lawbench.case import trash

from conftest import IS_WIN, make_junction
from t8_helpers import FIXTURES, Env, fail, ok

SCHEMA = "api/materials_remove.schema.json"


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path / "c", {"说明.txt": FIXTURES / "civil-01" / "情况说明.txt",
                             "摘要.md": FIXTURES / "civil-01" / "案情摘要.md",
                             "讯问笔录.pdf": FIXTURES / "criminal-01" / "讯问笔录.pdf"})
    e.bin = tmp_path / "假回收站"
    e.bin.mkdir()
    e.recycled = []

    def fake_recycle(p):
        e.recycled.append(str(p))
        shutil.move(str(p), str(e.bin / os.path.basename(p)))
    e.client.app.state.lb.materials.recycle = fake_recycle
    e.client.app.state.lb.materials.can_recycle = lambda p: True      # 临时目录可能不在固定盘上；有无回收站另有专门用例
    yield e
    e.close()


def mats(env) -> dict:
    v = ok(env.client.get("/api/materials", params={"case_id": env.case_id}), "api/materials_list.schema.json")
    return {m["name"]: m for m in v["materials"]}


def index(env) -> dict:
    return json.loads((env.root / "工作区" / "材料" / "index.json").read_text(encoding="utf-8"))


def remove(env, ids):
    return env.client.post("/api/materials/remove", json={"case_id": env.case_id, "material_ids": ids})


def search(env, q) -> list[str]:
    """命中的材料编号。"""
    v = ok(env.client.get("/api/search", params={"case_id": env.case_id, "q": q}), "api/search.schema.json")
    return [h["material_id"] for h in v["hits"]]


def test_remove_moves_original_and_clears_derived(env):
    mid = mats(env)["说明"]["material_id"]
    text = env.root / "工作区" / "材料" / "文本" / "说明.txt.md"
    word = text.read_text(encoding="utf-8").splitlines()[-1][:6]
    assert text.is_file() and mid in search(env, word)
    v = ok(remove(env, [mid]), SCHEMA)
    assert v == {"removed": [mid], "already_removed": [], "failed": [], "wiki_needs_update": False}
    assert not (env.root / "说明.txt").exists() and (env.bin / "说明.txt").is_file()      # 原件进了回收站，不是删掉
    assert not text.exists()                                                             # 材料文本清掉
    assert "说明" not in mats(env) and len(mats(env)) == 2                                # 列表里没有了
    entry = next(m for m in index(env)["materials"] if m["material_id"] == mid)
    assert entry["status"] == "removed"                                                  # 索引里留着编号
    assert mid not in search(env, word)                                                  # 检索不到这份了
    t = env.begin()["task_id"]
    fail(env.tool(t, "case_read_material", {"name": "说明"}), "MATERIAL_NOT_FOUND")       # AI 读不到
    assert sorted(m["name"] for m in env.tool_ok(t, "case_list_materials", {})["materials"]) == ["摘要", "讯问笔录"]
    assert env.tool_ok(t, "case_save_draft", {"title": "a", "content": "x"})["coverage"]["total"] == 2
    fail(env.client.get("/api/source", params={"case_id": env.case_id, "material_id": mid, "citation": "〔说明 第1行〕"}),
         "MATERIAL_NOT_FOUND")
    assert ok(remove(env, [mid]), SCHEMA) == {"removed": [], "already_removed": [mid], "failed": [],     # 幂等
                                              "wiki_needs_update": False}


def test_unknown_id_rejects_whole_request(env):
    mid = mats(env)["说明"]["material_id"]
    fail(remove(env, [mid, "M0999"]), "MATERIAL_NOT_FOUND")
    assert (env.root / "说明.txt").is_file() and "说明" in mats(env)                       # 什么都没动
    fail(remove(env, []), "INVALID_ARGUMENT")


def test_recycle_failure_keeps_material(env):
    def boom(p):
        raise PermissionError("in use")
    env.client.app.state.lb.materials.recycle = boom
    a, b = mats(env)["说明"]["material_id"], mats(env)["摘要"]["material_id"]
    v = ok(remove(env, [a, b]), SCHEMA)
    assert v["removed"] == [] and [f["material_id"] for f in v["failed"]] == [a, b] and "回收站" in v["failed"][0]["reason"]
    assert (env.root / "说明.txt").is_file() and mats(env)["说明"]["status"] == "parsed"
    assert (env.root / "工作区" / "材料" / "文本" / "说明.txt.md").is_file()               # 移不走原件：派生数据也不动


def test_rescan_keeps_removed_and_reimport_gets_new_id(env):
    mid = mats(env)["说明"]["material_id"]
    ok(remove(env, [mid]), SCHEMA)
    v = ok(env.client.post("/api/materials/scan", json={"case_id": env.case_id}), "api/materials_scan.schema.json")
    assert v["removed"] == 0 and v["added"] == 0                                         # 不改标成"原件已删除"
    assert next(m for m in index(env)["materials"] if m["material_id"] == mid)["status"] == "removed"
    shutil.copy(env.bin / "说明.txt", env.root / "说明.txt")                               # 律师又把同一个文件放回来
    v = ok(env.client.post("/api/materials/scan", json={"case_id": env.case_id}), "api/materials_scan.schema.json")
    assert v["added"] == 1
    new = mats(env)["说明"]
    assert new["material_id"] != mid and new["status"] == "parsed"                       # 是新材料、新编号
    statuses = sorted(m["status"] for m in index(env)["materials"] if m["rel_path"] == "说明.txt")
    assert statuses == ["parsed", "removed"]
    assert (env.root / "工作区" / "材料" / "文本" / "说明.txt.md").is_file()


def test_ocr_pages_dropped_and_wiki_flag(env):
    mid = mats(env)["讯问笔录"]["material_id"]
    pages = env.root / "工作区" / "材料" / "识别页" / mid
    pages.mkdir(parents=True)
    (pages / "1.md").write_text("识别出来的文字", encoding="utf-8")
    card = {"v": 1, "case_id": env.case_id, "case_type": "criminal", "stance": None, "parties": [], "issues": [],
            "key_facts": [], "generated_by": None, "generated_at": "2026-10-10T09:00:00+08:00",
            "materials_at_generation": [{"material_id": mid, "sha256": "a" * 64}]}
    w = env.root / "工作区" / "wiki" / "case.json"
    w.parent.mkdir(parents=True, exist_ok=True)
    w.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    v = ok(remove(env, [mid]), SCHEMA)
    assert v["removed"] == [mid] and v["wiki_needs_update"] is True
    assert not pages.exists() and (env.bin / "讯问笔录.pdf").is_file()


def test_source_deleted_material_can_be_removed(env):
    """原件已经被律师自己删掉的（source_deleted，文本还在、还能被检索）：移除时不用再动原件，文本和检索照样清掉（N61）。"""
    mid = mats(env)["说明"]["material_id"]
    (env.root / "说明.txt").unlink()
    ok(env.client.post("/api/materials/scan", json={"case_id": env.case_id}), "api/materials_scan.schema.json")
    assert mats(env)["说明"]["status"] == "source_deleted"
    assert ok(remove(env, [mid]), SCHEMA)["removed"] == [mid]
    assert "说明" not in mats(env) and not (env.root / "工作区" / "材料" / "文本" / "说明.txt.md").exists()


def test_logs_have_no_names(env, caplog):
    mid = mats(env)["说明"]["material_id"]
    with caplog.at_level("INFO", logger="lawbench.events"):
        ok(remove(env, [mid]), SCHEMA)
    log = "\n".join(r.getMessage() for r in caplog.records if r.name == "lawbench.events")
    assert '"op": "remove"' in log and "说明" not in log and "txt" not in log


# ---------- 复核 AMEND（rv-B24） ----------

def test_no_recycle_bin_location_is_not_removed(env):
    """P1-1：原件所在位置没有回收站（网络盘、U 盘）：Windows 会静默永久删除，所以不移，进 failed，回收函数不调用。"""
    env.client.app.state.lb.materials.can_recycle = lambda p: False
    mid = mats(env)["说明"]["material_id"]
    v = ok(remove(env, [mid]), SCHEMA)
    assert v["removed"] == [] and v["failed"] == [{"material_id": mid, "reason": "该位置没有回收站，未移除；请在资源管理器里自行处理"}]
    assert env.recycled == [] and (env.root / "说明.txt").is_file() and mats(env)["说明"]["status"] == "parsed"
    assert (env.root / "工作区" / "材料" / "文本" / "说明.txt.md").is_file()


@pytest.mark.skipif(not IS_WIN, reason="盘类型判断只在 Windows 上有")
def test_has_recycle_bin_only_on_fixed_local_drive(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(trash, "drive_type", lambda root: calls.append(root) or 3)
    assert trash.has_recycle_bin("C:\\案件\\a.pdf") is True and calls == ["C:\\"]
    assert trash.has_recycle_bin("\\\\?\\C:\\很长的路径\\a.pdf") is True               # 长路径前缀不算网络路径
    assert trash.has_recycle_bin("\\\\server\\share\\a.pdf") is False                # UNC
    assert trash.has_recycle_bin("\\\\localhost\\D$\\a.pdf") is False
    assert trash.has_recycle_bin("\\\\?\\UNC\\server\\share\\a.pdf") is False
    for t in (2, 4, 5, 6, 0, 1):                                                    # 可移动、网络映射盘、光盘、内存盘、未知
        monkeypatch.setattr(trash, "drive_type", lambda root, t=t: t)
        assert trash.has_recycle_bin("Z:\\a.pdf") is False

    def boom(root):
        raise OSError("x")
    monkeypatch.setattr(trash, "drive_type", boom)
    assert trash.has_recycle_bin("C:\\a.pdf") is False                              # 查不出来按没有
    monkeypatch.setattr(trash, "drive_type", lambda root: 4)
    called = []
    monkeypatch.setattr(trash, "_recycle_windows", lambda p: called.append(p))      # 真回收函数换掉：这一例不碰系统回收站
    f = tmp_path / "临时文件.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(OSError):                                                    # recycle 自己也兜一道：没有回收站就不往下走
        trash.recycle(f)
    assert called == [] and f.is_file()


@pytest.mark.skipif(not IS_WIN, reason="junction 只在 Windows 上有")
def test_gate_material_dir_replaced_by_junction(tmp_path):
    """P2-2：登记之后把材料所在目录换成指向案件外同名文件的联接：闸门拒绝，进 failed，回收函数不调用，案件外的文件还在。"""
    e = Env(tmp_path / "c", {"卷一/说明.txt": FIXTURES / "civil-01" / "情况说明.txt"})
    try:
        recycled = []
        e.client.app.state.lb.materials.recycle = lambda p: recycled.append(str(p))
        e.client.app.state.lb.materials.can_recycle = lambda p: True
        mid = mats(e)["说明"]["material_id"]
        outside = tmp_path / "案外"
        outside.mkdir()
        shutil.copy(FIXTURES / "civil-01" / "情况说明.txt", outside / "说明.txt")
        shutil.rmtree(e.root / "卷一")
        make_junction(e.root / "卷一", outside)
        v = ok(remove(e, [mid]), SCHEMA)
        assert v["removed"] == [] and v["failed"] == [{"material_id": mid, "reason": "该材料位置不在案件内，未移除"}]
        assert recycled == [] and (outside / "说明.txt").is_file()
        assert mats(e)["说明"]["status"] == "parsed"                                  # 没被标成已移除
    finally:
        e.close()


def test_index_rel_path_tampered_fails_that_one_not_500(env):
    """NOTE 2：index.json 里某条 rel_path 被改成 ../ 开头：那一份进 failed（或整份索引不合契约时报业务错误），不是 500。"""
    mid = mats(env)["说明"]["material_id"]
    p = env.root / "工作区" / "材料" / "index.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    next(m for m in data["materials"] if m["material_id"] == mid)["rel_path"] = "../外面/说明.txt"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    r = remove(env, [mid])
    assert r.status_code == 200
    body = r.json()
    if body["ok"]:
        assert body["value"]["removed"] == [] and body["value"]["failed"][0]["material_id"] == mid
        assert body["value"]["failed"][0]["reason"] == "材料索引已损坏，未移除；请联系技术支持"   # 不引导重扫（scan/list 同样读不了）
    else:
        assert body["error"]["code"] != "INTERNAL"
    assert env.recycled == []


@pytest.mark.skipif(os.environ.get("LB_TEST_RECYCLE") != "1", reason="真回收站：设 LB_TEST_RECYCLE=1 才跑（会往本机回收站放一个小文件）")
def test_real_recycle_bin(tmp_path):
    f = tmp_path / "lawbench-测试文件-可以删除.txt"
    f.write_text("x", encoding="utf-8")
    trash.recycle(f)
    assert not f.exists()
    with pytest.raises(OSError):
        trash.recycle(f)                       # 已经不在了
