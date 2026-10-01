"""/api/wiki/suggestions（Spec 4.3、20.8）：列出、处理 AI 提出的 wiki 修改建议（工作区/wiki/待确认.json）。

- GET（只带 case_id）：返回全部建议。
- POST /api/wiki/suggestions/{id}，带 accept：把这条从 pending 改成 accepted / rejected，返回全部建议。
  已处理过的再处理报 INVALID_ARGUMENT；编号不存在报 INVALID_ARGUMENT。
- 采纳后怎么改 wiki：Spec 写"律师在界面上确认后才改 wiki"，建议的 field 是自由文本、没有约定落到哪一节，
  本卡只记采纳状态、写进 wiki 日志，由下一次 wiki 更新或律师在界面上改（交主编排定）。
读改写与 case_suggest_wiki 共用一把锁（tools/drafts._WIKI_LOCK）。
"""
from __future__ import annotations

import json
from datetime import datetime

from .. import contracts
from ..case import gate
from ..errors import ApiError
from ..tools.drafts import _WIKI_LOCK, PENDING_REL, PENDING_SCHEMA

LOG_REL = "工作区/wiki/log.md"


def _load(root: str) -> dict:
    p = gate.resolve_internal(root, PENDING_REL, op="wiki_suggestions")
    data = contracts.read_json(p) if p.is_file() else {"v": 1, "suggestions": []}
    contracts.validate(PENDING_SCHEMA, "", data)
    return data


def handle(root: str, sid: str | None, accept: bool | None) -> dict:
    with _WIKI_LOCK:
        data = _load(root)
        if sid is None:
            return {"suggestions": data["suggestions"]}
        if accept is None:
            raise ApiError("INVALID_ARGUMENT", "accept_required")
        s = next((x for x in data["suggestions"] if x["id"] == sid), None)
        if s is None:
            raise ApiError("INVALID_ARGUMENT", "suggestion_not_found")
        if s["status"] != "pending":
            raise ApiError("INVALID_ARGUMENT", "suggestion_done")
        s["status"] = "accepted" if accept else "rejected"
        contracts.validate(PENDING_SCHEMA, "", data)
        gate.write_bytes(root, PENDING_REL, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
                         op="wiki_suggestions")
        if accept:
            _log(root, s)
        return {"suggestions": data["suggestions"]}


def _log(root: str, s: dict) -> None:
    p = gate.resolve_internal(root, LOG_REL, op="wiki_suggestions")
    old = p.read_text(encoding="utf-8") if p.is_file() else "# Wiki Log\n"
    day = datetime.now().astimezone().date().isoformat()
    entry = f"\n## [{day}] 律师采纳修改建议 {s['id']}\n- {s['field']}：{s['value']} {s['source']}\n"
    gate.write_bytes(root, LOG_REL, (old.rstrip("\n") + "\n" + entry).encode("utf-8"), op="wiki_suggestions")
