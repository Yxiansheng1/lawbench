r"""T5 第二轮返修红绿（执行令 致B-ORCH-执行令-T8第二轮及T5第二轮返修-20260930-1318 第二节，含 N44 ①）。复用 T3 的 redgreen.py。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T5\redgreen_round2_fix.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location(
    "redgreen_t3", pathlib.Path(__file__).resolve().parents[1] / "T3" / "redgreen.py")
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

R = "tests/test_t5_rework2.py"
rg.TITLE = "T5 第二轮返修红绿验证"
rg.MUTATIONS = [
    ("B-P2-1·按文件身份判断导入源是不是案件根目录或在它里面", "case/materials.py", [
        ("            parts = _parts_in_case(p, root)\n", "            parts = None\n"),
    ], f"{R} -k 'bp2_1_alias_of_root or bp2_1_alias_of_temp'"),
    ("B-P2-1·导入文件夹时按文件身份跳过案件根目录那一支", "case/materials.py", [
        ("                    if not _same_file(e.path, root):", "                    if not _same_path(os.path.realpath(e.path), root):"),
    ], f"{R} -k bp2_1_alias_of_parent"),
    ("A-P2-1·打开已有的库也执行 case_db.sql、扫描时查不到表就补建（两层一起去掉）", "case/registry.py", [
        ('                    con.executescript(self.sql_path.read_text(encoding="utf-8"))\n                    return row[0]',
         "                    return row[0]"),
    ], f"{R} -k ap2_1_old_db", [
        ("case/materials.py", "                if sql_path is not None:\n                    con.executescript(",
         "                if False:\n                    con.executescript("),
    ]),
    ("A-P2-1·扫描时查不到表就补建并记日志", "case/materials.py", [
        ("                if sql_path is not None:\n                    con.executescript(",
         "                if False:\n                    con.executescript("),
    ], f"{R} -k ap2_1_missing_table"),
    ("B-P2-3·常规格式按 15 位有效数字", "ingest/xlsx.py", [
        ('        s = f"{v:.15g}"\n', '        s = repr(v)\n'),
    ], f"{R} -k bp2_3"),
    ("B-P2-4·xlsx 加载前流式数格子", "ingest/xlsx.py", [
        ("    _check_cells(path)  # 单个部件", "    open_zip(path).close()  # 单个部件"),
    ], f"{R} -k bp2_4_dense_sheet_rejected"),
    ("B-P2-4·docx 建树前流式数段落", "ingest/docx.py", [
        ("                if count_tags(f, (_P,), _P, MAX_DOCX_PARAS) > MAX_DOCX_PARAS:", "                if False:"),
    ], f"{R} -k bp2_4_docx"),
    ("X6·只认本服务自己的形状（入口和删除前两处一起改回按前缀）", "case/materials.py", [
        ("            if not (_OWN_TEMP_DIR.match(e.name) or _OWN_TEMP_FILE.match(e.name)):",
         "            if not e.name.startswith(TEMP_PREFIXES):"),
        ("                elif stat.S_ISDIR(st.st_mode) and _OWN_TEMP_DIR.match(e.name):",
         "                elif stat.S_ISDIR(st.st_mode):"),
        ("                elif stat.S_ISREG(st.st_mode) and _OWN_TEMP_FILE.match(e.name):", "                else:"),
    ], f"{R} -k x6_only_own_shapes"),
    ("X9·第一次读不了、重试成功不计 changed", "case/materials.py", [
        (' or entry["sha256"] == ZERO_SHA):\n                pass', "):\n                pass"),
    ], f"{R} -k x9_first_unreadable"),
    ("X9·material_ids 的 sha 在重试成功后更正", "case/materials.py", [
        ('                ids.fix_sha(entry["material_id"], digest)', "                pass"),
    ], f"{R} -k x9_first_unreadable"),
    ("N44·内容不是 Office 格式的 .xls/.doc 用新原因", "case/materials.py", [
        ('                    raise ParseError("corrupt" if mtype == "xlsx" else "not_office")  # N44 ①',
         '                    raise ParseError("corrupt" if mtype == "xlsx" else "unchecked")  # N44 ①'),
    ], f"{R} -k 'n44 and xls'"),
    ("A-P3-3·PDF、图片在格式版本变了时也重扫", "case/materials.py", [
        ('REFORMAT_TYPES = ("xlsx", "xls", "pdf", "image")', 'REFORMAT_TYPES = ("xlsx", "xls")'),
    ], f"{R} -k reformat"),
]


def main() -> int:
    originals = {p: p.read_bytes() for p in rg.PKG.rglob("*.py")}
    bad = 0
    print(f"{rg.TITLE}：{len(rg.MUTATIONS)} 类防护\n")
    try:
        for i, item in enumerate(rg.MUTATIONS, 1):
            label, rel, reps, sel = item[:4]
            extra = item[4] if len(item) > 4 else []
            edits = [(rel, o, n) for o, n in reps] + list(extra)
            files = {}
            for frel, old, new in edits:
                f = rg.PKG / frel
                txt = files.get(f, f.read_text(encoding="utf-8"))
                n = txt.count(old)
                if n != 1:
                    raise SystemExit(f"[{i}] {label}：{frel} 原文命中 {n} 次（应为 1），脚本需要更新")
                files[f] = txt.replace(old, new)
            try:
                for f, txt in files.items():
                    f.write_text(txt, encoding="utf-8")
                rc_red, sum_red = rg.run(sel)
            finally:
                for f in files:
                    f.write_bytes(originals[f])
            rc_green, sum_green = rg.run(sel)
            ok = rc_red != 0 and rc_green == 0
            bad += not ok
            where = "、".join(sorted({e[0] for e in edits}))
            print(f"[{i:02d}] {label}\n  改坏 {where} → {'红' if rc_red else '绿（未变红！）'}：{sum_red}\n"
                  f"  复原 → {'绿' if rc_green == 0 else '红（复原后未变绿！）'}：{sum_green}\n", flush=True)
    finally:
        for p, data in originals.items():
            if p.read_bytes() != data:
                p.write_bytes(data)
                print(f"[复原] {p}")
    same = all(p.read_bytes() == d for p, d in originals.items())
    print(f"源码与开始时逐字节一致：{'是' if same else '否'}")
    print(f"\n结论：{len(rg.MUTATIONS) - bad}/{len(rg.MUTATIONS)} 类防护 改坏即红、复原即绿")
    return 1 if bad or not same else 0


if __name__ == "__main__":
    sys.exit(main())
