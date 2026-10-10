"""原文查看 GET /api/source（Spec 4.3、9.5 第 883 行；契约 api/source）。

按出处文本找到这份材料的定位单元，返回该单元的文本；PDF 另返回该页（范围取首页）的页面图片，定位到页、不做文字高亮。
定位复用出处核对（T10）的 checks.parse：find_cites 解析出处、Material.check_loc 判位置、Material.text_at 取文本；
页面图片复用识别（T12）的 ocr.render.render_png（200 DPI、长边不超过 2480 像素，内存里渲染、不落临时文件）。

source_changed：契约请求只有 case_id、material_id、citation，没有任务编号和版本。按本案各任务 result.json 里记下的
出处（材料编号 + 版本 + 位置）判断：同一材料同一位置有记录、而且没有一条的版本等于现在的原件哈希 → true；
没有记录（如来自检索）或有一条是现在的版本 → false。

只读：读 index.json、材料文本、原件（渲染）、result.json；不写文件。日志只记材料编号与单元类型。
"""
from __future__ import annotations

import json
import re

from .. import contracts, logs
from ..checks.parse import MaterialSet, find_cites
from ..errors import ApiError
from ..ocr import render
from . import gate
from .task import TASK_DIR


def view(root: str, case_id: str, index: dict, material_id: str, citation: str, task_id: str | None = None) -> dict:
    meta = next((m for m in index["materials"] if m["material_id"] == material_id), None)
    if meta is None:
        raise ApiError("MATERIAL_NOT_FOUND", "source_material")
    loc = _loc_for(meta["name"], citation)
    if meta["status"] == "failed":
        raise ApiError("MATERIAL_NOT_READY", "failed")
    mat = MaterialSet.from_case(root, {"materials": [meta]}).get(meta["name"])
    if mat.units is None:
        raise ApiError("MATERIAL_NOT_READY", "text_missing")
    problem = mat.check_loc(loc)
    if problem:
        raise ApiError("INVALID_ARGUMENT", "source_loc", detail=f"出处位置不对：{problem}")
    png = None
    if meta["type"] == "pdf" and loc["unit"] == "page":
        png = _page_png(root, meta, loc["from"])
    logs.event("source", "view", case_id=case_id, material_id=material_id, unit=loc["unit"])
    return {"name": meta["name"], "loc": loc, "text": mat.text_at(loc), "page_png_base64": png,
            "source_changed": _changed(root, meta, loc, task_id)}


def _loc_for(name: str, citation: str) -> dict:
    """出处里属于这份材料的第一处位置。出处必须整串是一条合格出处（契约已按正则校验）；
    〔未找到依据〕〔推断〕没有位置，名字对不上这份材料的也拒绝。"""
    cites = find_cites(citation)
    if len(cites) != 1 or cites[0].raw != citation or not cites[0].ok or cites[0].fixed:
        raise ApiError("INVALID_ARGUMENT", "source_citation")
    item = next((i for i in cites[0].items if i.name == name), None)
    if item is None:
        raise ApiError("INVALID_ARGUMENT", "source_other_material")
    return item.loc


def _page_png(root: str, meta: dict, page_no: int) -> str | None:
    """渲染不了（加密、损坏、原件已不在）只是没有图，文本照常返回；原因只进日志。"""
    import base64
    try:
        path = gate.resolve_read(root, meta["rel_path"], op="source_view")
        return base64.b64encode(render.render_png(path, "pdf", page_no)).decode("ascii")
    except (render.RenderError, ApiError, OSError) as e:
        logs.event("source", "page_image", status="fail", material_id=meta["material_id"],
                   error=getattr(e, "code", None) or type(e).__name__)
        return None


def _changed(root: str, meta: dict, loc: dict, task_id: str | None = None) -> bool:
    """给了 task_id（契约 1.4）：只看这个任务记下的出处——这份材料在该任务里记的版本与现在不同就是变了
    （版本按材料记，同一任务里位置写法不同也算，如记的是第2-3页、点的是第2页）；这个任务没引过这份材料则为 False。
    没给：照旧扫本案全部任务，同材料同位置有记录、且没有一条是现在的版本才算变了。"""
    if task_id is not None:
        if not re.fullmatch(r"[TP]-\d{14}-[0-9a-f]{4}", task_id):
            raise ApiError("TASK_NOT_FOUND", "bad_task_id")
        res = _result(root, task_id)
        if res is None:
            raise ApiError("TASK_NOT_FOUND", "source_task")
        versions = {c["material_version"] for c in res["citations"] if c["material_id"] == meta["material_id"]}
        return bool(versions) and meta["sha256"] not in versions
    base = gate.resolve_internal(root, TASK_DIR, op="source_view")
    if not base.is_dir():
        return False
    key = json.dumps(loc, sort_keys=True)
    versions = set()
    for d in base.iterdir():
        res = _result(root, d.name)
        if res is None:
            continue  # 还没开始执行的任务单（没有 result.json）、损坏的记录不算
        versions |= {c["material_version"] for c in res["citations"]
                     if c["material_id"] == meta["material_id"] and json.dumps(c["loc"], sort_keys=True) == key}
    return bool(versions) and meta["sha256"] not in versions


def _result(root: str, name: str) -> dict | None:
    try:
        path = gate.resolve_internal(root, f"{TASK_DIR}/{name}/result.json", op="source_view")
        res = json.loads(path.read_text(encoding="utf-8"))
        return None if contracts.errors("files/result.schema.json", "", res) else res
    except (ApiError, OSError, ValueError):
        return None
