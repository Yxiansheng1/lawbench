"""全文检索（Spec 第 11 节；契约 case_db.sql 的 search_units、search_fts，tools/case_search、api/search）。

索引
- 索引单位：一页、一段、一个工作表的每 20 行、文本文件的每 50 行（与材料文本的【第N行】分块一致）。
  每条记下材料编号、原件版本（sha256）、位置范围、原文、归一化文本；search_fts 是 search_units 的 trigram 外部内容表。
- 建索引的时机：扫描、导入结束时建（materials._scan 末尾调用 refresh_after_scan，裁决 1548 第 1 条）；
  每次检索前再按需核对补一次作兜底——
  材料的原件 sha256、材料文本的修改时间和大小，与本进程记下的对不上，就只重建这一份；材料不在了删掉它的单元。
  本进程第一次检索某个案件时整案重建一次（case.db 里没有记"材料文本版本"的地方，加字段是改契约）。
- 失败的材料（没有材料文本）不进索引。

查询
- 查询词先归一化，再按 expand.variants 扩展（日期、金额的几种写法）。
- 3 个字及以上：FTS5 trigram 短语查询找候选单元；1–2 个字：在 text_norm 上 instr 逐条扫描（保证不会静默搜不到）。
- 在候选单元的归一化文本里找出每一处命中，换算成精确位置：行（块内第几行）、单元格（工作表!列行）、页、段。
- 完全匹配要求命中处的原文与查询逐字是同一种写法（只做全角转半角、统一空白、不分大小写）；归一化后才相同的
  （80,000 与 80000）算扩展匹配（G-9 验证集的 found_as 条目就是这样定义的）。
- 同一位置只留一条：完全匹配优先于扩展匹配。排序：完全匹配 > 扩展匹配，再按材料顺序、位置顺序。
- 片段取原文里命中处前后各 40 字（归一化时记下了每个字在原文里的位置）。
- 检索词不进日志：只记案件编号、耗时、命中数。
"""
from __future__ import annotations

import sqlite3
import threading
import time
import unicodedata

from .. import logs
from ..case import gate, texts
from ..errors import ApiError
from . import expand
from .normalize import normalize_with_map

SNIPPET = 40
LINES_PER_UNIT = 50
ROWS_PER_UNIT = 20
UNIT_WORD = {"page": "页", "para": "段", "line": "行"}

_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}
# 本进程记下的索引状态：root → {material_id: (sha256, 文本修改时间, 文本大小)}
_state: dict[str, dict[str, tuple]] = {}


def _lock(root: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(root, threading.Lock())


def _col_letter(i: int) -> str:
    out = ""
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


# ---------- 索引单位 ----------

def units_of(root: str, m: dict) -> list[dict]:
    """把一份材料的材料文本切成索引单位。"""
    units = texts.split_units(texts.read_text(root, m), m["unit"])
    out: list[dict] = []
    if m["unit"] in ("page", "para"):
        for u in units:
            out.append({"unit": m["unit"], "from": u.no, "to": u.no, "sheet": None, "is_ocr": u.is_ocr,
                        "text": u.text})
    elif m["unit"] == "line":
        block: list = []
        for u in units:
            if block and (u.no - 1) // LINES_PER_UNIT != (block[0].no - 1) // LINES_PER_UNIT:
                out.append(_line_block(block))
                block = []
            block.append(u)
        if block:
            out.append(_line_block(block))
    else:  # cell：每个工作表每 20 行一条；位置记工作表内的行号
        block = []
        for u in units:
            if block and (u.sheet != block[0].sheet or len(block) >= ROWS_PER_UNIT):
                out.append(_cell_block(block))
                block = []
            block.append(u)
        if block:
            out.append(_cell_block(block))
    return out


def _line_block(block) -> dict:
    return {"unit": "line", "from": block[0].no, "to": block[-1].no, "sheet": None, "is_ocr": False,
            "text": "\n".join(u.text for u in block)}


def _cell_block(block) -> dict:
    return {"unit": "cell", "from": block[0].row, "to": block[-1].row, "sheet": block[0].sheet, "is_ocr": False,
            "text": "\n".join(u.text for u in block)}


# ---------- 建索引 ----------

def _connect(root: str) -> sqlite3.Connection:
    db = gate.resolve_internal(root, "工作区/case.db", op="search")
    if not db.is_file():
        raise ApiError("CASE_NOT_FOUND", "case_db_missing")
    con = sqlite3.connect(str(db), timeout=10)
    has = con.execute("SELECT 1 FROM sqlite_master WHERE name = 'search_fts'").fetchone()
    if not has:
        con.close()
        raise ApiError("INTERNAL", "search_tables_missing")
    return con


def _text_stamp(root: str, m: dict) -> tuple | None:
    try:
        p = gate.resolve_internal(root, texts.text_rel(m), op="search")
        st = p.stat()
    except (ApiError, OSError):
        return None
    return (m["sha256"], st.st_mtime_ns, st.st_size)


def _delete_material(con: sqlite3.Connection, mid: str) -> None:
    rows = con.execute("SELECT rowid, text_norm FROM search_units WHERE material_id = ?", (mid,)).fetchall()
    for rowid, norm in rows:
        con.execute("INSERT INTO search_fts(search_fts, rowid, text_norm) VALUES ('delete', ?, ?)", (rowid, norm))
    con.execute("DELETE FROM search_units WHERE material_id = ?", (mid,))


def _add_material(con: sqlite3.Connection, root: str, m: dict) -> None:
    for u in units_of(root, m):
        norm = normalize_with_map(u["text"])[0]
        cur = con.execute(
            "INSERT INTO search_units (material_id, material_version, unit, loc_from, loc_to, sheet, is_ocr, text, "
            "text_norm) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (m["material_id"], m["sha256"], u["unit"], u["from"], u["to"], u["sheet"], int(u["is_ocr"]), u["text"],
             norm))
        con.execute("INSERT INTO search_fts(rowid, text_norm) VALUES (?, ?)", (cur.lastrowid, norm))


