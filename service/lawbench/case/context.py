"""首轮注入的上下文（Spec 9.2；契约 core/context）。

- L0 案件卡片：本方立场、当事人、争议焦点、关键事实、材料清单及状态；每条标可信度（✔律师确认 > 原文 > ⚠未确认）；
  标出 wiki 生成后新增或修改的材料。上限 6000 字。没有 wiki 时写"还没有生成 wiki"并列材料清单。
- L1 任务输入：任务单选用的前序成果，按窗口的 40%（按 token）装入；放不下的只列目录，AI 用 case_read_input 读。
"""
from __future__ import annotations

from .. import contracts
from ..errors import ApiError
from ..llm import tokens
from . import gate

L0_MAX_CHARS = 6000
CARD_REL = "工作区/wiki/case.json"
MARK = {"lawyer_confirmed": "✔律师确认", "excerpt": "原文", "unconfirmed": "⚠未确认"}
STATUS = {"parsed": "已解析", "needs_ocr": "有页待识别", "ocr_running": "识别中", "partial": "部分识别",
          "failed": "无法处理", "source_deleted": "原件已删除"}


def load_card(root: str) -> dict | None:
    p = gate.resolve_internal(root, CARD_REL, op="context")
    if not p.is_file():
        return None
    try:
        data = contracts.read_json(p)
        contracts.validate("files/case_card.schema.json", "", data)
    except (ValueError, contracts.ContractError):
        raise ApiError("CASE_CARD_INVALID", "case_card_invalid") from None   # 契约 1.4（复核 P3-1）：原来是 INTERNAL
    return data


def changed_since_card(card: dict | None, index: dict) -> set[str]:
    """wiki 生成后新增或变化的材料编号。"""
    if card is None:
        return set()
    seen = {m["material_id"]: m["sha256"] for m in card["materials_at_generation"]}
    return {m["material_id"] for m in index["materials"]
            if m["status"] != "source_deleted" and seen.get(m["material_id"]) != m["sha256"]}


def build_l0(root: str, index: dict) -> str:
    card = load_card(root)
    changed = changed_since_card(card, index)
    lines = ["# 案件卡片", ""]
    if card is None:
        lines += ["还没有生成 wiki。可以请律师先点\"生成案件 wiki\"；现在可用 case_search、case_read_material 直接查原文。", ""]
    else:
        stance = card["stance"]["text"] if card["stance"] else "（律师尚未填写）"
        lines += [f"本方立场：{stance}", ""]
        for title, key in (("当事人", "parties"), ("争议焦点", "issues"), ("关键事实", "key_facts")):
            lines.append(f"## {title}")
            for f in card[key]:
                cites = "".join(f["citations"])
                lines.append(f"- [{MARK[f['status']]}] {f['text']}{cites}")
            lines.append("")
    lines.append("## 材料清单")
    for m in index["materials"]:
        flag = "（wiki 生成后新增或修改）" if m["material_id"] in changed else ""
        lines.append(f"- {m['name']}（{STATUS.get(m['status'], m['status'])}）{flag}")
    text = "\n".join(lines).rstrip() + "\n"
    if len(text) > L0_MAX_CHARS:
        tail = "\n…（案件卡片过长，已截断；完整内容用 case_read_wiki 读）\n"
        text = text[:L0_MAX_CHARS - len(tail)] + tail
    return text


def build_l1(root: str, task: dict, read_input) -> dict:
    """read_input(root, ref) → 文本；选用后被改过的报 INPUT_CHANGED。"""
    budget = tokens.l1_budget(task["params"]["window"])
    blocks: list[tuple[dict, str, int]] = []
    for ref in task["inputs"]:
        text = read_input(root, ref)
        block = f"## 输入 {ref['index']}：{ref['title']}\n\n{text.rstrip()}\n"
        blocks.append((ref, block, tokens.count(block)))

    def assemble(k: int) -> tuple[str, list[dict]]:
        """前 k 份放全文，其后的只列目录（保持顺序）。"""
        toc = [{"index": ref["index"], "title": ref["title"], "tokens": n} for ref, _, n in blocks[k:]]
        parts = [b for _, b, _ in blocks[:k]]
        if toc:
            parts.append("以下输入没有放进来，需要时用 case_read_input 按序号分段读取：\n"
                         + "\n".join(f"- 输入 {t['index']}：{t['title']}（约 {t['tokens']} token）" for t in toc)
                         + "\n")
        return "\n".join(parts), toc

    k, used = 0, 0
    while k < len(blocks) and used + blocks[k][2] <= budget:
        used += blocks[k][2]
        k += 1
    text, toc = assemble(k)
    while k > 0 and tokens.count(text) > budget:  # 目录那几行也计入预算（P3-1）：放不下就再少放一份全文
        k -= 1
        text, toc = assemble(k)
    return {"text": text, "tokens": tokens.count(text) if text else 0, "truncated": bool(toc), "toc": toc}


def build(root: str, task: dict, index: dict, read_input) -> dict:
    if task["kind"] != "agent":
        raise ApiError("INVALID_ARGUMENT", "not_agent_task")
    l0 = build_l0(root, index)
    return {"l0": {"text": l0, "chars": len(l0)}, "l1": build_l1(root, task, read_input)}
