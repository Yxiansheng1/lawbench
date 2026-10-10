"""案件注册表（<应用数据>/cases.json）、case.db 初始化、工作区/成果目录初始化（Spec 4.1）。"""
from __future__ import annotations

import os
import pathlib
import sqlite3
import threading
import uuid
from datetime import datetime

from .. import contracts, logs
from ..errors import ApiError
from . import gate

SCHEMA_VERSION = "1"
CASES_SCHEMA = "files/cases.schema.json"

WORK_DIRS = [
    "工作区",
    "工作区/材料",
    "工作区/材料/文本",
    "工作区/材料/识别页",
    "工作区/wiki",
    "工作区/任务",
    "工作区/会话",
    "工作区/临时",
    "成果",
]

# contracts/formats.md 第 1.1 节
_TRIAL6 = ["我方文件", "我方证据", "对方文件", "对方证据", "庭审准备", "法院文书"]
_INVEST5 = ["我方文件", "我方证据", "对方文件", "对方证据", "法律研究"]


def _expand(spec: list[tuple[str, list[str]]]) -> list[str]:
    out: list[str] = []
    for top, subs in spec:
        out.append(top)
        out += [f"{top}/{s}" for s in subs]
    return out


TEMPLATES: dict[str, list[str]] = {
    "civil": _expand([
        ("01委托手续", []),
        ("02案件材料", []),
        ("03一审", _TRIAL6),
        ("04二审", _TRIAL6),
        ("05执行", ["执行申请", "财产线索", "法院文书"]),
        ("06法律研究", []),
    ]),
    "criminal": _expand([
        ("01委托手续", []),
        ("02案件材料", ["会见笔录", "家属沟通", "涉案证据"]),
        ("03侦查阶段", _INVEST5),
        ("04审查起诉阶段", _INVEST5),
        ("05一审", _TRIAL6),
        ("06二审", _TRIAL6),
        ("07申诉与再审", []),
        ("08执行（财产刑、民事赔偿）", []),
    ]),
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class CaseRegistry:
    def __init__(self, appdata: pathlib.Path, sql_path: pathlib.Path):
        self.path = pathlib.Path(appdata) / "cases.json"
        self.sql_path = pathlib.Path(sql_path)
        self._lock = threading.Lock()

    # ---------- cases.json ----------

    def _load(self) -> dict:
        if not self.path.exists():
            return {"v": 1, "cases": []}
        data = contracts.read_json(self.path)
        if data.get("v") != 1:
            raise ApiError("INTERNAL", "cases_unknown_v")  # 不认识的 v：只读、不写（Spec 20.1）
        contracts.validate(CASES_SCHEMA, "", data)
        return data

    def _save(self, data: dict) -> None:
        contracts.write_json(self.path, data, CASES_SCHEMA)

    def root_of(self, case_id: str) -> str:
        with self._lock:
            for c in self._load()["cases"]:
                if c["case_id"] == case_id:
                    return c["root"]
        raise ApiError("CASE_NOT_FOUND", "unknown_case_id")

    def find_by_root(self, cwd: str) -> tuple[str, str]:
        """会话头的 cwd → (case_id, 注册表里的 root)。cwd 不在注册表中一律 CASE_NOT_FOUND（Spec 4.3）。"""
        if not isinstance(cwd, str) or not cwd or "\x00" in cwd:
            raise ApiError("CASE_NOT_FOUND", "bad_cwd")
        try:
            real = os.path.normcase(os.path.realpath(gate.strip_long_prefix(cwd)))
        except (OSError, ValueError):
            raise ApiError("CASE_NOT_FOUND", "bad_cwd")
        with self._lock:
            for c in self._load()["cases"]:
                if os.path.normcase(c["root"]) == real:
                    return c["case_id"], c["root"]
        raise ApiError("CASE_NOT_FOUND", "cwd_not_registered")

    def recent(self) -> list[dict]:
        with self._lock:
            cases = list(self._load()["cases"])
        # 同一秒内打开的，按注册表里的先后（最近打开的排在最后）
        order = {id(c): i for i, c in enumerate(cases)}
        cases.sort(key=lambda c: (datetime.fromisoformat(c["last_opened"]), order[id(c)]), reverse=True)
        return [{"case_id": c["case_id"], "name": c["name"], "root": c["root"],
                 "last_opened": c["last_opened"], "exists": os.path.isdir(c["root"]), "kind": c.get("kind")} for c in cases]

    # ---------- 打开案件 ----------

    def open(self, path: str, template: str | None, folders: list[str] | None = None,
             kind: str | None = None) -> dict:
        """folders（契约 1.4）：律师勾选要建的子文件夹。给了就只建这些，必须都在 template 的标准目录表里
        （没给 template 或有不在表里的，整个请求拒绝、什么都不建）；不给按 template 全建。只补缺。"""
        wanted = None
        if folders is not None:
            if not template or any(f not in TEMPLATES[template] for f in folders):
                raise ApiError("INVALID_ARGUMENT", "folders_not_in_template")
            wanted = [rel for rel in TEMPLATES[template] if rel in set(folders)]     # 按标准目录表的顺序
        root = gate.check_root(path, appdata=self.path.parent)
        with self._lock:
            created = not os.path.isdir(os.path.join(root, gate.WORK))
            for rel in WORK_DIRS:
                gate.mkdir_work(root, rel, op="case_open")
            case_id = self._init_db(root)
            kind = self._kind(root, kind)
            folders_created: list[str] = []
            if template:
                for rel in (TEMPLATES[template] if wanted is None else wanted):
                    if gate.mkdir_original(root, rel, op="case_template"):
                        folders_created.append(rel)
            name = os.path.basename(root.rstrip("\\/")) or root
            data = self._load()
            # 同一 case_id 只保留一条：整个文件夹复制到别处后在新位置打开，注册表指向新位置（F-CASE-04）
            data["cases"] = [c for c in data["cases"]
                             if c["case_id"] != case_id and os.path.normcase(c["root"]) != os.path.normcase(root)]
            data["cases"].append({"case_id": case_id, "root": root, "name": name, "last_opened": now_iso(), "kind": kind})
            self._save(data)
        logs.event("case", "open", case_id=case_id)
        return {"case_id": case_id, "name": name, "created": created, "folders_created": folders_created, "kind": kind}

    @staticmethod
    def _kind(root: str, kind: str | None) -> str | None:
        """案件类型（契约 1.4 case_open.kind）：记在案件的 case.db meta 里，跟着案件文件夹走。
        这次带了就写上（覆盖原来的）；没带就读已有的，没有为 None（沿旧行为）。"""
        con = sqlite3.connect(gate.resolve_write(root, "工作区/case.db", op="case_db"))
        try:
            if kind is not None:
                with con:
                    con.execute("INSERT OR REPLACE INTO meta VALUES ('kind', ?)", (kind,))
                return kind
            row = con.execute("SELECT value FROM meta WHERE key='kind'").fetchone()
            return row[0] if row and row[0] in ("civil", "criminal", "daily") else None
        finally:
            con.close()

    def _init_db(self, root: str) -> str:
        db_path = gate.resolve_write(root, "工作区/case.db", op="case_db")
        existed = db_path.exists()
        con = sqlite3.connect(db_path)
        try:
            if existed:
                row = con.execute("SELECT value FROM meta WHERE key='case_id'").fetchone()
                ver = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                if row:
                    if not ver or ver[0] != SCHEMA_VERSION:
                        # 第一版只有版本 1，不做升级：版本对不上就拒绝打开，不改动这份 case.db
                        raise ApiError("INVALID_ARGUMENT", "case_db_version")
                    # 契约 1.2 补了 material_ids 表（schema_version 仍为 1）：已有的库也执行一次，全是 IF NOT EXISTS
                    # （T5 第二轮 A-P2-1）
                    con.executescript(self.sql_path.read_text(encoding="utf-8"))
                    return row[0]
            con.executescript(self.sql_path.read_text(encoding="utf-8"))
            case_id = str(uuid.uuid4())
            with con:
                con.execute("INSERT OR REPLACE INTO meta VALUES ('case_id', ?)", (case_id,))
                con.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
                con.execute("INSERT OR REPLACE INTO meta VALUES ('created_at', ?)", (now_iso(),))
            return case_id
        finally:
            con.close()
