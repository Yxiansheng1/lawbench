"""T9（T14 联调派修）：原文查看 GET /api/source。

文字版 PDF / 扫描版（识别所得）/ docx / 图片四种材料各一例，越界位置、别的材料的出处、别案材料、
〔推断〕、source_changed、日志只记材料编号与单元类型。返回都按契约 api/source 校验。
"""
from __future__ import annotations

import base64
import os
import io
import json

import pytest
from PIL import Image

from lawbench.case import texts
from lawbench.config import REPO_ROOT
from lawbench.ocr import render

from t8_helpers import fail, ok
from test_ocr_queue import JPG, PDF, Env, Fake395, expected_md
from conftest import IS_WIN, ServerThread, make_junction
from lawbench import logs
import t8_helpers
import shutil

FIX = REPO_ROOT / "tests" / "fixtures"
TEXT_PDF = FIX / "criminal-01" / "起诉意见书.pdf"
DOCX = FIX / "civil-01" / "借条.docx"
SCHEMA = "api/source.schema.json"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    fake = Fake395()
    with ServerThread(fake.app) as srv:
        base = tmp_path_factory.mktemp("src")
        env = Env(base, srv.url, {"卷一/起诉意见书.pdf": TEXT_PDF, "卷一/讯问笔录.pdf": PDF,
                                  "卷一/转账截图.jpg": JPG, "卷二/借条.docx": DOCX})
        env.st.ocr.start()
        for name, pages in (("讯问笔录", [1, 2, 3]), ("转账截图", [1])):
            v = env.submit(env.material(name)["material_id"], pages)
            env.wait(v["job_id"], ("done",))
        yield env
        env.close()


def get(env, material_id: str, citation: str, case_id: str | None = None):
    return env.client.get("/api/source", params={"case_id": case_id or env.case_id, "material_id": material_id,
                                                 "citation": citation})


def unit_text(env, name: str, no: int) -> str:
    m = env.material(name)
    return next(u.text for u in texts.split_units(env.text(m), m["unit"]) if u.no == no)


def png_size(b64: str) -> tuple[int, int]:
    raw = base64.b64decode(b64)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    return Image.open(io.BytesIO(raw)).size


def test_text_pdf_page_text_and_image(world):
    m = world.material("起诉意见书")
    v = ok(get(world, m["material_id"], "〔起诉意见书 第2页〕"), SCHEMA)
    assert (v["name"], v["loc"], v["source_changed"]) == ("起诉意见书", {"unit": "page", "from": 2}, False)
    assert v["text"] == unit_text(world, "起诉意见书", 2) and v["text"]
    want = Image.open(io.BytesIO(render.render_png(world.root / m["rel_path"], "pdf", 2))).size
    assert png_size(v["page_png_base64"]) == want                       # 同一条渲染路径：200 DPI、长边上限


def test_page_range_shows_first_page_image_and_all_text(world):
    m = world.material("起诉意见书")
    v = ok(get(world, m["material_id"], "〔起诉意见书 第2-3页〕"), SCHEMA)
    assert v["loc"] == {"unit": "page", "from": 2, "to": 3}
    assert v["text"] == unit_text(world, "起诉意见书", 2) + "\n" + unit_text(world, "起诉意见书", 3)
    page2 = render.render_png(world.root / m["rel_path"], "pdf", 2)
    assert base64.b64decode(v["page_png_base64"]) == page2


def test_scanned_pdf_ocr_text_and_page_image(world):
    m = world.material("讯问笔录")
    v = ok(get(world, m["material_id"], "〔讯问笔录 第3页〕"), SCHEMA)
    png3 = render.render_png(PDF, "pdf", 3)
    assert expected_md(png3) in v["text"] and v["text"] == unit_text(world, "讯问笔录", 3)
    assert base64.b64decode(v["page_png_base64"]) == png3


def test_docx_paragraph_no_image(world):
    m = world.material("借条")
    assert m["unit"] == "para"
    v = ok(get(world, m["material_id"], "〔借条 第2段〕"), SCHEMA)
    assert v["text"] == unit_text(world, "借条", 2) and v["text"]
    assert v["page_png_base64"] is None                                   # 只有 PDF 带页面图片（Spec 4.3）