def refresh(root: str, index: dict, con: sqlite3.Connection) -> int:
    """让检索表跟上材料文本。返回重建了几份材料。调用方持该案件的锁。"""
    state = _state.get(root)
    wanted: dict[str, tuple] = {}
    by_id: dict[str, dict] = {}
    for m in index["materials"]:
        if m["status"] == "failed":
            continue
        stamp = _text_stamp(root, m)
        if stamp is not None:
            wanted[m["material_id"]] = stamp
            by_id[m["material_id"]] = m
    n = 0
    with con:
        if state is None:  # 本进程第一次：整案重建
            con.execute("INSERT INTO search_fts(search_fts) VALUES ('delete-all')")
            con.execute("DELETE FROM search_units")
            state = {}
            for mid in wanted:
                _add_material(con, root, by_id[mid])
                state[mid] = wanted[mid]
                n += 1
        else:
            for mid in list(state):
                if mid not in wanted:
                    _delete_material(con, mid)
                    del state[mid]
            for mid, stamp in wanted.items():
                if state.get(mid) != stamp:
                    _delete_material(con, mid)
                    _add_material(con, root, by_id[mid])
                    state[mid] = stamp
                    n += 1
    _state[root] = state
    return n


def refresh_after_scan(root: str, case_id: str, index: dict) -> None:
    """扫描、导入之后建索引（T9 三处裁决第 1 条：台账"导入时写"）。任何异常都兜住、只记元数据日志，
    不让扫描失败；检索前的按需核对重建仍保留作兜底。"""
    t0 = time.monotonic()
    try:
        with _lock(root):
            con = _connect(root)
            try:
                refresh(root, index, con)
            finally:
                con.close()
    except Exception as e:  # noqa: BLE001
        logs.event("search", "index", status="fail", case_id=case_id, error=type(e).__name__)
        return
    logs.event("search", "index", case_id=case_id, duration_ms=(time.monotonic() - t0) * 1000)


# ---------- 查询 ----------

def _fts_phrase(q: str) -> str:
    return '"' + q.replace('"', '""') + '"'


def _candidates(con: sqlite3.Connection, q: str) -> list[tuple]:
    cols = "u.rowid, u.material_id, u.unit, u.loc_from, u.loc_to, u.sheet, u.is_ocr, u.text"
    if len(q) >= 3:
        return con.execute(f"SELECT {cols} FROM search_fts f JOIN search_units u ON u.rowid = f.rowid "
                           "WHERE search_fts MATCH ?", (_fts_phrase(q),)).fetchall()
    return con.execute(f"SELECT {cols} FROM search_units u WHERE instr(lower(u.text_norm), ?) > 0",
                       (q.lower(),)).fetchall()


