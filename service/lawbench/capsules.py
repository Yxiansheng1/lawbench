"""胶囊配置（Spec 10.3；契约 skill/capsules.schema.json）。

默认配置 capsules.default.json 在第一个 Skill 目录（<安装目录>/skills/）；本机配置在 <应用数据>/capsules.json。
首次启动和"恢复默认"从默认配置复制；默认配置新增的分组和胶囊，以隐藏状态补进本机配置。
"""
from __future__ import annotations

import copy
import pathlib
import threading

from . import contracts, logs
from .errors import ApiError

SCHEMA = "skill/capsules.schema.json"


class CapsuleStore:
    def __init__(self, appdata: pathlib.Path, skills_dirs: list[pathlib.Path]):
        self.path = pathlib.Path(appdata) / "capsules.json"
        self.skills_dirs = [pathlib.Path(d) for d in skills_dirs]
        self._lock = threading.Lock()

    # ---------- 默认配置与已安装 Skill ----------

    def default(self) -> dict:
        data = contracts.read_json(self.skills_dirs[0] / "capsules.default.json")
        contracts.validate(SCHEMA, "", data)
        return data

    def skill_exists(self, name: str) -> bool:
        return any((d / name / "SKILL.md").is_file() for d in self.skills_dirs)

    # ---------- 本机配置 ----------

    def ensure(self) -> dict:
        """首次启动复制默认配置；已有本机配置时把默认配置新增的分组、胶囊以隐藏状态补进去。"""
        with self._lock:
            default = self.default()
            if not self.path.exists():
                contracts.write_json(self.path, default, SCHEMA)
                return default
            local = contracts.read_json(self.path)
            contracts.validate(SCHEMA, "", local)  # 损坏或 v 不认识：抛异常，接口层返回 HTTP 500；恢复用 reset
            merged, added = _merge_new(local, default)
            if added:
                contracts.write_json(self.path, merged, SCHEMA)
                logs.event("capsules", "merge_new", status="ok")
            return merged

    def get(self) -> dict:
        return self.ensure()

    def put(self, data: dict) -> dict:
        default = self.default()
        reason = self._check(data, default)
        if reason:
            logs.event("capsules", "put", status="fail", error=f"INVALID_ARGUMENT:{reason}")
            raise ApiError("INVALID_ARGUMENT", reason)
        with self._lock:
            contracts.write_json(self.path, data, SCHEMA)
        return data

    def reset(self) -> dict:
        default = self.default()
        with self._lock:
            contracts.write_json(self.path, default, SCHEMA)
        return default

    # ---------- PUT 校验（Spec 10.3 服务端校验） ----------

    def _check(self, data: dict, default: dict) -> str | None:
        ids: list[str] = []
        for g in data["groups"]:
            ids.append(g["id"])
            for it in g["items"]:
                ids.append(it["id"])
                # 工具只能是 invoice、retainer：由契约 tool_item 的枚举保证
                if it["kind"] == "skill" and not all(self.skill_exists(s) for s in it["skills"]):
                    return "unknown_skill"
        if len(ids) != len(set(ids)):
            return "duplicate_id"
        present = set(ids)
        for g in default["groups"]:
            if g["id"] not in present:
                return "default_removed"
            for it in g["items"]:
                if it["id"] not in present:
                    return "default_removed"
        if data["shared"] != default["shared"] or data["hint"] != default["hint"]:
            return "shared_or_hint_changed"
        if not all(self.skill_exists(s) for s in data["shared"]):
            return "unknown_skill"
        return None


def _merge_new(local: dict, default: dict) -> tuple[dict, bool]:
    """升级后默认配置里新增的胶囊补进本机配置：hidden=true、new=true（契约 1.2 N35②；律师显示或隐藏一次后由界面
    PUT /api/capsules 清掉 new）。"""
    merged = copy.deepcopy(local)
    present = {g["id"] for g in merged["groups"]} | {it["id"] for g in merged["groups"] for it in g["items"]}
    groups = {g["id"]: g for g in merged["groups"]}
    added = False
    for dg in default["groups"]:
        if dg["id"] not in present:
            g = copy.deepcopy(dg)
            g["hidden"] = True
            g["items"] = [dict(it, hidden=True, new=True) for it in g["items"] if it["id"] not in present]
            merged["groups"].append(g)
            groups[g["id"]] = g
            present.add(g["id"])
            present.update(it["id"] for it in g["items"])
            added = True
            continue
        for it in dg["items"]:
            if it["id"] not in present:
                groups[dg["id"]]["items"].append(dict(copy.deepcopy(it), hidden=True, new=True))  # 契约 1.2 N35②
                present.add(it["id"])
                added = True
    # shared、hint 律师不能改，始终与默认配置相同
    if merged["shared"] != default["shared"] or merged["hint"] != default["hint"]:
        merged["shared"] = copy.deepcopy(default["shared"])
        merged["hint"] = default["hint"]
        added = True
    return merged, added
