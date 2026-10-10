"""材料接口 /api/materials/import、/api/materials/scan、/api/materials（Spec 5.1）：
复制不移动；目标默认 02案件材料；云同步目录的源文件照常复制（N80）；跳过快捷方式和链接、超大、同名同内容；同名不同内容改名"原名(2)"；
已在案件内的直接解析；工作区 下的临时文件复制后删除；ZIP 解压规则；源文件 sha256 不变；返回通过契约校验。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sys
import zipfile

import pytest

from lawbench.config import REPO_ROOT

from conftest import IS_WIN, make_junction

sys.path.insert(0, str(REPO_ROOT / "contracts"))
from check_examples import validator  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures"


def ok(r, schema: str) -> dict:
    assert r.status_code == 200, r.text
    body = r.json()
    errs = list(validator(f"api/{schema}.schema.json", "#/$defs/response").iter_errors(body))
    assert not errs, [e.message for e in errs]
    assert body["ok"] is True, body
    return body["value"]


def fail(r, schema: str, code: str) -> None:
    assert r.status_code == 200, r.text
    body = r.json()
    assert not list(validator(f"api/{schema}.schema.json", "#/$defs/response").iter_errors(body))
    assert body["ok"] is False and body["error"]["code"] == code, body


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def hashes(root: pathlib.Path) -> dict[str, str]:
    return {q.relative_to(root).as_posix(): sha(q) for q in sorted(root.rglob("*")) if q.is_file()}


@pytest.fixture
def env(make_client, cases_dir, tmp_path):
    client = make_client()
    root = cases_dir / "借款案"
    (root / "02案件材料").mkdir(parents=True)
    cid = ok(client.post("/api/case/open", json={"path": str(root)}), "case_open")["case_id"]
    src = tmp_path / "外部"
    shutil.copytree(FIXTURES / "civil-01", src / "补充证据")
    shutil.copy(FIXTURES / "criminal-01" / "起诉意见书.pdf", src / "起诉意见书.pdf")
    return client, root, cid, src


def imp(client, cid, paths, target=None, unzip=False) -> dict:
    req = {"case_id": cid, "paths": [str(p) for p in paths], "target": target, "unzip": unzip}
    assert not list(validator("api/materials_import.schema.json", "#/$defs/request").iter_errors(req))
    return ok(client.post("/api/materials/import", json=req), "materials_import")


def test_import_folder_and_file(env):
    client, root, cid, src = env
    before = hashes(src)
    v = imp(client, cid, [src / "补充证据", src / "起诉意见书.pdf"])
    tos = sorted(c["to"] for c in v["copied"])
    assert tos == sorted(["02案件材料/补充证据/" + n for n in
                          ["借条.docx", "情况说明.txt", "案情摘要.md", "还款记录.csv", "银行流水.xlsx"]]
                         + ["02案件材料/起诉意见书.pdf"])
    assert v["skipped"] == [] and v["scan"]["added"] == 6 and v["scan"]["review_needed"] is True
    assert hashes(src) == before                                 # 源文件一个字节都没动
    assert (src / "起诉意见书.pdf").exists()                     # 复制不移动
    for c in v["copied"]:
        assert sha(root / c["to"]) == sha(pathlib.Path(c["from"]))
    lst = ok(client.get("/api/materials", params={"case_id": cid}), "materials_list")["materials"]
    assert len(lst) == 6


def test_default_target_root_without_02(make_client, cases_dir, tmp_path):
    client = make_client()
    root = cases_dir / "无标准目录"
    root.mkdir()
    cid = ok(client.post("/api/case/open", json={"path": str(root)}), "case_open")["case_id"]
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    assert imp(client, cid, [f])["copied"] == [{"from": str(f), "to": "a.txt"}]


def test_explicit_target(env):
    client, root, cid, src = env
    v = imp(client, cid, [src / "起诉意见书.pdf"], target="03一审/我方证据")
    assert v["copied"][0]["to"] == "03一审/我方证据/起诉意见书.pdf"
    assert (root / "03一审" / "我方证据" / "起诉意见书.pdf").is_file()


@pytest.mark.parametrize("target", ["工作区/材料", "成果", "../外面", ".dsh", "C:\\x"])
def test_bad_target(env, target):
    client, root, cid, src = env
    r = client.post("/api/materials/import", json={"case_id": cid, "paths": [str(src / "起诉意见书.pdf")],
                                                    "target": target, "unzip": False})
    body = r.json()
    assert body["ok"] is False and body["error"]["code"] in ("OUT_OF_CASE", "INVALID_ARGUMENT")
    assert not (root / "成果" / "起诉意见书.pdf").exists()


def test_same_name_same_content_skipped(env):
    client, root, cid, src = env
    imp(client, cid, [src / "起诉意见书.pdf"])
    v = imp(client, cid, [src / "起诉意见书.pdf"])
    assert v["copied"] == [] and v["skipped"] == [{"path": str(src / "起诉意见书.pdf"), "reason": "同名同内容已存在"}]
    assert v["scan"]["added"] == 0


def test_same_name_different_content_renamed(env):
    client, root, cid, src = env
    imp(client, cid, [src / "起诉意见书.pdf"])
    existing = root / "02案件材料" / "起诉意见书.pdf"
    old = sha(existing)
    other = src / "另一份" / "起诉意见书.pdf"
    other.parent.mkdir()
    shutil.copy(FIXTURES / "criminal-01" / "现场勘验图文.pdf", other)
    v = imp(client, cid, [other])
    assert v["copied"] == [{"from": str(other), "to": "02案件材料/起诉意见书(2).pdf"}]
    assert sha(existing) == old                                   # 不覆盖
    other2 = src / "第三份" / "起诉意见书.pdf"
    other2.parent.mkdir()
    shutil.copy(FIXTURES / "closed-01" / "01委托手续" / "授权委托书.pdf", other2)
    assert imp(client, cid, [other2])["copied"][0]["to"] == "02案件材料/起诉意见书(3).pdf"


def test_sync_folder_source_imported(env, tmp_path, monkeypatch):
    """N80（2026-10-08）：源文件在云同步目录（OneDrive 环境变量指向的目录、名字含"坚果云"的目录）也照常复制进案件。"""
    client, root, cid, src = env
    od = tmp_path / "云盘"
    od.mkdir()
    shutil.copy(FIXTURES / "civil-01" / "情况说明.txt", od / "情况说明.txt")
    monkeypatch.setenv("OneDrive", str(od))
    nut = tmp_path / "坚果云" / "b.txt"
    nut.parent.mkdir()
    nut.write_text("x", encoding="utf-8")
    v = imp(client, cid, [od / "情况说明.txt", od, nut])
    assert v["skipped"] == []
    assert sorted(c["to"] for c in v["copied"]) == ["02案件材料/b.txt", "02案件材料/云盘/情况说明.txt", "02案件材料/情况说明.txt"]
    names = {m["rel_path"] for m in ok(client.get("/api/materials", params={"case_id": cid}), "materials_list")["materials"]}
    assert {"02案件材料/b.txt", "02案件材料/云盘/情况说明.txt", "02案件材料/情况说明.txt"} <= names
    # 案件根本身在云同步目录仍被拒（SEC-14 不变）
    fail(client.post("/api/case/open", json={"path": str(od)}), "case_open", "CASE_IN_SYNC_FOLDER")


def test_shortcut_and_link_skipped(env, tmp_path):
    client, root, cid, src = env
    lnk = src / "快捷方式.lnk"
    lnk.write_bytes(b"L\x00\x00\x00")
    v = imp(client, cid, [lnk])
    assert v["skipped"] == [{"path": str(lnk), "reason": "链接或快捷方式"}]
    if IS_WIN:
        make_junction(src / "目录联接", src / "补充证据")
        v = imp(client, cid, [src / "目录联接"])
        assert v["skipped"] == [{"path": str(src / "目录联接"), "reason": "链接或快捷方式"}] and v["copied"] == []
        # 文件夹里的 junction：跳过这一项，其余照常复制
        folder = tmp_path / "含链接"
        folder.mkdir()
        (folder / "正常.txt").write_text("x", encoding="utf-8")
        make_junction(folder / "链到别处", src / "补充证据")
        v = imp(client, cid, [folder])
        assert [c["to"] for c in v["copied"]] == ["02案件材料/含链接/正常.txt"]
        assert v["skipped"] == [{"path": str(folder / "链到别处"), "reason": "链接或快捷方式"}]


def test_unreadable_and_too_large(env, monkeypatch):
    client, root, cid, src = env
    from lawbench.case import materials
    v = imp(client, cid, [src / "不存在.pdf"])
    assert v["skipped"] == [{"path": str(src / "不存在.pdf"), "reason": "无法读取"}]
    monkeypatch.setattr(materials, "MAX_BYTES", 1000)
    v = imp(client, cid, [src / "起诉意见书.pdf"])
    assert v["skipped"] == [{"path": str(src / "起诉意见书.pdf"), "reason": "超过大小上限"}]


def test_inside_case_not_copied(env):
    client, root, cid, src = env
    shutil.copy(FIXTURES / "civil-01" / "情况说明.txt", root / "02案件材料" / "情况说明.txt")
    v = imp(client, cid, [root / "02案件材料" / "情况说明.txt"])
    assert v["copied"] == [] and v["skipped"] == [] and v["scan"]["added"] == 1
    assert list((root / "02案件材料").iterdir()) == [root / "02案件材料" / "情况说明.txt"]


def test_work_temp_file_moved(env):
    client, root, cid, src = env
    tmpfile = root / "工作区" / "临时" / "粘贴截图.png"
    shutil.copy(FIXTURES / "criminal-01" / "转账截图.jpg", tmpfile)
    v = imp(client, cid, [tmpfile])
    assert v["copied"] == [{"from": str(tmpfile), "to": "02案件材料/粘贴截图.png"}]
    assert not tmpfile.exists() and (root / "02案件材料" / "粘贴截图.png").is_file()


def _zip(path: pathlib.Path, members: dict[str, bytes]) -> pathlib.Path:
    with zipfile.ZipFile(path, "w") as z:
        for n, data in members.items():
            z.writestr(n, data)
    return path


def test_unzip_standard_folders_to_root(env, tmp_path):
    client, root, cid, src = env
    z = _zip(tmp_path / "委托材料.zip", {"01委托手续/委托合同.txt": "合同".encode(), "01委托手续/授权书.txt": b"x"})
    v = imp(client, cid, [z], unzip=True)
    assert sorted(c["to"] for c in v["copied"]) == ["01委托手续/委托合同.txt", "01委托手续/授权书.txt"]
    assert (root / "01委托手续" / "委托合同.txt").read_text(encoding="utf-8") == "合同"
    assert list((root / "工作区" / "临时").iterdir()) == []
    assert z.exists()  # 案件外的源 ZIP 不动


def test_unzip_other_to_target(env, tmp_path):
    client, root, cid, src = env
    z = _zip(tmp_path / "下载.zip", {"a/说明.txt": b"x"})
    v = imp(client, cid, [z], unzip=True)
    assert [c["to"] for c in v["copied"]] == ["02案件材料/a/说明.txt"]


def test_zip_without_unzip_copied_as_file(env, tmp_path):
    client, root, cid, src = env
    z = _zip(tmp_path / "包.zip", {"a.txt": b"x"})
    v = imp(client, cid, [z], unzip=False)
    assert [c["to"] for c in v["copied"]] == ["02案件材料/包.zip"]


@pytest.mark.parametrize("members", [
    {"../evil.txt": b"x"}, {"a/../../evil.txt": b"x"}, {"/abs.txt": b"x"}, {"C:/x.txt": b"x"},
    {f"f{i}.txt": b"x" for i in range(501)},
])
def test_unsafe_zip_skipped(env, tmp_path, members):
    client, root, cid, src = env
    z = _zip(tmp_path / "坏.zip", members)
    v = imp(client, cid, [z], unzip=True)
    assert v["copied"] == [] and v["skipped"] == [{"path": str(z), "reason": "无法读取"}]
    assert not (root.parent / "evil.txt").exists()


def test_zip_symlink_member_skipped(env, tmp_path):
    client, root, cid, src = env
    z = tmp_path / "链接.zip"
    with zipfile.ZipFile(z, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.external_attr = (0o120777 << 16)
        zf.writestr(info, "C:/Windows/win.ini")
    v = imp(client, cid, [z], unzip=True)
    assert v["skipped"] == [{"path": str(z), "reason": "无法读取"}]


def test_errors(env):
    client, root, cid, src = env
    fail(client.post("/api/materials/scan", json={"case_id": "00000000-0000-4000-8000-000000000000"}),
         "materials_scan", "CASE_NOT_FOUND")
    fail(client.post("/api/materials/scan", json={}), "materials_scan", "INVALID_ARGUMENT")
    fail(client.get("/api/materials", params={"case_id": "bad"}), "materials_list", "INVALID_ARGUMENT")
    fail(client.post("/api/materials/import", json={"case_id": cid, "paths": [], "target": None, "unzip": False}),
         "materials_import", "INVALID_ARGUMENT")
    fail(client.post("/api/materials/import", json={"case_id": cid, "paths": ["相对路径.txt"], "target": None,
                                                   "unzip": False}), "materials_import", "INVALID_ARGUMENT")


def test_empty_case_list(env):
    client, root, cid, src = env
    assert ok(client.get("/api/materials", params={"case_id": cid}), "materials_list") == {"materials": []}


def test_stale_ocr_flag(env):
    """case.db 里有该材料旧版本的识别结果时，列表标 stale_ocr。"""
    import sqlite3
    client, root, cid, src = env
    imp(client, cid, [src / "起诉意见书.pdf"])
    con = sqlite3.connect(root / "工作区" / "case.db")
    with con:
        con.execute("INSERT INTO ocr_jobs VALUES ('J-20260929120000-abcd','M0001',?,0,'done',NULL,5,5,0,"
                    "'2026-09-29T12:00:00+08:00','2026-09-29T12:00:00+08:00')", ("0" * 64,))
    con.close()
    lst = ok(client.get("/api/materials", params={"case_id": cid}), "materials_list")["materials"]
    assert lst[0]["stale_ocr"] is True


def test_logs_no_material_names(env, appdata):
    client, root, cid, src = env
    imp(client, cid, [src / "补充证据"])
    from lawbench import logs
    logs.close()
    text = "".join(p.read_text(encoding="utf-8") for p in (appdata / "logs").glob("*"))
    assert '"op": "scan"' in text
    for bad in ["借条", "银行流水", "补充证据", "借款案", str(src), "LBFX"]:
        assert bad not in text, bad
    for line in text.splitlines():
        assert set(json.loads(line)) <= {"t", "module", "op", "status", "case_id", "ms", "error"}


def test_materials_list_chars(make_client, cases_dir):
    """契约 1.4：materials_list 每份带 chars = 材料文本字数（不含位置标记）；未识别的扫描件占位页不算；文本变了跟着变。"""
    client = make_client()
    root = cases_dir / "字数"
    root.mkdir()
    (root / "说明.txt").write_text("一二三四五\n六七八\n", encoding="utf-8")
    shutil.copy(FIXTURES / "criminal-01" / "讯问笔录.pdf", root / "讯问笔录.pdf")
    cid = ok(client.post("/api/case/open", json={"path": str(root)}), "case_open")["case_id"]
    ok(client.post("/api/materials/scan", json={"case_id": cid}), "materials_scan")
    by = {m["name"]: m for m in ok(client.get("/api/materials", params={"case_id": cid}), "materials_list")["materials"]}
    assert by["说明"]["chars"] == 8                    # 两行 5 + 3 个字，不含【第1行】标记和换行
    assert by["讯问笔录"]["chars"] == 0                # 3 页都是"本页需识别"占位
    (root / "说明.txt").write_text("一二三四五\n六七八\n九十\n", encoding="utf-8")
    ok(client.post("/api/materials/scan", json={"case_id": cid}), "materials_scan")
    by = {m["name"]: m for m in ok(client.get("/api/materials", params={"case_id": cid}), "materials_list")["materials"]}
    assert by["说明"]["chars"] == 10