def test_image_material_ocr_text_no_image(world):
    m = world.material("转账截图")
    v = ok(get(world, m["material_id"], "〔转账截图 第1页〕"), SCHEMA)
    assert expected_md(render.render_png(JPG, "image", 1)) in v["text"]
    assert v["page_png_base64"] is None


def test_out_of_range_and_wrong_unit(world):
    m = world.material("起诉意见书")
    body = fail(get(world, m["material_id"], "〔起诉意见书 第9页〕"), "INVALID_ARGUMENT")
    assert "超出材料范围" in body["error"]["message"]
    fail(get(world, m["material_id"], "〔起诉意见书 第2段〕"), "INVALID_ARGUMENT")
    fail(get(world, m["material_id"], "〔推断〕"), "INVALID_ARGUMENT")
    fail(get(world, m["material_id"], "起诉意见书 第2页"), "INVALID_ARGUMENT")      # 契约正则
    fail(world.client.get("/api/source", params={"case_id": world.case_id, "material_id": m["material_id"]}),
         "INVALID_ARGUMENT")


def test_multi_item_citation_picks_this_material(world):
    m = world.material("借条")
    v = ok(get(world, m["material_id"], "〔起诉意见书 第2页、借条 第1段〕"), SCHEMA)
    assert v["name"] == "借条" and v["loc"] == {"unit": "para", "from": 1}


def test_other_material_and_other_case_rejected(world, tmp_path):
    a = world.material("起诉意见书")
    fail(get(world, a["material_id"], "〔借条 第1段〕"), "INVALID_ARGUMENT")   # 出处写的是另一份材料
    fail(get(world, "M0999", "〔起诉意见书 第1页〕"), "MATERIAL_NOT_FOUND")
    # 别案：另开一个案件，它的 M0001 是别的材料；拿本案的出处去查，查不到本案的文本
    other = tmp_path / "别案"
    other.mkdir()
    (other / "情况说明.txt").write_text("别案的说明\n第二行\n", encoding="utf-8")
    cid = ok(world.client.post("/api/case/open", json={"path": str(other)}), "api/case_open.schema.json")["case_id"]
    ok(world.client.post("/api/materials/scan", json={"case_id": cid}), "api/materials_scan.schema.json")
    fail(get(world, "M0001", f"〔{world.material('起诉意见书')['name']} 第1页〕", case_id=cid), "INVALID_ARGUMENT")
    fail(get(world, a["material_id"], "〔起诉意见书 第1页〕", case_id=cid), "MATERIAL_NOT_FOUND")  # 别案没有这个编号
    fail(get(world, "M0001", "〔起诉意见书 第1页〕", case_id="00000000-0000-4000-8000-000000000000"),
         "CASE_NOT_FOUND")


def _result(env, task_id: str, cites: list[dict]) -> None:
    d = env.root / "工作区" / "任务" / task_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "result.json").write_text(json.dumps({
        "v": 1, "task_id": task_id, "status": "completed",
        "usage": {"model_calls": 1, "tool_calls": 1, "elapsed_s": 1}, "drafts": [], "citation_check": None,
        "coverage": None, "citations": cites, "finished_at": None}, ensure_ascii=False), encoding="utf-8")


def test_source_changed_by_recorded_version(world):
    m = world.material("起诉意见书")
    old = "0" * 64
    rec = lambda ver, page: {"material_id": m["material_id"], "material_version": ver, "name": m["name"],  # noqa: E731
                             "loc": {"unit": "page", "from": page}}
    _result(world, "T-20261003000001-aaaa", [rec(old, 4)])
    assert ok(get(world, m["material_id"], "〔起诉意见书 第4页〕"), SCHEMA)["source_changed"] is True
    assert ok(get(world, m["material_id"], "〔起诉意见书 第5页〕"), SCHEMA)["source_changed"] is False  # 没记录
    _result(world, "T-20261003000002-bbbb", [rec(m["sha256"], 4)])     # 之后有任务按现在的版本引过同一处
    assert ok(get(world, m["material_id"], "〔起诉意见书 第4页〕"), SCHEMA)["source_changed"] is False


def test_log_only_material_id_and_unit(world, caplog):
    m = world.material("借条")
    with caplog.at_level("INFO", logger="lawbench.events"):
        ok(get(world, m["material_id"], "〔借条 第1段〕"), SCHEMA)
    log = "\n".join(r.getMessage() for r in caplog.records if r.name == "lawbench.events")
    recs = [json.loads(x) for x in log.splitlines() if '"module": "source"' in x]
    assert {"material_id": m["material_id"], "unit": "para"}.items() <= recs[-1].items()
    for s in ("借条", "起诉意见书", "LBFX-", "识别文本", "第1段"):
        assert s not in log


