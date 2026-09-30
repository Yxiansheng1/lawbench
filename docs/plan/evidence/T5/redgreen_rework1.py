r"""T5 第一轮返修红绿（执行令 致B-ORCH-执行令-T3第三轮及T5返修-20260930-0136 第 3 节）：逐条改坏即红、复原即绿。

复用 T3 的 redgreen.py 的 run()；结束时核对源码逐字节复原，再跑一次全量。
用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T5\redgreen_rework1.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_T3 = pathlib.Path(__file__).resolve().parents[1] / "T3" / "redgreen.py"
_spec = importlib.util.spec_from_file_location("redgreen_t3", _T3)
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

R = "tests/test_t5_rework.py"
MUTATIONS = [
    ("X1·扩展名 .xls、内容是 xlsx：按文件头走 xlsx 的检查（改回先转换）", "case/materials.py", [
        ('                if kind == "zip":\n                    return xlsx.parse(path, recalc=self._recalc(path, s))',
         '                if kind == "zip" and mtype == "xls":\n'
         '                    return xlsx.parse(s.convert(path, "xlsx"), recalc=None)\n'
         '                if kind == "zip":\n                    return xlsx.parse(path, recalc=self._recalc(path, s))'),
    ], "tests/test_t5_convert_safety.py -k xls_no_request"),
    ("X1·扩展名 .doc、内容是 docx：直接读，不交给 LibreOffice", "case/materials.py", [
        ('                if kind == "zip":\n                    return docx.parse(path)',
         '                if kind == "zip" and mtype == "docx":\n                    return docx.parse(path)'),
    ], f"{R} -k x1_doc_with_docx"),
    ("X1·内容既不是 OLE 也不是压缩包：不交给 LibreOffice", "case/materials.py", [
        ('                if kind != "ole":\n                    raise ParseError("corrupt" if mtype == "docx" else "unchecked")',
         '                if kind != "ole":\n                    return docx.parse(s.convert(path, "docx"))'),
    ], f"{R} -k x1_other_content"),
    ("X2·关系文件解析出错即拒绝", "ingest/links.py", [
        ('    except Exception:  # noqa: BLE001 读不了、解析出错（X2）\n        raise ParseError("unchecked")',
         '    except Exception:  # noqa: BLE001\n        return etree.fromstring(b"<r/>")'),
    ], f"{R} -k x2_bad_rels"),
    ("X2·Data 流读不了即拒绝", "ingest/links.py", [
        ('    except Exception:  # noqa: BLE001 容器坏了、流读不了：查不了就不放行（X2）\n        raise ParseError("unchecked")',
         '    except Exception:  # noqa: BLE001\n        return False'),
    ], f"{R} -k x2_ole_checks"),
    ("X2·加密判断出错即拒绝", "ingest/detect.py", [
        ('    except Exception:  # noqa: BLE001 olefile 对坏文件抛的异常种类很多\n        raise ParseError("unchecked")',
         '    except Exception:  # noqa: BLE001\n        return False'),
    ], f"{R} -k x2_ole_checks"),
    ("X3·导入源是案件根目录：只扫描", "case/materials.py", [
        ('            if _same_path(real, root):\n                continue', '            if False:\n                continue'),
    ], f"{R} -k x3_import_case_root_itself"),
    ("X3·导入源是案件的上级：跳过案件根目录那一支", "case/materials.py", [
        ("                    if not _same_path(os.path.realpath(e.path), root):", "                    if True:"),
    ], f"{R} -k x3_import_parent"),
    ("X4·压缩包部件解压前看大小", "ingest/links.py", [
        ("    if any(i.file_size > MAX_PART_BYTES for i in z.infolist()):", "    if False:"),
    ], f"{R} -k 'x4_docx_part or x4_xlsx_part'"),
    ("X4·xlsx 只遍历实际存在的单元格", "ingest/xlsx.py", [
        ("    return ws._cells  # noqa: SLF001",
         "    return {(c.row, c.column): c for row in ws.iter_rows() for c in row}  # noqa: SLF001"),
    ], f"{R} -k 'x4_xlsx_far_cell_fast and coord0'"),
    ("X4·写出的格子数上限", "ingest/xlsx.py", [
        ("            if len(texts) * max_col > MAX_SHEET_CELLS:", "            if False:"),
    ], f"{R} -k x4_xlsx_too_many"),
    ("X5·导入的临时文件写在 工作区/临时/", "case/gate.py", [
        ("    tmp, fd = _exclusive_tmp(tmp_dir, IMPORT_TMP_PREFIX)",
         "    _mkdirs(root, path.parent, op)\n    tmp, fd = _exclusive_tmp(path.parent, IMPORT_TMP_PREFIX)"),
    ], f"{R} -k x5_"),
    ("X6·扫描开始时清本服务前缀的残留", "case/materials.py", [
        ("        self._clean_temp(root)\n", ""),
    ], f"{R} -k 'x5_x6 or x6_'"),
    ("X6·只清自己前缀的", "case/materials.py", [
        ("            if not e.name.startswith(TEMP_PREFIXES):", "            if False:"),
    ], f"{R} -k x6_"),
    ("X7·工作区 下 临时 以外的文件不接受导入", "case/materials.py", [
        ('                    if len(parts) > 2 and parts[1] == "临时" and stat.S_ISREG(st.st_mode):',
         "                    if stat.S_ISREG(st.st_mode):"),
    ], f"{R} -k x7_non_temp"),
    ("X7·复制成功后才删临时文件", "case/materials.py", [
        ("                        if self._import_file(root, p, target, os.path.basename(p), copied, skipped, unzip):\n",
         "                        self._import_file(root, p, target, os.path.basename(p), copied, skipped, unzip)\n"
         "                        if True:\n"),
    ], f"{R} -k x7_temp_file_deleted_only"),
    ("X8·长路径前缀遍历，超长原件登记为失败", "case/materials.py", [
        ('        stack: list[tuple[str, str]] = [(_long_path(root), "")]', '        stack: list[tuple[str, str]] = [(root, "")]'),
    ], f"{R} -k x8_too_long"),
    ("X8·读不了的文件夹里的旧条目不标原件已删除", "case/materials.py", [
        ('            if any(m["rel_path"].startswith(d) for d in unreadable_dirs):', "            if False:"),
    ], f"{R} -k x8_unreadable"),
    ("X8·读不了的原件登记为失败", "case/materials.py", [
        ("            except OSError:\n                digest = None", "            except OSError:\n                continue"),
    ], f"{R} -k x8_locked"),
    ("X9·跟环境有关的失败每次扫描都重试", "case/materials.py", [
        ('            retry = live and entry["status"] == "failed" and entry["error"] in RETRY_MESSAGES',
         "            retry = False"),
    ], f"{R} -k x9_retry_by_reason"),
    ("X10·第三级仍重名时加 _2、_3", "case/materials.py", [
        ("                while n.casefold() in taken:", "                while False:"),
    ], f"{R} -k x10_"),
    ("X11·index.json 丢失后编号从能找到的最大编号加 1 起", "case/materials.py", [
        ('"next_seq": _recover_next_seq(root)', '"next_seq": 1'),
    ], f"{R} -k x11_ids"),
    ("X12·导入文件夹时跳过任何层级的点开头项", "case/materials.py", [
        ('                if e.name.startswith("."):\n                    skipped.append', '                if False:\n                    skipped.append'),
    ], f"{R} -k x12_dot_items"),
    ("X12·ZIP 里的点开头成员跳过", "case/materials.py", [
        ('                    if any(part.startswith(".") for part in name.split("/")):', "                    if False:"),
    ], f"{R} -k x12_dot_members"),
    ("Y5·文本框只取 Choice", "ingest/docx.py", [
        (' | {_FALLBACK}', ''),
    ], f"{R} -k y5_textbox"),
    ("Y5·带 DOCTYPE 的部件按失败", "ingest/docx.py", [
        ('    if root.getroottree().docinfo.doctype:\n        raise ParseError("corrupt")',
         '    if False:\n        raise ParseError("corrupt")'),
    ], f"{R} -k y5_doctype"),
    ("Y6·UTF-16 文本", "ingest/text.py", [
        ('    if data[:2] in (b"\\xff\\xfe", b"\\xfe\\xff"):', "    if False:"),
    ], f"{R} -k y6_"),
    ("Y7·重算不成退回写公式", "ingest/xlsx.py", [
        ('            logs.event("materials", "recalc", status="fail", error=e.reason)', "            raise"),
    ], f"{R} -k y7_"),
]


def main() -> int:
    originals = {p: p.read_bytes() for p in rg.PKG.rglob("*.py")}
    bad = 0
    print(f"T5 第一轮返修红绿验证：{len(MUTATIONS)} 类防护\n")
    try:
        for i, (label, rel, reps, sel) in enumerate(MUTATIONS, 1):
            f = rg.PKG / rel
            src = f.read_text(encoding="utf-8")
            mutated = src
            for old, new in reps:
                n = mutated.count(old)
                if n != 1:
                    raise SystemExit(f"[{i}] {label}：原文命中 {n} 次（应为 1），脚本需要更新")
                mutated = mutated.replace(old, new)
            try:
                f.write_text(mutated, encoding="utf-8")
                rc_red, sum_red = rg.run(sel)
            finally:
                f.write_bytes(originals[f])
            rc_green, sum_green = rg.run(sel)
            ok = rc_red != 0 and rc_green == 0
            bad += not ok
            print(f"[{i:02d}] {label}\n  改坏 {rel} → {'红' if rc_red else '绿（未变红！）'}：{sum_red}\n"
                  f"  复原 → {'绿' if rc_green == 0 else '红（复原后未变绿！）'}：{sum_green}\n", flush=True)
    finally:
        for p, data in originals.items():
            if p.read_bytes() != data:
                p.write_bytes(data)
                print(f"[复原] {p}")
    same = all(p.read_bytes() == d for p, d in originals.items())
    print(f"源码与开始时逐字节一致：{'是' if same else '否'}")
    print(f"\n结论：{len(MUTATIONS) - bad}/{len(MUTATIONS)} 类防护 改坏即红、复原即绿")
    return 1 if bad or not same else 0


if __name__ == "__main__":
    sys.exit(main())
