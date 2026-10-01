"""归档目录与材料匹配（Spec 12.4"匹配"；原版规则 lawyer-archiving 第三步；契约 tools/case_archive_match、
skill/archive_catalog）。

四条规则：
1. 跳过 generated 项（结案报告：程序生成）。忽略：~$ 开头的临时文件、._ 开头的文件（这两类不进材料清单，
   这里另扫原件区列出来）、名字形如"微信图片_数字""IMG_数字"的、加密或无法读取的。
2. 文件名（不含扩展名，不分大小写）命中某项关键词就归入该项；命中多项时，先取 folders 包含材料所在文件夹的项，
   再取命中关键词最长的（仍并列取编号小的）。
3. 没命中关键词、但所在文件夹只对应一项的，按文件夹归入。
4. 其余列为未匹配。
"所在文件夹"指材料相对案件根目录的上级目录；folders 里的一项（如 03一审/我方证据）包含它本身和它下面的子文件夹。
"""
from __future__ import annotations

import os
import pathlib
import re

from .. import contracts
from ..case import gate
from ..errors import ApiError

CATALOGS = ("民事行政卷", "刑事卷", "常法卷", "其他非诉卷")
_MESSY = re.compile(r"^(微信图片|IMG)_\d+", re.IGNORECASE)
_UNREADABLE = ("failed", "source_deleted")
# 能转成 PDF 放进卷宗的材料类型（md 不行：没有可靠的版式转换，按复核 P3-2 在保存方案时就拒）
CONVERTIBLE = ("pdf", "docx", "doc", "wps", "xlsx", "xls", "csv", "txt", "image")


def load_catalog(skills_dirs, name: str) -> dict:
    """skills/case-archiving/catalogs/<卷类>.json（第一个有它的 Skill 目录），按契约校验。"""
    if name not in CATALOGS:
        raise ApiError("INVALID_ARGUMENT", "unknown_catalog")
    for d in skills_dirs:
        p = pathlib.Path(d) / "case-archiving" / "catalogs" / f"{name}.json"
        if p.is_file():
            data = contracts.read_json(p)
            contracts.validate("skill/archive_catalog.schema.json", "", data)
            return data
    raise ApiError("TEMPLATE_MISSING", "catalog")


def _stem(rel_path: str) -> str:
    return pathlib.PurePosixPath(rel_path).stem


def _folder(rel_path: str) -> str:
    return rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""


def _first_folder(rel_path: str) -> str:
    parts = rel_path.split("/")
    return parts[0] if len(parts) > 1 else ""


def _in_folders(folder: str, folders: list[str]) -> bool:
    f = folder.casefold()
    return any(f == x.casefold() or f.startswith(x.casefold() + "/") for x in folders)


def stray_files(root: str) -> list[tuple[str, str]]:
    """原件区里不进材料清单的临时文件：~$ 开头（Office 锁文件）、._ 开头（苹果的附属文件）。
    返回 [(相对路径, 原因)]。不进 工作区/、成果/ 和以 . 开头的目录，不跟随链接。"""
    out: list[tuple[str, str]] = []
    top = {gate.WORK.casefold(), gate.OUTPUT.casefold()}
    for dp, dns, fns in os.walk(root):
        rel_dir = os.path.relpath(dp, root).replace("\\", "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        dns[:] = sorted(d for d in dns if not d.startswith(".") and not os.path.islink(os.path.join(dp, d))
                        and not (rel_dir == "" and d.casefold() in top))
        for fn in sorted(fns):
            if fn.startswith(("~$", "._")):
                out.append(((rel_dir + "/" if rel_dir else "") + fn, "临时文件"))
    return out


def match(root: str, index: dict, catalog: dict) -> dict:
    items = [it for it in catalog["items"] if not it.get("generated")]
    result_items = {it["code"]: {"code": it["code"], "name": it["name"], "required": it["required"], "matched": []}
                    for it in items}
    unmatched: list[str] = []
    ignored: list[dict] = [{"name": rel, "reason": why} for rel, why in stray_files(root)]
    for m in index["materials"]:
        rel, name = m["rel_path"], m["name"]
        stem = _stem(rel)
        if stem.startswith(("~$", "._")):
            ignored.append({"name": name, "reason": "临时文件"})
            continue
        if _MESSY.match(stem):
            ignored.append({"name": name, "reason": "命名混乱"})
            continue
        if m["status"] in _UNREADABLE:
            ignored.append({"name": name, "reason": "加密或无法读取"})
            continue
        folder = _folder(rel)
        key = stem.casefold()
        hits = []
        for it in items:
            lens = [len(k) for k in it["keywords"] if k.casefold() in key]
            if lens:
                hits.append((it, max(lens)))
        chosen, reason = None, None
        if hits:
            in_f = [(it, n) for it, n in hits if _in_folders(folder, it["folders"])]
            pool = in_f or hits
            chosen = sorted(pool, key=lambda x: (-x[1], x[0]["code"]))[0][0]
            reason = "文件夹和关键词" if in_f else "关键词"
        else:
            by_folder = [it for it in items if folder and _in_folders(folder, it["folders"])]
            if len(by_folder) == 1:
                chosen, reason = by_folder[0], "文件夹"
        if chosen is None:
            unmatched.append(name)
        else:
            result_items[chosen["code"]]["matched"].append(
                {"name": name, "folder": _first_folder(rel), "reason": reason})
    return {"catalog": catalog["id"], "items": list(result_items.values()), "unmatched": unmatched,
            "ignored": ignored}


def check_plan(catalog: dict, plan: dict, index: dict) -> tuple[list[dict], list[str]]:
    """归档方案的程序校验（保存方案和生成归档共用）：编号必须是该卷类目录里的、不能是程序生成的项（结案报告）、
    不能重复，否则 INVALID_ARGUMENT；材料名必须在材料清单里，否则 MATERIAL_NOT_FOUND。
    返回 (缺失的必交项 [{code, name}], 提醒)。"""
    by_code = {it["code"]: it for it in catalog["items"]}
    codes = [it["code"] for it in plan["items"]]
    if len(codes) != len(set(codes)):
        raise ApiError("INVALID_ARGUMENT", "duplicate_code")
    for c in codes:
        if c not in by_code:
            raise ApiError("INVALID_ARGUMENT", "unknown_code")
        if by_code[c].get("generated"):
            raise ApiError("INVALID_ARGUMENT", "generated_item")
    materials = {m["name"]: m for m in index["materials"]}
    warnings: list[str] = []
    seen: dict[str, int] = {}
    for it in plan["items"]:
        for name in it["materials"]:
            m = materials.get(name)
            if m is None:
                raise ApiError("MATERIAL_NOT_FOUND", "unknown_material")
            if m["type"] not in CONVERTIBLE:
                raise ApiError("INVALID_ARGUMENT", "not_convertible")     # 如 .md：生成时转不了 PDF，保存方案时就拒
            if m["status"] in _UNREADABLE:
                warnings.append(f"「{name}」导入时没通过（加密、读不了或有外链），生成时会跳过，请换成可读的版本或从方案中去掉")
            if name in seen and seen[name] != it["code"]:
                warnings.append(f"「{name}」同时放在第 {seen[name]} 项和第 {it['code']} 项，卷宗里会出现两次")
            seen.setdefault(name, it["code"])
    missing = [{"code": it["code"], "name": it["name"]} for it in catalog["items"]
               if it["required"] and not it.get("generated") and it["code"] not in codes]
    return missing, warnings