# ---------- 复核 AMEND（P2）：两处路径闸门的回归用例 ----------

win_only = pytest.mark.skipif(not IS_WIN, reason="junction 只在 Windows 上有")


@pytest.fixture
def plain(tmp_path):
    """不带识别的小案件：卷一/起诉意见书.pdf（文字版）。每例一份，用例会把目录换成联接。"""
    env = t8_helpers.Env(tmp_path / "案", {"卷一/起诉意见书.pdf": TEXT_PDF})
    yield env
    env.close()


def _mid(env) -> str:
    return next(m["material_id"] for m in env.client.app.state.lb.materials.index(env.case_id)["materials"])


def _source(env, citation="〔起诉意见书 第1页〕"):
    return env.client.get("/api/source", params={"case_id": env.case_id, "material_id": _mid(env), "citation": citation})


def _events(caplog) -> list[dict]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "lawbench.events"]


@win_only
def test_gate_original_folder_junction_no_image(plain, tmp_path, caplog):
    """原件所在文件夹换成指向案外的联接：不读案外的原件出图，文本（工作区里的材料文本）照返，日志有 gate denied。"""
    outside = tmp_path / "案外"
    outside.mkdir()
    shutil.copy(TEXT_PDF, outside / "起诉意见书.pdf")
    vol = plain.root / "卷一"
    shutil.rmtree(vol)
    make_junction(vol, outside)
    with caplog.at_level("INFO", logger="lawbench.events"):
        v = ok(_source(plain), SCHEMA)
    assert v["page_png_base64"] is None and v["text"]
    ev = _events(caplog)
    assert any(e["module"] == "gate" and e["op"] == "source_view" and e["status"] == "denied" for e in ev), ev
    assert any(e["module"] == "source" and e["op"] == "page_image" and e["status"] == "fail" for e in ev)


def _stale_result(folder: pathlib.Path, task_id: str, mid: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "result.json").write_text(json.dumps({
        "v": 1, "task_id": task_id, "status": "completed",
        "usage": {"model_calls": 1, "tool_calls": 1, "elapsed_s": 1}, "drafts": [], "citation_check": None,
        "coverage": None, "finished_at": None,
        "citations": [{"material_id": mid, "material_version": "0" * 64, "name": "起诉意见书",
                       "loc": {"unit": "page", "from": 1}}]}, ensure_ascii=False), encoding="utf-8")


@win_only
def test_gate_task_folder_junction_not_read(plain, tmp_path):
    """工作区/任务/<id> 换成指向案外的联接：案外那份 result.json（旧版本的出处记录）不被读，source_changed=false。"""
    tid = "T-20261003000003-cccc"
    outside = tmp_path / "案外任务"
    _stale_result(outside, tid, _mid(plain))
    tasks = plain.root / "工作区" / "任务"
    tasks.mkdir(parents=True, exist_ok=True)
    make_junction(tasks / tid, outside)
    assert ok(_source(plain), SCHEMA)["source_changed"] is False
    # 对照：同一份记录真放在案内，就会提示
    os.rmdir(tasks / tid)                                              # 只拆联接，不动案外目录
    _stale_result(tasks / tid, tid, _mid(plain))
    assert ok(_source(plain), SCHEMA)["source_changed"] is True


@win_only
def test_gate_tasks_root_junction_out_of_case(plain, tmp_path):
    """工作区/任务 整个目录换成联接：OUT_OF_CASE。"""
    outside = tmp_path / "案外任务根"
    _stale_result(outside / "T-20261003000004-dddd", "T-20261003000004-dddd", _mid(plain))
    tasks = plain.root / "工作区" / "任务"
    if tasks.exists():
        shutil.rmtree(tasks)
    make_junction(tasks, outside)
    fail(_source(plain), "OUT_OF_CASE")


def test_log_fields_format_checked():
    with pytest.raises(ValueError):
        logs.event("source", "view", material_id="借条")          # 不是材料编号，不许借这个字段记别的
    with pytest.raises(ValueError):
        logs.event("source", "view", material_id="M00012")
    with pytest.raises(ValueError):
        logs.event("source", "view", unit="第1页")

