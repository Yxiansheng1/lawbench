"""案件 wiki 流水线（Spec 9.1；formats.md 第 4、6 节；参照 wiki 测试的 run_pipeline_v2.py）。

步骤：逐份材料写摘要（长材料按单元切段，每段约 8000 字；表格类材料由程序筛选，不经模型）→ 程序写材料清单 →
当事人、时间线、争议焦点、概览（每篇一次调用）→ 案件卡片 case.json（一次调用，编号由程序分配）→
程序写目录 index.md、日志 log.md → 全文核对（结果进 result.json）。

文件（与 case_read_wiki 的读法一致）：工作区/wiki/材料/<材料编号>.md、案件/<节名>.md、case.json、index.md、log.md。
跑完直接写进 工作区/wiki/（它是 L0 的来源）；各篇另存一份到任务的 草稿/ 作记录。

- 摘要步骤里模型的出处只写位置（〔第N页〕），程序补成〔材料名 第N页〕再核对（wiki 测试的写法，实测稳定）。
- 表格类材料（以 | 开头的行占 60% 以上，Excel 一律算）：按 Skill 目录的 `表格筛选.json` 列出部分行，其余计数；
  摘要页第二行写"> 筛选条件：…；已列出 X 行 / 共 Y 行"，材料清单里注明"摘要为筛选结果，非全量"。
- 律师修改块：`<!-- 律师修改 -->` 到 `<!-- /律师修改 -->` 之间的内容先取出，写新文件时放回原位置（按块前一行定位；
  紧挨着的几块算一组，整组放回，顺序不变）；原位置不在了放到文末，并加 `> **Status: 待律师核对**`。目录 index.md 也保护。
- 更新（wiki_update）：只重跑新增或变化材料的摘要页（与 case.json 的 materials_at_generation 比 sha256），
  没有摘要页或摘要页只有部分的也重跑；不在了的材料删掉摘要页；再重写四篇、卡片、清单、目录、日志。
- 中途停下（取消、到预算、出错，T16 返修 P2-4）：已有完整摘要页的不覆盖，半份存进任务的 草稿/；没有旧页的才写半份，
  页首注明"部分（k/n 段）"，材料清单那一行也写"部分（k/n 段）"。
- 旧 case.json 不合契约（律师手改坏了）：不覆盖，整次报错，免得静默丢掉本方立场和律师确认的条目（P3-7）。
- 开跑前先建好 材料/、案件/ 和任务的 草稿/（两路并行第一次建目录时，路径闸门偶发误判越界，P2-2）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

from ... import checks, contracts
from ...case import gate, texts
from ...checks.parse import citation_re, find_cites
from ...errors import ApiError
from ...tools.drafts import _WIKI_LOCK
from ..runner import Runner

WIKI = "工作区/wiki"
SECTIONS = ("当事人", "时间线", "争议焦点", "概览")
REQUIRED_STEPS = ("材料摘要", *SECTIONS, "案件卡片", "修改")
CHUNK_CHARS = 8000
TABLE_RATIO = 0.6
FILTER_FILE = "表格筛选.json"
DEFAULT_FILTER = {"amount_min": 10000, "cash_words": ["取现", "现金"], "persons_in_case": True, "unclear": True}
LAWYER_OPEN, LAWYER_CLOSE = "<!-- 律师修改 -->", "<!-- /律师修改 -->"
_LAWYER = re.compile(re.escape(LAWYER_OPEN) + r".*?" + re.escape(LAWYER_CLOSE), re.S)
_SHORT = re.compile(r"〔(第[^〔〕]*)〕")
PARTIAL_HEAD = "> 部分摘要："
RETRY_CARD = ("\n\n【注意】上一次输出过长被截断或不是合法 JSON。请精简：每条 text 不超过 60 字，每条最多 2 个出处，"
              "parties 不超过 20 条，issues 不超过 10 条，key_facts 不超过 15 条；只输出 JSON。")
ORG_WORDS = ("公司", "超市", "店", "站", "中心", "局", "行", "美团", "拼多多", "物业", "移动", "药房",
             "出行", "餐饮", "医院", "学校", "政府", "ATM", "银行", "支付宝", "财付通", "微信")


# ---------- 材料 ----------

@dataclass
class Mat:
    meta: dict
    units: list
    table: bool = False
    chunks: list = field(default_factory=list)       # [(第一处写法, 最后一处写法, 文本)]

    @property
    def name(self) -> str:
        return self.meta["name"]

    @property
    def mid(self) -> str:
        return self.meta["material_id"]


def load_materials(root: str, index: dict) -> tuple[list[Mat], list[tuple[dict, str]]]:
    """可写摘要的材料，以及跳过的材料和原因（进材料清单）。"""
    ok, skipped = [], []
    for m in index["materials"]:
        if m["status"] == "failed":
            skipped.append((m, m.get("error") or "无法处理"))      # 照抄导入时记下的原因（加密、识别超时……）
            continue
        try:
            units = texts.split_units(texts.read_text(root, m), m["unit"])
        except ApiError:
            skipped.append((m, "没有材料文本"))
            continue
        if not units or not texts.readable(units):
            skipped.append((m, "待识别"))
            continue
        mat = Mat(m, units)
        mat.table = is_table(mat)
        if not mat.table:
            mat.chunks = chunk(mat)
        ok.append(mat)
    return ok, skipped


def is_table(m: Mat) -> bool:
    if m.meta["unit"] == "cell":
        return True
    lines = [ln.strip() for u in m.units for ln in u.text.splitlines() if ln.strip()]
    return bool(lines) and sum(ln.startswith("|") for ln in lines) / len(lines) >= TABLE_RATIO


def _word(unit: str) -> str:
    return {"page": "页", "para": "段", "line": "行"}[unit]


def chunk(m: Mat, limit: int = CHUNK_CHARS) -> list[tuple[str, str, str]]:
    """按单元切段，每段不超过约 limit 字（单个单元超长时自成一段）。"""
    out, cur, size = [], [], 0
    for u in m.units:
        n = len(u.text) + 12
        if cur and size + n > limit:
            out.append(cur)
            cur, size = [], 0
        cur.append(u)
        size += n
    if cur:
        out.append(cur)
    w = _word(m.meta["unit"])
    return [(f"第{c[0].no}{w}", f"第{c[-1].no}{w}", _render(c, m.meta["unit"])) for c in out]


def _render(units: list, unit: str) -> str:
    if unit == "line":      # 行材料：每行都带标记，模型才能标准行号
        return "\n".join(f"【第{u.no}行】{u.text}" for u in units)
    return texts.render(units, unit)


def expand_short(text: str, name: str) -> str:
    """〔第3页〕〔第3页、第5页〕〔第1页至第3页〕→ 写全材料名。已写材料名、〔推断〕等不动。"""
    def repl(m):
        items = re.split(r"[、,，]\s*", m.group(1))
        out = []
        for it in items:
            it = re.sub(r"第(\d+)([页段行])?\s*[至~-]\s*第?(\d+)([页段行])", r"第\1-\3\4", it.strip())
            out.append(f"{name} {it}" if it.startswith("第") else it)
        return "〔" + "、".join(out) + "〕"
    return _SHORT.sub(repl, text)


# ---------- 表格类材料：程序筛选 ----------

def load_filter(skills_dirs, skill: str) -> dict:
    import pathlib
    for d in reversed(list(skills_dirs or ())):
        p = pathlib.Path(d) / skill / FILTER_FILE
        if p.is_file():
            try:
                return {**DEFAULT_FILTER, **json.loads(p.read_text(encoding="utf-8-sig"))}
            except ValueError:
                break
    return dict(DEFAULT_FILTER)


def _amount(x: str) -> float | None:
    try:
        return float(x.replace(",", "").replace("¥", "").strip())
    except ValueError:
        return None


def _is_person(name: str) -> bool:
    return bool(re.fullmatch(r"[一-鿿■]{2,4}", name)) and not any(w in name for w in ORG_WORDS)


def table_summary(m: Mat, case_text: str, rule: dict) -> tuple[list[str], int, int]:
    """(摘要行, 列出的行数, 总行数)。出处：页、段、行材料写所在单元；Excel 写整行区域（如 流水!A3:F3）。"""
    cell = m.meta["unit"] == "cell"
    w = None if cell else _word(m.meta["unit"])
    out, kept, total = [], 0, 0
    persons: dict[str, dict] = {}
    rest: dict[str, int] = {}
    rest_where: list[str] = []
    calls: dict[str, int] = {}
    call_where: list[str] = []
    header = None
    for u in m.units:
        lines = [u.text] if cell else u.text.splitlines()
        for ln in lines:
            t = ln.strip()
            if not t:
                continue
            if cell:
                cells = checks.parse.cell_values(t)
                where = f"{u.sheet}!A{u.row}:{checks.parse.col_letters(max(len(cells), 1))}{u.row}"
            else:
                if not t.startswith("|"):
                    if "：" in t and not t.startswith("（"):
                        out.append(f"- 【书证】{t}〔{m.name} 第{u.no}{w}〕")
                    continue
                cells = [c.strip() for c in t.strip("|").split("|")]
                where = f"第{u.no}{w}"
            if all(set(c) <= set("-: ") for c in cells):
                continue
            if any("日期" in c for c in cells):
                header = cells
                continue
            if not header or len(cells) != len(header):
                continue
            total += 1
            row = dict(zip(header, cells))
            if "对方号码" in row:
                calls[row["对方号码"]] = calls.get(row["对方号码"], 0) + 1
                if where not in call_where:
                    call_where.append(where)
                continue
            cp = row.get("对方户名", "")
            amt = max([a for a in (_amount(row.get("收入", "")), _amount(row.get("支出", ""))) if a] or [0])
            unclear = rule["unclear"] and ("■" in t or "[看不清]" in t)
            kind = row.get("摘要", "")
            known = rule["persons_in_case"] and _is_person(cp) and cp in case_text
            if unclear or known or amt >= rule["amount_min"] or kind in rule["cash_words"]:
                parts = [row.get("交易日期", ""), kind]
                if row.get("收入"):
                    parts.append(f"收入 {row['收入']}")
                if row.get("支出"):
                    parts.append(f"支出 {row['支出']}")
                parts.append(f"对方户名 {cp}")
                txt = " ".join(p for p in parts if p)
                cite = f"〔{m.name} {where}〕"
                out.append(f"- 【识别不清】{txt}（识别不清，需核对原件）{cite}" if unclear else f"- 【书证】{txt}{cite}")
                kept += 1
            elif _is_person(cp):
                d = persons.setdefault(cp, {"收入": 0, "支出": 0, "where": []})
                d["收入" if row.get("收入") else "支出"] += 1
                if where not in d["where"]:
                    d["where"].append(where)
            else:
                rest[kind or "其他"] = rest.get(kind or "其他", 0) + 1
                if where not in rest_where:
                    rest_where.append(where)

    def cite(places: list[str]) -> str:
        return "〔" + "、".join(f"{m.name} {p}" for p in _ranges(places)[:20]) + "〕"

    if calls:
        top = sorted(calls.items(), key=lambda x: -x[1])[:5]
        out.append(f"- 【书证】通话记录共 {sum(calls.values())} 条（程序统计），出现最多的号码："
                   + "、".join(f"{n}（{c} 次）" for n, c in top) + cite(call_where))
    for name, d in persons.items():
        out.append(f"- 【书证】与{name}的转账 {d['收入'] + d['支出']} 笔（收入 {d['收入']} 笔、支出 {d['支出']} 笔），"
                   f"{name}未在其他材料中出现，未逐笔列出（程序统计）{cite(d['where'])}")
    if rest:
        desc = "、".join(f"{k} {v} 笔" for k, v in rest.items())
        out.append(f"- 【书证】其余交易 {sum(rest.values())} 笔（{desc}），对方为商户或单位，未逐笔列出（程序统计）"
                   + cite(rest_where))
    return out, kept, total


def _ranges(places: list[str]) -> list[str]:
    """["第1页","第2页","第3页","第5页"] → ["第1-3页","第5页"]；单元格区域原样。"""
    nums = [re.fullmatch(r"第(\d+)([页段行])", p) for p in places]
    if not places or not all(nums):
        return places
    word = nums[0].group(2)
    ns = sorted({int(x.group(1)) for x in nums})
    out, a = [], ns[0]
    for prev, cur in zip(ns, ns[1:] + [None]):
        if cur != prev + 1 if cur is not None else True:
            out.append(f"第{a}{word}" if a == prev else f"第{a}-{prev}{word}")
            a = cur
    return out


def filter_note(rule: dict) -> str:
    conds = []
    if rule["persons_in_case"]:
        conds.append("对方为本案材料中出现的个人")
    conds.append(f"金额达到 {rule['amount_min']:,}")
    if rule["cash_words"]:
        conds.append("、".join(rule["cash_words"]))
    if rule["unclear"]:
        conds.append("含 ■ 或 [看不清] 的行")
    return "、".join(conds)


# ---------- 律师修改块 ----------

def take_lawyer_blocks(old: str) -> list[tuple[str | None, str]]:
    """[(块前一行非空文字, 块全文)]。中间只隔空白的几块算一组（P3-4），整组按第一块的位置放回。"""
    out: list[tuple[str | None, str]] = []
    end = None
    for m in _LAWYER.finditer(old):
        if out and end is not None and not old[end:m.start()].strip():
            anchor, block = out[-1]
            out[-1] = (anchor, block + old[end:m.start()] + m.group(0))
        else:
            before = [ln for ln in old[:m.start()].splitlines() if ln.strip()]
            out.append((before[-1].strip() if before else None, m.group(0)))
        end = m.end()
    return out


def put_lawyer_blocks(new: str, blocks: list[tuple[str | None, str]]) -> str:
    lines = new.splitlines()
    tail = []
    after: dict[int, list[str]] = {}
    for anchor, block in blocks:
        idx = next((i for i, ln in enumerate(lines) if anchor is not None and ln.strip() == anchor), None)
        if idx is None:
            tail.append(block)
        else:
            after.setdefault(idx, []).append(block)      # 同一位置的几组按原来的先后放
    out = []
    for i, ln in enumerate(lines):
        out.append(ln)
        for block in after.get(i, []):
            out += block.splitlines()
    text = "\n".join(out)
    if tail:
        text = text.rstrip("\n") + "\n\n> **Status: 待律师核对**\n\n" + "\n\n".join(tail)
    return text


# ---------- 运行 ----------

class WikiRun:
    def __init__(self, *, root: str, case_id: str, index: dict, runner: Runner, step: str, rule: dict,
                 task_id: str, tasks):
        self.root = root
        self.case_id = case_id
        self.index = index
        self.r = runner
        self.step = step
        self.rule = rule
        self.task_id = task_id
        self.tasks = tasks
        self.today = datetime.now().astimezone().date().isoformat()
        self.written: list[tuple[str, str]] = []     # (节名, 相对路径) 本次写进 wiki 的文章
        self.drafts: list[dict] = []
        self.prep = None                              # 律师勾选"使用 395 抽取"时由 pipeline.prep.attach 挂上
        self.prep_refs: dict[str, list[tuple[int, str]]] = {}
        self.prep_cats: dict[str, str] = {}

    # ---- 文件 ----

    def _read(self, rel: str) -> str | None:
        p = gate.resolve_internal(self.root, rel, op="pipeline")
        return p.read_text(encoding="utf-8") if p.is_file() else None

    def _write(self, rel: str, text: str) -> None:
        old = self._read(rel)
        if old:
            blocks = take_lawyer_blocks(old)
            if blocks:
                text = put_lawyer_blocks(text, blocks)
        gate.write_bytes(self.root, rel, text.encode("utf-8"), op="pipeline")

    def _draft(self, title: str, text: str) -> None:
        rel = self.tasks.rel(self.task_id, f"草稿/{title}-v1.md")
        gate.write_bytes(self.root, rel, text.encode("utf-8"), op="pipeline")
        self.drafts.append({"title": title, "path": rel, "version": 1})

    def old_card(self) -> dict | None:
        raw = self._read(f"{WIKI}/case.json")
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            contracts.validate("files/case_card.schema.json", "", data)
            return data
        except (ValueError, contracts.ContractError):
            raise ApiError("INVALID_ARGUMENT", "case_card_invalid") from None

    # ---- 主流程 ----

    def run(self) -> None:
        mats, skipped = load_materials(self.root, self.index)
        card = self.old_card()
        for rel in (f"{WIKI}/材料", f"{WIKI}/案件", self.tasks.rel(self.task_id, "草稿")):
            gate.mkdir_work(self.root, rel, op="pipeline")
        before = {x["material_id"]: x["sha256"] for x in (card or {}).get("materials_at_generation", [])}
        if self.step == "wiki_update" and card is not None:
            redo = [m for m in mats if before.get(m.mid) != m.meta["sha256"] or not self._complete_page(m)]
        else:
            redo = list(mats)
        keep = [m for m in mats if m not in redo]
        p = self.r.progress
        p.step_total = sum(len(m.chunks) or 1 for m in redo) + len(SECTIONS) + 3
        case_text = "\n".join(u.text for m in mats if not m.table for u in m.units)

        # 1 摘要
        summaries: dict[str, str] = {}
        partial: dict[str, str] = {}
        for m in keep:
            summaries[m.mid] = self._existing_summary(m)
        if self.prep is not None:
            p.current = "395 抽取"
            self.prep_refs, self.prep_cats = self.prep.run([m for m in redo if not m.table])
        items = [(m, i, c) for m in redo if not m.table for i, c in enumerate(m.chunks)]
        for m in redo:
            if m.table:
                lines, kept, total = table_summary(m, case_text, self.rule)
                note = f"> 筛选条件：{filter_note(self.rule)}；已列出 {kept} 行 / 共 {total} 行"
                summaries[m.mid] = "\n".join(lines)
                self._write_material(m, summaries[m.mid], note)
                p.step_index += 1
        try:
            results = self.r.map(lambda it: self._summary_chunk(*it), items)
            stop = None
        except Exception as e:  # noqa: BLE001 取消、到预算：先把已写完的摘要页存下来再抛出
            results, stop = getattr(e, "partial", None), e
            if results is None:
                raise
        kept_old: set[str] = set()
        for m in redo:
            if m.table:
                continue
            parts = [res for (mm, _, _), res in zip(items, results) if mm is m and res is not None]
            if len(parts) == len(m.chunks):
                summaries[m.mid] = "\n".join(parts)
                self._write_material(m, summaries[m.mid], None)
                continue
            k_n = f"部分（{len(parts)}/{len(m.chunks)} 段）"
            if self._complete_page(m):
                # 停下时不覆盖已有的完整页（主编排定，P2-4）：半份存任务草稿，清单仍按旧页算已读
                if parts:      # 标题进文件名，不能带"/"
                    self._draft(f"材料摘要 {m.mid} 部分（{len(parts)} 段，共 {len(m.chunks)} 段）", "\n".join(parts))
                summaries[m.mid] = self._existing_summary(m)
                kept_old.add(m.mid)
            elif parts:
                summaries[m.mid] = "\n".join(parts)
                partial[m.mid] = k_n
                self._write_material(m, summaries[m.mid], f"{PARTIAL_HEAD}{k_n}，运行中止，没有读完")
        if stop is not None:
            self._inventory(mats, skipped, summaries, partial, kept_old, stopped=True)
            raise stop
        removed = [mid for mid in before if mid not in {m.mid for m in mats}]
        for mid in removed:
            gate.delete_work_file(self.root, f"{WIKI}/材料/{mid}.md", op="pipeline")

        # 2 材料清单（程序）
        inventory = self._inventory(mats, skipped, summaries, partial, kept_old)
        p.step_index += 1

        # 3 四篇
        digest = "\n\n".join(f"# {m.name}\n{summaries[m.mid]}" for m in mats if m.mid in summaries)
        user = f"{inventory}\n\n【各材料摘要页】\n\n{digest}"
        texts_ = dict(zip(SECTIONS, self.r.map(lambda s: self._article(s, user), list(SECTIONS))))

        # 4 案件卡片
        p.current = None
        self._card(texts_, mats)
        p.step_index += 1

        # 5 目录、日志
        self._index_and_log(mats, summaries, inventory)
        p.step_index += 1

    def _complete_page(self, m: Mat) -> bool:
        text = self._read(f"{WIKI}/材料/{m.mid}.md")
        return text is not None and PARTIAL_HEAD not in "\n".join(text.splitlines()[:3])

    def _existing_summary(self, m: Mat) -> str:
        text = self._read(f"{WIKI}/材料/{m.mid}.md") or ""
        body = text.split("## 摘要", 1)[1] if "## 摘要" in text else text
        return _LAWYER.sub("", body).strip()

    def _summary_chunk(self, m: Mat, i: int, c: tuple[str, str, str]) -> str:
        first, last, src = c
        p = self.r.progress
        p.current = m.name
        total = len(m.units)
        header = (f"材料名：{m.name}\n本次给你的是 {first} 至 {last}（全份共 {total} {_word(m.meta['unit'])}）"
                  + ("\n注意：本材料含识别所得的页，■ 和 [看不清] 表示识别不清。" if m.meta.get("is_ocr") not in (None, "none")
                     else ""))
        lo, hi = int(re.sub(r"\D", "", first)), int(re.sub(r"\D", "", last))
        refs = [s for no, s in self.prep_refs.get(m.mid, []) if lo <= no <= hi]
        if refs:
            header += (f"\n395 分类：{self.prep_cats.get(m.mid, '未分类')}"
                       "\n【395 抽取的参考字段（已按原文核对，可以直接用，但仍要带出处）】\n" + "\n".join(refs))
        res = self.r.write_checked("材料摘要", header + "\n\n" + src, f"{m.mid}#{i + 1}",
                                   expand=lambda t: expand_short(t, m.name), sources=header + "\n\n" + src)
        p.step_index += 1
        return res.text

    def _write_material(self, m: Mat, body: str, note: str | None) -> None:
        head = f"# {m.name}\n" + (note + "\n" if note else "")
        self._write(f"{WIKI}/材料/{m.mid}.md", head + "\n## 摘要\n\n" + body.strip() + "\n")

    def _inventory(self, mats, skipped, summaries, partial, kept_old=(), stopped=False) -> str:
        rows, n_read = [], 0
        for m in mats:
            if m.mid not in summaries:
                why = "运行中止，未生成" if stopped else "摘要生成失败"
                rows.append(f"| {m.name} | {m.meta['type']} | {m.meta['unit_count']} | **否** | {why} |")
                continue
            if m.mid in partial:
                rows.append(f"| {m.name} | {m.meta['type']} | {m.meta['unit_count']} | {partial[m.mid]} | |")
                continue
            n_read += 1
            note = "；".join(x for x in ("摘要为筛选结果，非全量" if m.table else "",
                                         "原件已删除（保留材料文本）" if m.meta["status"] == "source_deleted" else "",
                                         "本次运行中止，保留上次的摘要页" if m.mid in kept_old else "") if x)
            rows.append(f"| {m.name} | {m.meta['type']} | {m.meta['unit_count']} | 是 | {note} |")
        for meta, why in skipped:
            rows.append(f"| {meta['name']} | {meta['type']} | {meta.get('unit_count') or '—'} | **否** | {why} |")
        total = len(mats) + len(skipped)
        coverage = f"共 {total} 份材料，已读 {n_read} 份，未读 {total - n_read} 份。"
        body = ("| 材料 | 类型 | 数量 | 已读 | 备注 |\n|---|---|---|---|---|\n" + "\n".join(rows)
                + f"\n\n**覆盖**：{coverage}\n")
        self._write(f"{WIKI}/案件/材料清单.md", "# 材料清单\n\n" + body)
        unread = [r for r in rows if "**否**" in r or "部分" in r]
        return "【材料清单】\n" + coverage + "\n未读或未读完：\n" + ("\n".join(unread) or "（无）")

    def _article(self, section: str, user: str) -> str:
        self.r.progress.current = section
        res = self.r.write_checked(section, user, section)
        text = f"# {section}\n\n{res.text.strip()}\n"
        rel = f"{WIKI}/案件/{section}.md"
        self._write(rel, text)
        self._draft(section, self._read(rel) or text)
        self.written.append((section, rel))
        self.r.progress.step_index += 1
        return res.text

    def _card(self, sections: dict[str, str], mats: list[Mat]) -> None:
        user = "\n\n".join(f"# {s}\n{sections[s]}" for s in SECTIONS)
        raw, finish = self.r.call_reply(self.r.prompts.system("案件卡片"), user, "案件卡片", "案件卡片")
        data = _json_object(raw) if finish != "length" else {}
        if not data:
            # 输出被截断或不是 JSON：提示精简后重试一次（大卷宗实测：一次输出到 8192 上限被截断）
            raw, finish = self.r.call_reply(self.r.prompts.system("案件卡片"), user + RETRY_CARD, "案件卡片", "案件卡片重试")
            data = _json_object(raw) if finish != "length" else {}
        if not data:
            # 还是不行：不写空卡片、不覆盖原来的卡片，整次运行记为失败（OUTPUT_TRUNCATED）
            raise ApiError("OUTPUT_TRUNCATED", "case_card")
        pat = citation_re()
        old = self.old_card()
        n = 0

        def facts(key: str) -> list[dict]:
            nonlocal n
            out = []
            kept = [f for f in (old or {}).get(key, []) if f["status"] == "lawyer_confirmed"]
            for f in kept:
                n += 1
                out.append(dict(f, id=f"F{n:04d}"))
            for item in (data.get(key) or [])[:40]:
                if not isinstance(item, dict) or not str(item.get("text", "")).strip():
                    continue
                text = str(item["text"]).strip()
                given = [c for c in item.get("citations") or [] if isinstance(c, str)]
                cites = [c for c in given if pat.match(c) and self._cite_ok(c, text)]
                n += 1
                excerpt = item.get("status") == "excerpt" and (cites or not given)
                out.append({"id": f"F{n:04d}", "text": text, "citations": cites,
                            "status": "excerpt" if excerpt else "unconfirmed"})
            return out

        card = {"v": 1, "case_id": self.case_id,
                "case_type": data.get("case_type") if data.get("case_type") in ("criminal", "civil", "contract", "other")
                else "other",
                "stance": (old or {}).get("stance"),
                "parties": facts("parties"), "issues": facts("issues"), "key_facts": facts("key_facts")[:15 + len(
                    [f for f in (old or {}).get("key_facts", []) if f["status"] == "lawyer_confirmed"])],
                "generated_by": self.task_id, "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "materials_at_generation": [{"material_id": m.mid, "sha256": m.meta["sha256"]} for m in mats]}
        contracts.validate("files/case_card.schema.json", "", card)
        payload = json.dumps(card, ensure_ascii=False, indent=2)
        gate.write_bytes(self.root, f"{WIKI}/case.json", payload.encode("utf-8"), op="pipeline")
        self._draft("案件卡片", payload)

    def _cite_ok(self, cite: str, text: str) -> bool:
        """卡片里的一处出处：和条目文字一起核，没有 A–E 类必须修改的问题才留下（大卷宗实测：卡片曾把识别不清的
        "8■,000.00"所在页当成"80,000元"的出处）。丢掉出处的条目状态改为 unconfirmed。"""
        check, _ = checks.check_text(text + cite, self.r.materials, "excerpt")
        return not any(p["class"] in "ABCDE" and p["severity"] == "must_fix" for p in check["problems"])

    def _index_and_log(self, mats, summaries, inventory) -> None:
        idx = ["# 案件 wiki 目录", "", "## 案件", "", "| 文章 | 更新日期 |", "|---|---|"]
        idx += [f"| {t} | {self.today} |" for t in ("概览", "当事人", "时间线", "材料清单", "争议焦点")]
        idx += ["", "## 材料", "", "| 摘要页 | 更新日期 |", "|---|---|"]
        idx += [f"| {m.name} | {self.today} |" for m in mats if m.mid in summaries]
        self._write(f"{WIKI}/index.md", "\n".join(idx) + "\n")          # 律师修改块同样保护
        what = "更新" if self.step == "wiki_update" else "生成"
        cov = inventory.splitlines()[1] if len(inventory.splitlines()) > 1 else ""
        entry = (f"\n## [{self.today}] {what} | 流水线 {self.task_id}\n- 材料：{len(summaries)} 份有摘要页\n"
                 f"- 覆盖：{cov}\n- 改动文章：概览、当事人、时间线、材料清单、争议焦点、案件卡片\n")
        if self.prep is not None:
            entry += f"- 395 抽取：{self.prep.note or '已用，核对通过的字段作为摘要的参考输入'}\n"
        with _WIKI_LOCK:                             # 与"采纳修改建议"写日志用同一把锁
            old = self._read(f"{WIKI}/log.md") or "# Wiki Log\n"
            gate.write_bytes(self.root, f"{WIKI}/log.md", (old.rstrip("\n") + "\n" + entry).encode("utf-8"),
                             op="pipeline")

    # ---- 全文核对 ----

    def final_check(self) -> tuple[dict, list[dict]]:
        """wiki 全部文章与摘要页一起核对（excerpt）。返回合并的 citation_check 与结构化出处。"""
        rels = [f"{WIKI}/案件/{s}.md" for s in SECTIONS]
        rels += [f"{WIKI}/材料/{m['material_id']}.md" for m in self.index["materials"]]
        problems, cites, n = [], {}, 0
        for rel in rels:
            text = self._read(rel)
            if not text:
                continue
            check, cs = checks.check_text(text, self.r.materials, "excerpt")
            problems += check["problems"]
            n += check["stats"]["citations"]
            for c in cs:
                cites.setdefault((c["material_id"], json.dumps(c["loc"], sort_keys=True)), c)
        must = sum(p["severity"] == "must_fix" for p in problems)
        return ({"passed": must == 0, "problems": problems[:500],
                 "stats": {"citations": n, "must_fix": must, "hints": len(problems) - must}}, list(cites.values()))


def _json_object(raw: str) -> dict:
    s = raw.strip()
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b <= a:
        return {}
    try:
        data = json.loads(s[a:b + 1])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


__all__ = ["WikiRun", "REQUIRED_STEPS", "load_filter", "expand_short", "table_summary", "take_lawyer_blocks",
           "put_lawyer_blocks", "find_cites"]