def _positions(norm: str, q: str, bounded: bool) -> list[int]:
    """q 在 norm 里的每一处（英文字母不分大小写，与 trigram 一致）。"""
    low, ql = norm.lower(), q.lower()
    if len(low) == len(norm) and len(ql) == len(q):
        norm, q = low, ql
    out = []
    start = 0
    while True:
        k = norm.find(q, start)
        if k < 0:
            return out
        start = k + 1
        if bounded:
            before = norm[k - 1] if k else ""
            after = norm[k + len(q)] if k + len(q) < len(norm) else ""
            if (q[0].isdigit() and (before.isdigit() or before == ".")) or (q[-1].isdigit() and after.isdigit()):
                continue
        out.append(k)


def _locate(row: tuple, name: str, text: str, where: list[int], k: int) -> tuple[str, tuple]:
    """命中在单元文本里的位置 → (出处文本, 排序键)。"""
    _, _, unit, loc_from, _, sheet, _, _ = row
    orig = where[k]
    if unit in ("page", "para"):
        return f"〔{name} 第{loc_from}{UNIT_WORD[unit]}〕", (loc_from, 0)
    line_idx = text.count("\n", 0, orig)
    if unit == "line":
        no = loc_from + line_idx
        return f"〔{name} 第{no}行〕", (no, 0)
    line = text.split("\n")[line_idx]
    line_start = sum(len(x) + 1 for x in text.split("\n")[:line_idx])
    pos = orig - line_start
    cells = line.split("|")
    # "| 行号 | A | B |" → cells[0] 为空，cells[1] 是行号，cells[2] 起是 A、B……
    acc = 0
    col = 1
    for ci, c in enumerate(cells):
        if acc <= pos < acc + len(c) + 1:
            col = max(1, ci - 1)
            break
        acc += len(c) + 1
    row_no = int(cells[1].strip()) if len(cells) > 1 and cells[1].strip().isdigit() else loc_from
    return f"〔{name} {sheet}!{_col_letter(col)}{row_no}〕", (row_no, col)


def _literal(s: str) -> str:
    """只做全角转半角、统一空白、不分大小写（不去千分位逗号）：判断命中处的原文与查询是不是逐字同一种写法。"""
    return " ".join(unicodedata.normalize("NFKC", s).split()).lower()


def search(root: str, case_id: str, index: dict, query: str, max_hits: int = 20) -> dict:
    t0 = time.monotonic()
    vs = expand.variants(query)
    if not vs[0][0]:
        raise ApiError("INVALID_ARGUMENT", "empty_query")
    order = {m["material_id"]: i for i, m in enumerate(index["materials"])}
    names = {m["material_id"]: m["name"] for m in index["materials"]}
    found: dict[tuple, dict] = {}
    with _lock(root):
        con = _connect(root)
        try:
            refresh(root, index, con)
            literal_q = _literal(query)
            for q, kind0 in vs:
                bounded = kind0 == "expanded"
                for row in _candidates(con, q):
                    mid = row[1]
                    if mid not in names:
                        continue
                    text = row[7]
                    norm, where = normalize_with_map(text)
                    for k in _positions(norm, q, bounded):
                        citation, key = _locate(row, names[mid], text, where, k)
                        a = where[k]
                        b = where[k + len(q) - 1] + 1
                        # 归一化后相同、原文写法不同（80,000 与 80000）：算扩展匹配，完全匹配要原文逐字是同一种写法
                        kind = kind0 if kind0 == "expanded" or _literal(text[a:b]) == literal_q else "expanded"
                        dedup = (mid, citation)
                        if dedup in found and found[dedup]["match"] == "exact":
                            continue
                        if dedup in found and kind == "expanded":
                            continue
                        snippet = text[max(0, a - SNIPPET):b + SNIPPET]
                        found[dedup] = {"hit": {"name": names[mid], "material_id": mid, "citation": citation,
                                                "snippet": snippet, "is_ocr": bool(row[6]), "match": kind},
                                        "match": kind, "key": (0 if kind == "exact" else 1, order[mid], key)}
        finally:
            con.close()
    ranked = sorted(found.values(), key=lambda x: x["key"])
    hits = [x["hit"] for x in ranked[:max_hits]]
    logs.event("search", "query", case_id=case_id, duration_ms=(time.monotonic() - t0) * 1000)
    return {"hits": hits, "total": len(ranked), "truncated": len(ranked) > len(hits)}
