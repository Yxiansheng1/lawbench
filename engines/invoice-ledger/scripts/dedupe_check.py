# -*- coding: utf-8 -*-
"""
独立发票查重工具 — 目录级全号交叉比对（不依赖主台账）
用于验证"某目录内/某目录 vs 历史已报"是否存在重复发票。

用法:
  # 目录内部查重
  python dedupe_check.py --dir <目录A> [--dir <目录B>]

  # 目标目录 vs 历史已报根（递归扫 2~8 月）
  python dedupe_check.py --target <当期批次目录> --history-root <历史根目录>

  # 输出：控制台报告 + 查重报告_<日期>.txt

退出码：0=无重复  2=存在重复
"""

import argparse
import json
import sys
import zipfile
import tempfile
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ── 环境自举：校验当前包指纹并使用外部缓存；无有效环境时中止 ──
import sys as _sys_boot
from pathlib import Path as _Path_boot
_sys_boot.dont_write_bytecode = True
_sys_boot.path.insert(0, str(_Path_boot(__file__).resolve().parent))
import _deps
_deps.guard(__file__)

# 子模块
import extract_fields

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATE_NOW = datetime.now().strftime("%Y%m%d_%H%M%S")


def collect_pdfs(root: Path, skip_summary: bool = True, exclude: list = None):
    """递归收集 PDF（可跳过汇总单、内部目录、无扩展名文件；exclude=需排除的绝对路径集）"""
    exclude = exclude or set()
    out = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() != ".pdf":
            continue
        if skip_summary and ("汇总单" in p.name or "PDF合并" in p.name):
            continue
        parts = p.parts
        if any(seg.startswith("_") or "已分类" in seg or seg in ("raw_decoded",) for seg in parts[:-1]):
            continue
        # 排除目标目录自身（防止历史根递归时自交叉）
        if str(p.resolve()) in exclude:
            continue
        out.append(p)
    return out


def extract_full_number(pdf_path: Path):
    """提取 PDF 全号，返回 (全号, 路径字符串)；失败返回 None"""
    try:
        r = extract_fields.extract_from_pdf(str(pdf_path))
        fn = r.get("发票号码全号", "").strip()
        return fn if fn else None
    except Exception:
        return None


def extract_zip_pdfs(zip_path: Path):
    """从 ZIP 内提取全部 PDF 全号，返回 [(全号, 'zip名/内部路径')]"""
    results = []
    try:
        with zipfile.ZipFile(str(zip_path)) as zf:
            for zi in zf.infolist():
                if zi.filename.lower().endswith(".pdf") and not zi.is_dir():
                    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                    try:
                        tmp.write(zf.read(zi.filename))
                        tmp.close()
                        fn = extract_full_number(Path(tmp.name))
                        if fn:
                            results.append((fn, f"{zip_path.name}/{zi.filename}"))
                    except Exception:
                        pass
                    finally:
                        if os.path.exists(tmp.name):
                            os.unlink(tmp.name)
    except Exception:
        pass
    return results


def scan_dir(root: Path, include_zip: bool = True, exclude: set = None):
    """扫描目录全部 PDF（含 ZIP 内），返回 [(全号, 标签)] 与失败文件列表"""
    nums = []
    failed = []
    for p in collect_pdfs(root, exclude=exclude):
        fn = extract_full_number(p)
        if fn:
            nums.append((fn, str(p)))
        else:
            failed.append(str(p))
    if include_zip:
        for z in root.rglob("*.zip"):
            if exclude and str(z.resolve()) in exclude:
                continue
            nums.extend(extract_zip_pdfs(z))
    return nums, failed


