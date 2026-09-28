#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
classify_archived.py — invoice-mail-downloader → invoice-pdf-renamer 联动桥接脚本

将归档目录（按来源/日期分目录存放的发票 PDF，可能含 ZIP/TSV 等非 PDF 文件）
递归合并平铺到分类工作目录，然后自动调用 invoice-pdf-renamer 的 --sort 模式
执行分类重命名 + Excel 统计，实现"下载归档 → 分类命名 → Excel 统计"端到端闭环。

用法:
  python classify_archived.py <归档目录> [--out <分类目录>] [--renamer <脚本路径>] [--python <解释器>] [--dry-run]

参数:
  archived_dir   归档目录（递归扫描所有 .pdf，自动跳过 _raw_decoded/_chrome/已分类 等内部目录）
  --out          分类输出目录（默认: <归档目录>_已分类_YYYYMMDD）
  --renamer      invoice_renamer.py 路径（默认自动探测用户级技能安装位置）
  --python       Python 解释器（默认自动探测：系统 Python → managed Python）
  --dry-run      仅合并预览 + 打印 renamer 调用命令，不实际执行分类

退出码:
  0  成功（含 dry-run）
  1  失败
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ── 环境自举：校验当前包指纹并使用外部缓存；无有效环境时中止 ──
import sys as _sys_boot
from pathlib import Path as _Path_boot
_sys_boot.dont_write_bytecode = True
_sys_boot.path.insert(0, str(_Path_boot(__file__).resolve().parent))
import _deps
_deps.guard(__file__)

# 默认跳过目录（下载技能内部工作目录）
SKIP_DIR_NAMES = {"_raw_decoded", "_chrome", "_raw", "__pycache__", ".git"}
# 若目标目录名含这些标记，视为"已分类输出目录"，跳过避免递归复制自身
SKIP_DIR_MARKERS = ("已分类", "_classify_out", "_renamer_", "分类")


def ensure_utf8():
    """Windows 控制台 utf-8 输出。"""
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def is_skip_dir(name: str) -> bool:
    if name in SKIP_DIR_NAMES:
        return True
    return any(m in name for m in SKIP_DIR_MARKERS)


def find_pdfs(archived_dir: str) -> list:
    """递归收集 PDF，返回 [(源路径, 文件名), ...]。"""
    files = []
    root = Path(archived_dir)
    for dirpath, dirnames, filenames in os.walk(root):
        # 原地过滤跳过目录
        dirnames[:] = [d for d in dirnames if not is_skip_dir(d)]
        for f in filenames:
            if f.lower().endswith(".pdf"):
                files.append((os.path.join(dirpath, f), f))
    return files


def merge_to_flat(sources: list, out_dir: str) -> dict:
    """
    将 PDF 平铺复制到 out_dir。
    同名同内容 → 跳过（记 duplicate）
    同名不同内容 → 追加 _dupN 后缀
    返回 {copied: [...], skipped_dup: [...], renamed_dup: [...]}
    """
    os.makedirs(out_dir, exist_ok=True)
    result = {"copied": [], "skipped_dup": [], "renamed_dup": []}
    known_hashes = {md5(str(p)) for p in Path(out_dir).glob("*.pdf")}
    for src_path, fname in sources:
        digest = md5(src_path)
        if digest in known_hashes:
            result["skipped_dup"].append(fname)
            continue
        known_hashes.add(digest)
        dest = os.path.join(out_dir, fname)
        if os.path.exists(dest):
            h1 = md5(src_path)
            h2 = md5(dest)
            if h1 == h2:
                result["skipped_dup"].append(fname)
                continue
            # 同名不同内容：追加后缀
            base, ext = os.path.splitext(fname)
            n = 1
            while os.path.exists(dest):
                dest = os.path.join(out_dir, f"{base}_dup{n}{ext}")
                n += 1
            result["renamed_dup"].append((fname, os.path.basename(dest)))
        shutil.copy2(src_path, dest)
        result["copied"].append(os.path.basename(dest))
    return result


