"""界面接口 /api/*：令牌、案件、设置、胶囊、测试连接；请求和返回全部按契约校验；日志不含材料名和路径。"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import shutil
import sqlite3
import sys

import pytest

from lawbench import contracts
from lawbench.case.registry import TEMPLATES, WORK_DIRS
from lawbench.config import REPO_ROOT

from conftest import AUTH, IS_WIN, ServerThread, closed_port, make_junction, servers
from fakes import Fake395, Fake6000D

sys.path.insert(0, str(REPO_ROOT / "contracts"))
from check_examples import validator  # noqa: E402  契约自检脚本里的写法（工单通用约定）

CASE_NAME = "张某甲借款纠纷-LBTEST-9X"
MATERIAL = "借条原件-LBTEST-MAT.txt"


def ok(r, schema: str) -> dict:
    """HTTP 200 + 成功体，且整个返回体通过契约 $defs/response。"""
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
    assert body == {"ok": False, "error": {"code": code, "message": body["error"]["message"]}}
    assert body["error"]["code"] == code


def req_valid(schema: str, data) -> None:
    assert not list(validator(f"api/{schema}.schema.json", "#/$defs/request").iter_errors(data))


@pytest.fixture
def case_root(cases_dir) -> pathlib.Path:
    root = cases_dir / CASE_NAME
    (root / "证据").mkdir(parents=True)
    (root / "证据" / MATERIAL).write_text("LBTEST-CONTENT", encoding="utf-8")
    return root


# ---------- 令牌与 /health ----------

def test_health_without_token(client):
    r = client.get("/health", headers={"Authorization": ""})
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "contract_version": "1.2"}
    assert contracts.version() == "1.2"


@pytest.mark.parametrize("hdr", [None, "", "Bearer", "Bearer wrong", "bearer " + "t" * 43, "Basic " + "t" * 43,
                                 "Bearer " + "t" * 42])
def test_token_required(client, hdr):
    headers = {"Authorization": hdr} if hdr is not None else {}
    c = client
    saved = c.headers.pop("Authorization")
    try:
        for method, path in [("GET", "/api/case/recent"), ("POST", "/api/case/open"), ("GET", "/api/settings"),
                             ("PUT", "/api/capsules"), ("POST", "/api/connection/test"), ("GET", "/api/nope")]:
            r = c.request(method, path, headers=headers, json={})
            assert r.status_code == 401, (method, path, r.status_code)
            assert r.content == b""
    finally:
        c.headers["Authorization"] = saved


def test_token_ok(client):
    assert client.get("/api/case/recent").status_code == 200


# ---------- /api/case/open ----------

def test_case_open_new(client, case_root, appdata):
    req = {"path": str(case_root)}
    req_valid("case_open", req)
    v = ok(client.post("/api/case/open", json=req), "case_open")
    assert v["name"] == CASE_NAME and v["created"] is True and v["folders_created"] == []
    for rel in WORK_DIRS:
        assert (case_root / rel).is_dir(), rel
    con = sqlite3.connect(case_root / "工作区" / "case.db")
    meta = dict(con.execute("SELECT key, value FROM meta"))
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master")}
    con.close()
    assert meta["case_id"] == v["case_id"] and meta["schema_version"] == "1" and "created_at" in meta
    assert {"ocr_jobs", "ocr_pages", "search_units", "search_fts"} <= tables
    reg = json.loads((appdata / "cases.json").read_text(encoding="utf-8"))
    assert not list(validator("files/cases.schema.json").iter_errors(reg))
    assert reg["cases"][0]["root"] == os.path.realpath(case_root)
    # 原件不动
    assert (case_root / "证据" / MATERIAL).read_text(encoding="utf-8") == "LBTEST-CONTENT"
    # 再次打开：同一 case_id，不再新建
    v2 = ok(client.post("/api/case/open", json=req), "case_open")
    assert v2["case_id"] == v["case_id"] and v2["created"] is False


@pytest.mark.parametrize("template", ["civil", "criminal"])
def test_case_open_template(client, case_root, template):
    v = ok(client.post("/api/case/open", json={"path": str(case_root), "template": template}), "case_open")
    assert v["folders_created"] == TEMPLATES[template]
    for rel in TEMPLATES[template]:
        assert (case_root / rel).is_dir()


def test_template_keeps_existing(client, case_root):
    """已有文件夹不做改动：不重建、里面的文件内容和修改时间不变、不出现在 folders_created。"""
    (case_root / "03一审" / "我方证据").mkdir(parents=True)
    kept = case_root / "03一审" / "我方证据" / "聊天记录.txt"
    kept.write_text("LBTEST-KEEP", encoding="utf-8")
    (case_root / "01委托手续").mkdir()
    (case_root / "01委托手续" / "合同.txt").write_text("LBTEST-KEEP2", encoding="utf-8")
    snap = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in case_root.rglob("*") if p.is_file()}
    dir_ino = {p: p.stat().st_ino for p in [case_root / "03一审", case_root / "03一审" / "我方证据",
                                             case_root / "01委托手续"]}
    v = ok(client.post("/api/case/open", json={"path": str(case_root), "template": "civil"}), "case_open")
    assert "01委托手续" not in v["folders_created"]
    assert "03一审" not in v["folders_created"]
    assert "03一审/我方证据" not in v["folders_created"]
    assert "03一审/对方证据" in v["folders_created"]  # 只补缺
    for p, (mt, data) in snap.items():
        assert p.stat().st_mtime_ns == mt and p.read_bytes() == data
    for p, ino in dir_ino.items():
        assert p.stat().st_ino == ino
    # 第二次：全部已存在，什么都不建
    v2 = ok(client.post("/api/case/open", json={"path": str(case_root), "template": "civil"}), "case_open")
    assert v2["folders_created"] == []


@pytest.mark.parametrize("body", [{}, {"path": 1}, {"path": "x", "extra": 1}, {"path": "C:\\x", "template": "tax"}])
def test_case_open_bad_request(client, body):
    fail(client.post("/api/case/open", json=body), "case_open", "INVALID_ARGUMENT")


def test_case_open_bad_json(client):
    fail(client.post("/api/case/open", content=b"{not json", headers={"Content-Type": "application/json"}),
         "case_open", "INVALID_ARGUMENT")


def test_case_open_relative_or_missing(client, cases_dir):
    fail(client.post("/api/case/open", json={"path": "相对路径"}), "case_open", "INVALID_ARGUMENT")
    fail(client.post("/api/case/open", json={"path": str(cases_dir / "无")}), "case_open", "INVALID_ARGUMENT")


@pytest.mark.skipif(not IS_WIN, reason="junction")
def test_case_open_junction_root(client, case_root, cases_dir):
    make_junction(cases_dir / "快捷", case_root)
    fail(client.post("/api/case/open", json={"path": str(cases_dir / "快捷")}), "case_open", "CASE_ROOT_IS_LINK")


def test_case_open_sync_folder(client, tmp_path, monkeypatch):
    od = tmp_path / "Cloud"
    (od / "案件").mkdir(parents=True)
    monkeypatch.setenv("OneDrive", str(od))
    fail(client.post("/api/case/open", json={"path": str(od / "案件")}), "case_open", "CASE_IN_SYNC_FOLDER")
    assert not (od / "案件" / "工作区").exists()


def test_case_copied_folder_keeps_id(client, case_root, cases_dir, appdata):
    v = ok(client.post("/api/case/open", json={"path": str(case_root)}), "case_open")
    copy_root = cases_dir / "复制件"
    shutil.copytree(case_root, copy_root)
    v2 = ok(client.post("/api/case/open", json={"path": str(copy_root)}), "case_open")
    assert v2["case_id"] == v["case_id"]
    reg = json.loads((appdata / "cases.json").read_text(encoding="utf-8"))
    assert [c["root"] for c in reg["cases"]] == [os.path.realpath(copy_root)]


# ---------- /api/case/recent ----------

def test_case_recent(client, cases_dir):
    ids = []
    for n in ["甲", "乙", "丙"]:
        (cases_dir / n).mkdir()
        ids.append(ok(client.post("/api/case/open", json={"path": str(cases_dir / n)}), "case_open")["case_id"])
    ok(client.post("/api/case/open", json={"path": str(cases_dir / "甲")}), "case_open")
    shutil.rmtree(cases_dir / "乙")
    v = ok(client.get("/api/case/recent"), "case_recent")
    assert [c["name"] for c in v["cases"]][0] == "甲"
    assert {c["name"]: c["exists"] for c in v["cases"]} == {"甲": True, "乙": False, "丙": True}
    fail(client.get("/api/case/recent?x=1"), "case_recent", "INVALID_ARGUMENT")


def test_case_recent_empty(client):
    assert ok(client.get("/api/case/recent"), "case_recent") == {"cases": []}


# ---------- /api/settings ----------

def test_settings_get_default_and_put(client, appdata, tmp_path):
    v = ok(client.get("/api/settings"), "settings")
    assert v["servers"]["llm_base_url"] == "http://192.168.8.77:8000/v1"
    assert v["servers"]["prep_alt_base_url"] == "http://10.126.126.3:9000"
    new = copy.deepcopy(v)
    new["profile"]["lawyer_name"] = "李律师"
    new["office"]["dir"] = str(tmp_path / "日常办公")
    new["converter"] = "libreoffice"
    req_valid("settings", new)
    assert ok(client.put("/api/settings", json=new), "settings") == new
    assert ok(client.get("/api/settings"), "settings") == new
    disk = json.loads((appdata / "settings.json").read_text(encoding="utf-8"))
    assert disk == new and not list(validator("files/settings.schema.json").iter_errors(disk))


@pytest.mark.parametrize("mutate", [
    lambda s: s.pop("converter"),
    lambda s: s["servers"].update(llm_base_url="https://x"),
    lambda s: s.update(extra=1),
    lambda s: s.update(v=2),
    lambda s: s["defaults"].update(max_tokens=10),
])
def test_settings_put_invalid(client, appdata, mutate):
    s = ok(client.get("/api/settings"), "settings")
    mutate(s)
    fail(client.put("/api/settings", json=s), "settings", "INVALID_ARGUMENT")
    assert not (appdata / "settings.json").exists()


def test_settings_office_dir_in_sync_folder(client, appdata, tmp_path, monkeypatch):
    s = ok(client.get("/api/settings"), "settings")
    s["office"]["dir"] = str(tmp_path / "坚果云" / "日常办公")
    fail(client.put("/api/settings", json=s), "settings", "CASE_IN_SYNC_FOLDER")
    od = tmp_path / "Cloud"
    od.mkdir()
    monkeypatch.setenv("OneDrive", str(od))
    s["office"]["dir"] = str(od / "办公")
    fail(client.put("/api/settings", json=s), "settings", "CASE_IN_SYNC_FOLDER")
    s["office"]["dir"] = "相对路径"
    fail(client.put("/api/settings", json=s), "settings", "INVALID_ARGUMENT")
    assert not (appdata / "settings.json").exists()


# ---------- /api/capsules ----------

def _default():
    return json.loads((REPO_ROOT / "skills" / "capsules.default.json").read_text(encoding="utf-8"))


def test_capsules_first_start_copies_default(client, appdata):
    v = ok(client.get("/api/capsules"), "capsules")
    assert v == _default()
    assert json.loads((appdata / "capsules.json").read_text(encoding="utf-8")) == _default()


def test_capsules_put_ok(client, appdata):
    c = ok(client.get("/api/capsules"), "capsules")
    c["groups"].reverse()                                     # 排序
    c["groups"][0]["items"][0]["name"] = "我的发票"             # 改名
    c["groups"][1]["items"][1]["hidden"] = True               # 隐藏
    c["groups"][2]["items"].append({"id": "my-review", "name": "快速审查", "kind": "skill",
                                    "skills": ["contract-review"], "outputs": [], "hidden": False,
                                    "custom": True})          # 新增
    req_valid("capsules", c)
    assert ok(client.put("/api/capsules", json=c), "capsules") == c
    assert json.loads((appdata / "capsules.json").read_text(encoding="utf-8")) == c


def _bad_unknown_skill(c):
    c["groups"][0]["items"][0]["skills"].append("no-such-skill")


def _bad_unknown_tool(c):
    c["groups"][2]["items"][0]["tool"] = "shell"


def _bad_custom_tool(c):
    c["groups"][2]["items"].append({"id": "x-tool", "name": "x", "kind": "tool", "tool": "browser",
                                    "hidden": False, "custom": True})


def _bad_removed(c):
    c["groups"][1]["items"].pop()


def _bad_group_removed(c):
    c["groups"].pop()


def _bad_dup(c):
    c["groups"][0]["items"][1]["id"] = c["groups"][0]["items"][0]["id"]


def _bad_dup_group_item(c):
    c["groups"][0]["items"][0]["id"] = "office"


def _bad_shared(c):
    c["shared"] = ["case-wiki-build"]


def _bad_hint(c):
    c["hint"] = "改了"


def _bad_name_len(c):
    c["groups"][0]["items"][0]["name"] = "一二三四五六七八九十一二三"


@pytest.mark.parametrize("mutate", [_bad_unknown_skill, _bad_unknown_tool, _bad_custom_tool, _bad_removed,
                                    _bad_group_removed, _bad_dup, _bad_dup_group_item, _bad_shared, _bad_hint,
                                    _bad_name_len])
def test_capsules_put_invalid_not_saved(client, appdata, mutate):
    c = ok(client.get("/api/capsules"), "capsules")
    before = (appdata / "capsules.json").read_bytes()
    mutate(c)
    fail(client.put("/api/capsules", json=c), "capsules", "INVALID_ARGUMENT")
    assert (appdata / "capsules.json").read_bytes() == before


def test_capsules_reset(client):
    c = ok(client.get("/api/capsules"), "capsules")
    c["groups"][0]["name"] = "民商"
    ok(client.put("/api/capsules", json=c), "capsules")
    req_valid("capsules_reset", {})
    assert ok(client.post("/api/capsules/reset", json={}), "capsules_reset") == _default()
    assert ok(client.post("/api/capsules/reset"), "capsules_reset") == _default()  # 空请求体等同 {}
    assert ok(client.get("/api/capsules"), "capsules") == _default()
    fail(client.post("/api/capsules/reset", json={"x": 1}), "capsules_reset", "INVALID_ARGUMENT")


def test_capsules_new_default_merged_hidden(make_client, tmp_path, appdata):
    """升级后默认配置新增的胶囊和分组，以隐藏状态补进本机配置；本机改动保留。"""
    skills = tmp_path / "skills"
    skills.mkdir()
    default = _default()
    names = set(default["shared"]) | {s for g in default["groups"] for it in g["items"] for s in it.get("skills", [])}
    for n in names | {"new-skill"}:
        (skills / n).mkdir()
        (skills / n / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    (skills / "capsules.default.json").write_text(json.dumps(default, ensure_ascii=False), encoding="utf-8")
    c1 = make_client(skills_dirs=[skills])
    local = ok(c1.get("/api/capsules"), "capsules")
    local["groups"][0]["name"] = "民商"
    ok(c1.put("/api/capsules", json=local), "capsules")
    c1.close()

    default["groups"][0]["items"].append({"id": "new-cap", "name": "新胶囊", "kind": "skill",
                                          "skills": ["new-skill"], "outputs": [], "hidden": False, "custom": False})
    default["groups"].append({"id": "new-group", "name": "新分组", "hidden": False, "items": [
        {"id": "new-cap2", "name": "新胶囊2", "kind": "skill", "skills": ["new-skill"], "outputs": [],
         "hidden": False, "custom": False}]})
    (skills / "capsules.default.json").write_text(json.dumps(default, ensure_ascii=False), encoding="utf-8")
    c2 = make_client(skills_dirs=[skills])
    merged = ok(c2.get("/api/capsules"), "capsules")
    assert merged["groups"][0]["name"] == "民商"
    added = [it for it in merged["groups"][0]["items"] if it["id"] == "new-cap"]
    assert added and added[0]["hidden"] is True
    ng = [g for g in merged["groups"] if g["id"] == "new-group"][0]
    assert ng["hidden"] is True and ng["items"][0]["hidden"] is True
    # 契约 1.2 N35②：新补进来的胶囊标 new=true；原有的不标
    assert added[0]["new"] is True and ng["items"][0]["new"] is True
    assert all("new" not in it for g in merged["groups"] for it in g["items"]
               if it["id"] not in ("new-cap", "new-cap2"))
    # 律师显示或隐藏一次后，界面 PUT 时不带 new：清掉，之后不再补标
    for g in merged["groups"]:
        for it in g["items"]:
            it.pop("new", None)
    ok(c2.put("/api/capsules", json=merged), "capsules")
    again = ok(c2.get("/api/capsules"), "capsules")
    assert all("new" not in it for g in again["groups"] for it in g["items"])


# ---------- /api/connection/test ----------

@pytest.fixture
def fake_llm():
    f = Fake6000D()
    with ServerThread(f.app()) as s:
        s.fake = f
        yield s


@pytest.fixture
def fake_prep():
    f = Fake395()
    with ServerThread(f.app()) as s:
        s.fake = f
        yield s


def _put_servers(client, sv: dict):
    s = ok(client.get("/api/settings"), "settings")
    s["servers"] = sv
    ok(client.put("/api/settings", json=s), "settings")


def test_connection_primary(make_client, fake_llm, fake_prep):
    c = make_client(key="LBTEST-KEY")
    _put_servers(c, servers(fake_llm.url + "/v1", None, fake_prep.url, None))
    req_valid("connection_test", {"server": "llm"})
    v = ok(c.post("/api/connection/test", json={"server": "llm"}), "connection_test")
    assert v["reachable"] and v["route"] == "primary" and v["key_valid"] is True and v["latency_ms"] >= 0
    assert "所内" in v["message"]
    probe = [s for s in fake_llm.fake.seen if s["path"] == "/v1/chat/completions"][0]
    assert probe["body"]["max_tokens"] == 1 and probe["headers"]["authorization"] == "Bearer LBTEST-KEY"
    v = ok(c.post("/api/connection/test", json={"server": "prep"}), "connection_test")
    assert v["reachable"] and v["route"] == "primary" and v["key_valid"] is None


def test_connection_alternate(make_client, fake_llm, fake_prep):
    c = make_client(key="LBTEST-KEY")
    down = f"http://127.0.0.1:{closed_port()}"
    _put_servers(c, servers(down + "/v1", fake_llm.url + "/v1", down, fake_prep.url))
    v = ok(c.post("/api/connection/test", json={"server": "llm"}), "connection_test")
    assert v["reachable"] and v["route"] == "alternate" and "所外" in v["message"]
    v = ok(c.post("/api/connection/test", json={"server": "prep"}), "connection_test")
    assert v["reachable"] and v["route"] == "alternate"


def test_connection_both_down(make_client):
    c = make_client(key="LBTEST-KEY")
    d1, d2 = f"http://127.0.0.1:{closed_port()}", f"http://127.0.0.1:{closed_port()}"
    _put_servers(c, servers(d1 + "/v1", d2 + "/v1", d1, d2))
    for server in ("llm", "prep"):
        v = ok(c.post("/api/connection/test", json={"server": server}), "connection_test")
        assert v == {"reachable": False, "key_valid": None, "latency_ms": None, "route": None,
                     "message": "无法连接服务器，请检查网络"}


def test_connection_key_states(make_client, fake_llm):
    c = make_client(key=None)
    _put_servers(c, servers(fake_llm.url + "/v1", None, fake_llm.url, None))
    v = ok(c.post("/api/connection/test", json={"server": "llm"}), "connection_test")
    assert v["reachable"] and v["key_valid"] is None and "尚未设置 Key" in v["message"]
    fake_llm.fake.key_status = 401
    c2 = make_client(key="LBTEST-BAD")
    v = ok(c2.post("/api/connection/test", json={"server": "llm"}), "connection_test")
    assert v["key_valid"] is False


def test_connection_bad_request(client):
    fail(client.post("/api/connection/test", json={"server": "evil"}), "connection_test", "INVALID_ARGUMENT")


# ---------- 统一错误 ----------

def test_internal_error_body(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("LBTEST-SECRET-DETAIL")
    monkeypatch.setattr(client.app.state.lb.cases, "recent", boom)
    r = client.get("/api/case/recent")
    assert r.status_code == 500
    assert r.json() == {"ok": False, "error": {"code": "INTERNAL", "message": "内部错误，请重试；多次出现请联系技术支持"}}


# ---------- 日志 ----------

def test_logs_have_no_names_or_paths(make_client, case_root, appdata, cases_dir, tmp_path, monkeypatch):
    c = make_client(key="LBTEST-KEY")
    ok(c.post("/api/case/open", json={"path": str(case_root), "template": "civil"}), "case_open")
    ok(c.get("/api/case/recent"), "case_recent")
    fail(c.post("/api/case/open", json={"path": str(cases_dir / "不存在-LBTEST-GONE")}), "case_open",
         "INVALID_ARGUMENT")
    od = tmp_path / "LBTEST-CLOUD"
    (od / "案件-LBTEST-SYNC").mkdir(parents=True)
    monkeypatch.setenv("OneDrive", str(od))
    fail(c.post("/api/case/open", json={"path": str(od / "案件-LBTEST-SYNC")}), "case_open", "CASE_IN_SYNC_FOLDER")

    def boom(*a, **k):
        raise RuntimeError(str(case_root / "证据" / MATERIAL))
    monkeypatch.setattr(c.app.state.lb.cases, "recent", boom)
    assert c.get("/api/case/recent").status_code == 500
    c.close()
    from lawbench import logs
    logs.close()
    files = list((appdata / "logs").glob("*"))
    assert files
    text = "".join(p.read_text(encoding="utf-8") for p in files)
    assert '"op": "case_open"' in text and "RuntimeError" in text
    for bad in [CASE_NAME, "LBTEST", MATERIAL, "借条", str(tmp_path), str(cases_dir), "证据", "Bearer"]:
        assert bad not in text, bad
    for line in text.splitlines():
        rec = json.loads(line)
        assert set(rec) <= {"t", "module", "op", "status", "case_id", "ms", "error"}