def main():
    parser = argparse.ArgumentParser(description="独立发票查重工具")
    parser.add_argument("--dir", action="append", help="扫描目录（可多个，两两交叉）")
    parser.add_argument("--target", help="目标目录（与 --history-root 配合）")
    parser.add_argument("--history-root", help="历史已报根目录（递归扫描）")
    parser.add_argument("--json8", help="可选：8月已报 JSON（_dup_check_rmb.json 格式 全号→路径）")
    args = parser.parse_args()

    report_lines = []
    def log(s=""):
        print(s)
        report_lines.append(s)

    dup_total = 0
    sets = {}

    # 模式1：--dir 两两比对
    if args.dir:
        for d in args.dir:
            p = Path(d)
            if not p.is_dir():
                log(f"[ERROR] 目录不存在: {p}")
                return 1
            nums, failed = scan_dir(p)
            sets[p.name] = set(n for n, _ in nums)
            log(f"目录 [{p.name}]: PDF/ZIP 全号 {len(nums)} 个，提取失败 {len(failed)} 个")
            if failed:
                for f in failed[:5]:
                    log(f"  ⚠ {f}")
            # 内部查重
            cnt = Counter(n for n, _ in nums)
            internal = {k: v for k, v in cnt.items() if v > 1}
            if internal:
                dup_total += len(internal)
                log(f"  ! 内部重复 {len(internal)} 组:")
                for k, v in list(internal.items())[:10]:
                    paths = [t for n, t in nums if n == k]
                    log(f"      {k}: {v}处 -> {paths[:3]}")

        names = list(sets.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                cross = sets[names[i]] & sets[names[j]]
                if cross:
                    dup_total += len(cross)
                    log(f"交叉 [{names[i]} vs {names[j]}]: {len(cross)} 个重复")
                    for c in sorted(cross)[:10]:
                        log(f"  ⚠ {c}")
                else:
                    log(f"交叉 [{names[i]} vs {names[j]}]: 0 重复 ✅")

    # 模式2：--target vs --history-root
    if args.target and args.history_root:
        tp = Path(args.target)
        hp = Path(args.history_root)
        t_nums, t_failed = scan_dir(tp)
        # 历史根扫描排除目标目录自身（防止自交叉）
        exclude_self = {str(p.resolve()) for p in tp.rglob("*") if p.is_file()}
        h_nums, h_failed = scan_dir(hp, exclude=exclude_self)
        t_set = set(n for n, _ in t_nums)
        h_set = set(n for n, _ in h_nums)
        log(f"目标 [{tp.name}]: {len(t_set)} 个唯一全号（失败 {len(t_failed)}）")
        log(f"历史根 [{hp.name}]: {len(h_set)} 个唯一全号（失败 {len(h_failed)}）")
        cross = t_set & h_set
        if cross:
            dup_total += len(cross)
            log(f"\n⚠ 交叉重复: {len(cross)} 个")
            for c in sorted(cross)[:20]:
                # 找目标与历史中的路径
                t_paths = [t for n, t in t_nums if n == c][:2]
                h_paths = [t for n, t in h_nums if n == c][:2]
                log(f"  {c}")
                for x in t_paths:
                    log(f"    目标: {x}")
                for x in h_paths:
                    log(f"    历史: {x}")
        else:
            log(f"\n✅ [{tp.name}] vs 历史 [{hp.name}]: 0 重复")
        if t_failed:
            log(f"\n⚠ 目标目录 {len(t_failed)} 个文件提取失败:")
            for f in t_failed[:10]:
                log(f"  {f}")

    # 可选：对比 8月 JSON
    if args.json8:
        jp = Path(args.json8)
        if jp.exists():
            with open(jp, "r", encoding="utf-8") as f:
                data = json.load(f)
            j8_set = set(data.keys())
            for name, s in sets.items():
                cross = s & j8_set
                if cross:
                    dup_total += len(cross)
                    log(f"⚠ [{name}] vs 8月JSON({len(j8_set)}): {len(cross)} 重复")
                    for c in sorted(cross)[:10]:
                        log(f"  {c}")
                else:
                    log(f"[{name}] vs 8月JSON({len(j8_set)}): 0 重复 ✅")

    log(f"\n{'='*50}")
    log(f"结论: {'⚠ 存在 ' + str(dup_total) + ' 组重复，需人工复核' if dup_total else '✅ 未发现重复'}")
    log(f"{'='*50}")

    # 写报告 → 技能内 `_日志/`（与 invoice_db 的运行产物同址；`_` 前缀目录不参与扫描/打包）
    # 原实现写在技能**根目录**，每次运行都会往技能目录里丢文件
    if dup_total or args.target:
        d = Path(__file__).resolve().parent.parent / "_日志"
        d.mkdir(parents=True, exist_ok=True)
        out = d / f"查重报告_{DATE_NOW}.txt"
        with open(out, "w", encoding="utf-8-sig") as f:
            f.write("\n".join(report_lines))
        # 保留最近 10 个
        for old in sorted(d.glob("查重报告_*.txt"), key=lambda x: x.stat().st_mtime)[:-10]:
            try:
                old.unlink()
            except OSError:
                pass
        log(f"报告文件: {out}")

    return 2 if dup_total else 0


if __name__ == "__main__":
    sys.exit(main())