r"""T9 全文检索红绿：逐条改坏即红、复原即绿。复用 T3 的 redgreen.py。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T9\redgreen_t9.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location(
    "redgreen_t3", pathlib.Path(__file__).resolve().parents[1] / "T3" / "redgreen.py")
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

R = "tests/test_search.py"
rg.TITLE = "T9 红绿验证"
rg.MUTATIONS = [
    ("1–2 字的查询在 text_norm 上 instr 扫描（改成也走 FTS）", "search/fts.py", [
        ("    if len(q) >= 3:\n        try:", "    if True:\n        try:"),
    ], f"{R} -k g9"),
    ("日期扩展", "search/expand.py", [("    for v in _dates(q) + _amounts(q):", "    for v in _amounts(q):")],
     f"{R} -k g9"),
    ("金额扩展", "search/expand.py", [("    for v in _dates(q) + _amounts(q):", "    for v in _dates(q):")],
     f"{R} -k g9"),
    ("归一化：去千分位", "search/normalize.py", [
        ("    drop = {m.start() for m in _THOUSANDS.finditer(text)}", "    drop = set()"),
    ], f"{R} -k 'normalize_rules or snippet_from_original'"),
    ("归一化：全角转半角", "search/normalize.py", [
        ('        for c in unicodedata.normalize("NFKC", ch):', "        for c in ch:"),
    ], f"{R} -k normalize_rules"),
    ("扩展出的数字要求前后不是数字", "search/fts.py", [
        ('                bounded = kind0 == "expanded"', "                bounded = False"),
    ], f"{R} -k expanded_numbers_have_digit_boundaries"),
    ("完全匹配要原文逐字是同一种写法（80,000 与 80000 算扩展）", "search/fts.py", [
        ('                        kind = kind0 if kind0 == "expanded" or _literal(text[a:b]) == literal_q else "expanded"',
         "                        kind = kind0"),
    ], f"{R} -k g9"),
    ("按需建索引：材料文本变了重建这一份", "search/fts.py", [
        ("                if state.get(mid) != stamp:", "                if False:"),
    ], f"{R} -k index_follows_material_changes"),
    ("按需建索引：材料不在了删掉它的单元", "search/fts.py", [
        ("                if mid not in wanted:", "                if False:"),
    ], f"{R} -k material_leaving_index"),
    ("片段取原文", "search/fts.py", [
        ("                        snippet = text[max(0, a - SNIPPET):b + SNIPPET]",
         "                        snippet = norm[max(0, k - SNIPPET):k + len(q) + SNIPPET]"),
    ], f"{R} -k snippet_from_original"),
    ("单元格出处的列", "search/fts.py", [("            col = ci - 1", "            col = 1")],
     f"{R} -k g9"),
    ("行出处取块内第几行", "search/fts.py", [("        no = loc_from + line_idx", "        no = loc_from")],
     f"{R} -k g9"),
    ("完全匹配排在扩展匹配前面", "search/fts.py", [
        ('"key": (0 if kind == "exact" else 1, order[mid], key)', '"key": (0, order[mid], key)'),
    ], f"{R} -k exact_ranked_before_expanded"),
    ("裁决 1·扫描完就建索引", "case/materials.py", [
        ("        search_fts.refresh_after_scan(root, case_id, index)  # T9", "        pass  # T9"),
    ], f"{R} -k index_built_at_scan"),
    ("裁决 1·建索引出错兜住、不让扫描失败", "search/fts.py", [
        ('    except Exception as e:  # noqa: BLE001\n        logs.event("search", "index"',
         '    except ZeroDivisionError as e:  # noqa: BLE001\n        logs.event("search", "index"'),
    ], f"{R} -k index_failure_does_not_break_scan"),
    ("裁决 2·case_search 工具用 T9", "tools/__init__.py", [
        ('        "case_search": search.search,',
         '        "case_search": lambda ctx, a: {"hits": [], "total": 0, "truncated": False},'),
    ], f"{R} -k case_search_tool_uses_t9"),
    ("T8 小项·begin 写到一半失败时移出 _begun", "case/task.py", [
        ("                self._begun.pop(tid, None)\n", ""),
    ], "tests/test_t8_rework2.py -k begin_write_failure"),
    ("英文字母不分大小写", "search/fts.py", [
        ("    if len(low) == len(norm) and len(ql) == len(q):\n        norm, q = low, ql\n", ""),
    ], f"{R} -k case_insensitive"),
    # ---- 返修（执行令 1721） ----
    ("P2-1·重建中途出错：在状态副本上改、出错作废状态（两层都去掉）", "search/fts.py", [
        ("    state = {} if old is None else dict(old)", "    state = {} if old is None else old"),
        ("        _state.pop(root, None)\n        raise\n    _state[root] = state", "        raise\n    _state[root] = state"),
    ], f"{R} -k refresh_failure_midway_heals"),
    ("P3-1·单元格里的 \\| 不当列分隔", "search/fts.py", [
        ("    cells = _CELL_SEP.split(line)", '    cells = line.split("|")'),
    ], f"{R} -k escaped_pipe"),
    ("P3-2·命中落在行号列不算", "search/fts.py", [
        ("    if col is None or col < 1:", "    if col is None:"),
    ], f"{R} -k escaped_pipe"),
    ("P3-3·归一化去掉控制字符", "search/normalize.py", [
        ("                continue                           # 控制字符、格式字符（零宽空格、BOM）",
         "                pass                               # 控制字符、格式字符（零宽空格、BOM）"),
    ], f"{R} -k control_chars"),
    ("P3-3·FTS5 不接受的查询串转参数错误", "search/fts.py", [
        ('            raise ApiError("INVALID_ARGUMENT", "bad_query") from None', "            raise"),
    ], f"{R} -k control_chars"),
    ("P3-4·两个汉字之间的空白去掉", "search/normalize.py", [
        ("    if len(keep) < len(out_c):", "    if False:"),
    ], f"{R} -k 'hanzi or hard_line_break'"),
    ("P3-4·完全匹配的判定也按同一规则（跨行命中算完全匹配）", "search/fts.py", [
        ('    return normalize(s.replace("\\\\|", "|"), thousands=False).lower().strip()',
         '    return " ".join(s.split()).lower()'),
    ], f"{R} -k hard_line_break"),
    ("NOTE 4·短语里的双引号转义", "search/fts.py", [
        ("""    return '"' + q.replace('"', '""') + '"'""", """    return '"' + q + '"'"""),
    ], f"{R} -k double_quote"),
    ("NOTE 6·检索表不在时按契约补建", "search/fts.py", [
        ('            con.executescript((contracts._dir / "case_db.sql").read_text(encoding="utf-8"))',
         '            raise ApiError("INTERNAL", "search_tables_missing")'),
    ], f"{R} -k tables_recreated"),
    # ---- T10 令附 T9 小项（执行令 20261001-1127） ----
    ("小项·完全匹配判定去掉首尾空格", "search/fts.py", [
        ('    return normalize(s.replace("\\\\|", "|"), thousands=False).lower().strip()',
         '    return normalize(s.replace("\\\\|", "|"), thousands=False).lower()'),
    ], f"{R} -k outer_spaces"),
    ("小项·只有 FTS5 查询串错误才转参数错误", "search/fts.py", [
        ("            if not any(s in str(e) for s in _QUERY_ERRORS):\n                raise\n", ""),
    ], f"{R} -k storage_errors_not_reported"),
    ("小项·单元格里的 \\| 建索引时还原成 |", "search/fts.py", [
        ('    if unit != "cell" or "\\\\|" not in norm:', "    if True:"),
    ], f"{R} -k escaped_pipe"),
    ("小项·完全匹配判定也还原 \\|", "search/fts.py", [
        ('    return normalize(s.replace("\\\\|", "|"), thousands=False).lower().strip()',
         "    return normalize(s, thousands=False).lower().strip()"),
    ], f"{R} -k escaped_pipe"),
    ("小项·归一化去掉格式字符（Cf）", "search/normalize.py", [
        ('            if unicodedata.category(c) in ("Cc", "Cf") and not c.isspace():',
         '            if unicodedata.category(c) == "Cc" and not c.isspace():'),
    ], f"{R} -k format_chars_dropped"),
]

_run = rg.run


def _run_no_full(sel: str):
    if sel == "tests":
        return 0, "（本脚本不跑全量，见 T9\\pytest.txt）"
    return _run(sel)


rg.run = _run_no_full

if __name__ == "__main__":
    sys.exit(rg.main())