def md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def probe_renamer() -> str:
    """探测 invoice_renamer.py 路径（优先技能内同目录，其次 ~/.workbuddy/skills）。"""
    here = Path(__file__).resolve().parent
    candidates = [str(Path(__file__).with_name("invoice_renamer.py"))]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return ""


def probe_python() -> str:
    """返回已验证的外部缓存解释器，不回落宿主。"""
    import _deps
    return str(_deps.ensure_runtime() / "python.exe")


def main():
    ensure_utf8()
    ap = argparse.ArgumentParser(description="发票归档目录一键分类（downloader → renamer 联动）")
    ap.add_argument("archived_dir", help="归档目录（递归扫描 PDF）")
    ap.add_argument("--out", default="", help="分类输出目录（默认 <归档目录>_已分类_YYYYMMDD）")
    ap.add_argument("--renamer", default="", help="invoice_renamer.py 路径（默认自动探测）")
    ap.add_argument("--python", default="", help="Python 解释器（默认自动探测）")
    ap.add_argument("--dry-run", action="store_true", help="仅预览，不执行分类")
    args = ap.parse_args()

    if not os.path.isdir(args.archived_dir):
        print(f"[ERROR] 归档目录不存在: {args.archived_dir}")
        sys.exit(1)

    from archive_extract import expand_archives
    if not args.dry_run:
        try: expand_archives(args.archived_dir)
        except Exception as e:
            print("[ERROR] ZIP解压失败：", e)
            return 2
    # 1. 收集 PDF
    sources = find_pdfs(args.archived_dir)
    if not sources:
        print(f"[ERROR] 目录中未找到 PDF: {args.archived_dir}")
        sys.exit(1)
    print(f"[INFO] 扫描到 {len(sources)} 个 PDF")

    # 2. 输出目录
    out_dir = args.out or f"{args.archived_dir.rstrip('/\\\\')}_已分类_{time.strftime('%Y%m%d')}"
    if os.path.abspath(out_dir) == os.path.abspath(args.archived_dir):
        print("[ERROR] 输出目录不能等于归档目录")
        sys.exit(1)

    # 3. 合并平铺
    print(f"[INFO] 合并 PDF 到: {out_dir}")
    merged = merge_to_flat(sources, out_dir)
    print(f"  复制: {len(merged['copied'])} | 同内容跳过: {len(merged['skipped_dup'])} | 同名异内容改名: {len(merged['renamed_dup'])}")
    for f in merged["skipped_dup"]:
        print(f"  [SKIP-同内容] {f}")
    for old, new in merged["renamed_dup"]:
        print(f"  [RENAME-异内容] {old} -> {new}")

    # 4. 定位 renamer 与 Python
    renamer = args.renamer or probe_renamer()
    if not renamer or not os.path.isfile(renamer):
        print("[ERROR] 未找到 invoice_renamer.py，可用 --renamer 指定")
        sys.exit(1)
    python = probe_python()
    if args.python and Path(args.python).resolve() != Path(python).resolve():
        print("[ERROR] --python 必须指向当前环境包对应的缓存解释器")
        sys.exit(1)
    if not python:
        print("[ERROR] 未找到带 pdfplumber/openpyxl 的 Python，可用 --python 指定")
        sys.exit(1)
    print(f"[INFO] renamer: {renamer}")
    print(f"[INFO] python:  {python}")

    # 5. 执行分类
    cmd = [python, renamer, out_dir, "--sort"]
    print(f"[INFO] 执行: {' '.join(cmd)}")
    if args.dry_run:
        print("[DRY-RUN] 跳过实际执行")
        print(f"[DRY-RUN] 分类输出目录就绪: {out_dir}")
        sys.exit(0)

    proc = subprocess.run(cmd, cwd=out_dir)
    if proc.returncode != 0:
        print(f"[ERROR] renamer 执行失败，退出码 {proc.returncode}")
        sys.exit(proc.returncode)
    print(f"\n[OK] 分类完成。输出目录: {out_dir}")
    print(f"[OK] Excel 统计表: {os.path.join(out_dir, '发票统计表.xlsx')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
