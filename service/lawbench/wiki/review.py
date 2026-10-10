"""案件 wiki 的核对状态（契约 1.4：api/wiki_review、files/case_card 的 review）。

律师点"核对完成"时，把"这一版 wiki + 此刻材料"的指纹记进 工作区/wiki/case.json 的 review；
读的时候现算指纹，和记下的一样才算"已核对"。重新生成、更新 wiki（生成时间变）或材料有增减、内容变化（哈希变）后
指纹不同，状态自动回到未核对。记在案件里，换电脑打开同一个案件文件夹也一致。

指纹 = sha256(wiki 生成时间 + 按编号排序的 [材料编号, 原件哈希])；材料只算还在的（原件已删除、已移除的不算）。
读改写与 wiki 的其他写入共用一把锁（tools/drafts._WIKI_LOCK）。日志只记案件编号。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from .. import contracts, logs
from ..case import gate
from ..case.context import CARD_REL
from ..errors import ApiError
from ..tools.drafts import _WIKI_LOCK

GONE = ("source_deleted", "removed")


def _card(root: str) -> dict | None:
    p = gate.resolve_internal(root, CARD_REL, op="wiki_review")
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        contracts.validate("files/case_card.schema.json", "", data)
    except (ValueError, contracts.ContractError):
        raise ApiError("CASE_CARD_INVALID", "case_card_invalid") from None
    return data


def _now(index: dict) -> dict[str, str]:
    return {m["material_id"]: m["sha256"] for m in index["materials"] if m["status"] not in GONE}


def signature(card: dict, index: dict) -> str:
    body = json.dumps([card["generated_at"], sorted(_now(index).items())], ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _view(card: dict | None, index: dict) -> dict:
    if card is None or card["generated_at"] is None:
        return {"exists": False, "reviewed": False, "reviewed_at": None, "changes": None}
    then = {x["material_id"]: x["sha256"] for x in card["materials_at_generation"]}
    now = _now(index)
    changes = {"added": sum(1 for k in now if k not in then),
               "changed": sum(1 for k in now if k in then and then[k] != now[k]),
               "removed": sum(1 for k in then if k not in now)}
    rev = card.get("review")
    ok = bool(rev) and rev["signature"] == signature(card, index)
    return {"exists": True, "reviewed": ok, "reviewed_at": rev["at"] if ok else None, "changes": changes}


def get(root: str, index: dict) -> dict:
    return _view(_card(root), index)


def mark(root: str, case_id: str, index: dict) -> dict:
    """把当前这一版记为已核对。还没生成过 wiki 的不能核对。"""
    with _WIKI_LOCK:
        card = _card(root)
        if card is None or card["generated_at"] is None:
            raise ApiError("INVALID_ARGUMENT", "no_wiki", detail="还没有生成案件 wiki，不能标记核对完成")
        card["review"] = {"signature": signature(card, index),
                          "at": datetime.now().astimezone().isoformat(timespec="seconds")}
        contracts.validate("files/case_card.schema.json", "", card)
        gate.write_bytes(root, CARD_REL, json.dumps(card, ensure_ascii=False, indent=2).encode("utf-8"), op="wiki_review")
    logs.event("wiki", "review", case_id=case_id)
    return _view(card, index)
