r"""T10 出处核对红绿：逐条改坏即红、复原即绿。复用 T3 的 redgreen.py。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T10\redgreen_t10.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location(
    "redgreen_t3", pathlib.Path(__file__).resolve().parents[1] / "T3" / "redgreen.py")
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

R = "tests/test_checks.py"
rg.TITLE = "T10 红绿验证"
rg.MUTATIONS = [
    # ---- 解析（parse.py） ----
    ("引号内的〔〕、〔四位数字〕不算出处", "checks/parse.py", [
        ("        if _inside(m.start(), quotes) or _YEAR.match(body) or any(", "        if any("),
    ], f"{R} -k correct_citations_pass"),
    ("出处正则从契约读（不另写宽的）", "checks/parse.py", [
        ("    return _citation_re(str(contracts._dir))", '    return re.compile(r"^〔.+〕$")'),
    ], f"{R} -k 'e_bad_format or regex_comes_from_contract'"),
    ("位置号从 1 起", "checks/parse.py", [
        ("        if a < 1:\n", "        if False:\n"),
    ], f"{R} -k e_bad_format"),
    ("位置超出材料范围", "checks/parse.py", [
        ("        if b > last:", "        if False:"),
    ], f"{R} -k e_bad_format"),
    ("单元格值还原 \\|", "checks/parse.py", [
        ('    return [c.strip().replace("\\\\|", "|").replace("<br>", "\\n") for c in cells]',
         '    return [c.strip().replace("<br>", "\\n") for c in cells]'),
    ], f"{R} -k correct_citations_pass"),
    # ---- 七类（citations.py） ----
    ("E·【】写的出处", "checks/citations.py", [
        ("        for raw in find_lenticular(body):", "        for raw in []:"),
    ], f"{R} -k e_bad_format"),
    ("E·材料名不存在", "checks/citations.py", [
        ("            if m is None:\n                rep.add(", "            if m is None:\n                continue\n                rep.add("),
    ], f"{R} -k e_bad_format"),
    ("E·位置与材料不合", "checks/citations.py", [
        ("            bad = m.check_loc(it.loc)", "            bad = None"),
    ], f"{R} -k e_bad_format"),
    ("A·识别不清的数被写成完整值", "checks/citations.py", [
        ('                if k == "num" and _ocr_num_matches(tok, v):', '                if False:'),
    ], f"{R} -k a_filled_in"),
    ("A·识别不清的姓名被写全", "checks/citations.py", [
        ("            if g and g.group(0) != tok and g.group(0) not in orig:", "            if False:"),
    ], f"{R} -k a_filled_in"),
    ("B·别处找到报 B（不是 C）", "checks/citations.py", [
        ("    if elsewhere:", "    if False:"),
    ], f"{R} -k 'b_wrong_location or cite_cases'"),
    ("金额按值比（万）", "checks/citations.py", [
        ('{"万": 10000, "亿": 100000000}.get(unit, 1)', '{"亿": 100000000}.get(unit, 1)'),
    ], f"{R} -k correct_citations_pass"),
    ("日期按年月日比", "checks/citations.py", [
        ("    return any(_date_match(v, r) for r in dates)", "    return any(v == r for r in dates)"),
    ], f"{R} -k correct_citations_pass"),
    ("只写月份的日期（月底、月份）", "checks/citations.py", [
        ('    re.compile(r"(?<![\\d年])(\\d{1,2})月(?:初|中|底|份|下旬|上旬|中旬)"),\n', ""),
    ], f"{R} -k correct_citations_pass"),
    ("只写年份能核到原文的年月", "checks/citations.py", [
        ("    if source:\n", "    if False:\n"),
    ], f"{R} -k correct_citations_pass"),
    ("数字中间折行", "checks/citations.py", [
        ('    text = normalize(_WRAPPED.sub("", text))', "    text = normalize(text)"),
    ], f"{R} -k cite_cases"),
    ("公文文号不当数值核", "checks/citations.py", [
        ('    dates, nums = extract(_DOCNO.sub(" ", fact))', "    dates, nums = extract(fact)"),
    ], f"{R} -k correct_citations_pass"),
    ("D·只在给了 declared 时查", "checks/citations.py", [
        ("            if declared is not None and it.name not in declared:",
         "            if it.name not in (declared or []):"),
    ], f"{R} -k 'd_undeclared or correct_citations_pass'"),
    ("F 是提示、G 按成果类型", "checks/citations.py", [
        ('        if cls == "F" or (cls == "G" and self.kind != "excerpt"):', '        if cls == "F":'),
    ], f"{R} -k 'g_excerpt or analysis_kind'"),
    ("G·引号内的原文不算", "checks/citations.py", [
        ("        for a, b in reversed(quote_spans(bare)):", "        for a, b in []:"),
    ], f"{R} -k g_quotes"),
    ("〔推断〕〔未找到依据〕不核 A、B、C", "checks/citations.py", [
        ("    if inferred:\n        return\n", ""),
    ], f"{R} -k inferred_skips"),
    ("表格行整行算一段", "checks/citations.py", [
        ('    if line.lstrip().startswith("|"):', "    if False:"),
    ], f"{R} -k correct_citations_pass"),
    # ---- 引语（evidence.py） ----
    ("引语逐字核对", "checks/evidence.py", [
        ('    return [q for q in found if len(squash(q)) >= QUOTE_MIN and "■" not in q]', "    return []"),
    ], f"{R} -k 'b_wrong_location or c_not_found or cite_cases'"),
    ("短引语也核（阈值 6）", "checks/evidence.py", [("QUOTE_MIN = 6", "QUOTE_MIN = 15")],
     f"{R} -k cite_cases"),
    ("引用块整段按引语核", "checks/evidence.py", [
        ("        found = [fact.strip()]", "        found = []"),
    ], f"{R} -k 'correct_citations_pass or c_not_found'"),
    # ---- 成果类型与接入 ----
    ("kind 不拼路径", "checks/__init__.py", [
        ('    if not skill or not re.fullmatch(r"[A-Za-z0-9_-]+", skill):', "    if not skill:"),
    ], f"{R} -k skill_kind"),
    ("case_save_draft 返回真核对", "tools/drafts.py", [
        ('        check, cites = citation_check(ctx, a["content"])',
         '        check, cites = {"passed": True, "problems": [], "stats": {"citations": 0, "must_fix": 0, "hints": 0}}, []'),
    ], f"{R} -k save_draft"),
    ("result.json 的出处按（材料、位置）去重", "tools/drafts.py", [
        ("    return list(out.values())", "    return list(out.values()) + new"),
    ], f"{R} -k save_draft_returns"),
    # ---- 返修（执行令 20261001-1246） ----
    ("P2-1·各种引号算同一个字符", "checks/evidence.py", [
        ("""    return _QUOTES.sub('"', _WS.sub("", normalize(s)))""", """    return _WS.sub("", normalize(s))"""),
    ], f"{R} -k correct_citations_pass"),
    ("P3-5·引语比对前归一化（全角半角）", "checks/evidence.py", [
        ("""    return _QUOTES.sub('"', _WS.sub("", normalize(s)))""", """    return _QUOTES.sub('"', _WS.sub("", s))"""),
    ], f"{R} -k correct_citations_pass"),
    ("P2-2·材料名带〔年份〕整段报 E", "checks/parse.py", [
        ("        nested.append((i, end))\n", "        continue\n"),
    ], f"{R} -k 'material_name_with_year or e_bad_format'"),
    ("P2-3·每份材料只算一次（缓存）", "checks/parse.py", [
        ("        if key not in self._memo:\n            self._memo[key] = fn(self)\n        return self._memo[key]",
         "        return fn(self)"),
    ], f"{R} -k large_sheet"),
    ("P3-1·单元格越界", "checks/parse.py", [
        ("            if any(r > max_row or c > max_col for c, r in refs):", "            if False:"),
    ], f"{R} -k 'e_bad_format or cell_errors_not_recorded'"),
    ("P3-1·单元格区域写反", "checks/parse.py", [
        ("            if len(refs) == 2 and (refs[1][0] < refs[0][0] or refs[1][1] < refs[0][1]):", "            if False:"),
    ], f"{R} -k 'e_bad_format or cell_errors_not_recorded'"),
    ("P3-2·法院案号不当金额", "checks/citations.py", [
        ('_DOCNO = re.compile(r"[〔（(][0-9]{4}[〕）)]', '_DOCNO = re.compile(r"[〔][0-9]{4}[〕]'),
    ], f"{R} -k correct_citations_pass"),
    ("P3-3·单引号、全角双引号也是引号", "checks/parse.py", [
        ("|‘[^’\\n]*’|＂[^＂\\n]*＂\")", "\")"),
    ], f"{R} -k 'c_not_found or g_quotes'"),
    ("P3-4·管理员目录覆盖安装目录", "checks/__init__.py", [
        ("    for d in reversed(list(skills_dirs or ())):", "    for d in skills_dirs or ():"),
    ], f"{R} -k skill_kind_admin"),
    ("P3-4·SKILL.md 头部去 BOM", "checks/__init__.py", [
        ('.read_text(encoding="utf-8", errors="replace").lstrip("\\ufeff")', '.read_text(encoding="utf-8", errors="replace")'),
    ], f"{R} -k skill_kind_admin"),
    ("裁决 4·所标位置只用中文数字写时不报", "checks/citations.py", [
        ("        if any(_chinese_only(m.text_at(loc), values_at(m, loc), k, v) for m, loc in targets):",
         "        if False:"),
    ], f"{R} -k correct_citations_pass"),
    ("裁决 4·有阿拉伯数字的同类值时照常核", "checks/citations.py", [
        ('    return not any(not n.startswith(("%", "年")) for n in nums) and bool(_CN_AMOUNT.search(text))',
         "    return bool(_CN_AMOUNT.search(text))"),
    ], f"{R} -k c_not_found"),
    ("result.json 同一处以最新保存为准", "tools/drafts.py", [
        ('        out[(c["material_id"], json.dumps(c["loc"], sort_keys=True))] = c',
         '        out.setdefault((c["material_id"], json.dumps(c["loc"], sort_keys=True)), c)'),
    ], f"{R} -k merge_keeps_latest"),
    ("工具调用带上 Skill 目录（按 kind 区分 G）", "api/core.py", [
        (",\n                               skills_dirs=tuple(st.config.skills_dirs))", ")"),
    ], f"{R} -k save_draft"),
]

_run = rg.run


def _run_no_full(sel: str):
    if sel == "tests":
        return 0, "（本脚本不跑全量，见 T10\\pytest.txt）"
    return _run(sel)


rg.run = _run_no_full

if __name__ == "__main__":
    sys.exit(rg.main())
