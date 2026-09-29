"""SEC-01 / SEC-11（上线必过第 5、21 项）：在案件目录以外全盘搜索测试案卷的特征字符串。

python acceptance\\sec\\find_leaks.py --feature LBFX-CRIM01-7Q3Z --case-dir D:\\验收\\criminal-01
  --feature   可多次；缺省为 tests\\fixtures\\README.md 的全部 8 个特征字符串
  --case-dir  案件目录（可多次），命中在这些目录内的不算泄露
  --root      搜索范围（可多次）；缺省为 %USERPROFILE%、%APPDATA%、%LOCALAPPDATA%、%TEMP%、%DSH_HOME%
  --exclude   额外排除的目录（如测试样本所在的仓库、本工具的证据目录）
  --max-mb    跳过超过此大小的文件（缺省 256），跳过的文件逐个列出

按字节搜索 UTF-8 和 UTF-16LE 两种编码（特征字符串是 ASCII，GBK 同 UTF-8）；压缩文件（docx、zip）
里的内容搜不到，所以验收看的是"解压后的正文副本有没有落到案件外"。不跟随链接和联接。
"""
from __future__ import annotations

import argparse
import mmap
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FAIL, FEATURES, PASS, UNMET, Report  # noqa: E402


def default_roots() -> list[Path]:
    out = []
    for k in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "DSH_HOME"):
        v = os.environ.get(k)
        if v and Path(v).exists():
            out.append(Path(v))
    # 去掉被其他根包含的根，避免重复搜索
    out = sorted(set(p.resolve() for p in out), key=lambda p: len(str(p)))
    uniq: list[Path] = []
    for p in out:
        if not any(p == u or u in p.parents for u in uniq):
            uniq.append(p)
    return uniq


def is_link(p: Path) -> bool:
    try:
        return p.is_symlink() or os.path.isjunction(p)
    except OSError:
        return True


def scan(roots, excludes, patterns, max_bytes, report):
    hits, skipped_big, denied, files = [], [], 0, 0
    ex = [e.resolve() for e in excludes]

    def excluded(p: Path) -> bool:
        return any(p == e or e in p.parents for e in ex)

    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None, followlinks=False):
            d = Path(dirpath)
            dirnames[:] = [n for n in dirnames if not is_link(d / n) and not excluded(d / n)]
            if excluded(d):
                continue
            for n in filenames:
                p = d / n
                try:
                    size = p.stat().st_size
                    if is_link(p) or size == 0:
                        continue
                    if size > max_bytes:
                        skipped_big.append((p, size))
                        continue
                    files += 1
                    with open(p, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
                        for label, pat in patterns:
                            if m.find(pat) != -1:
                                hits.append((p, label))
                except (OSError, ValueError):
                    denied += 1
    return hits, skipped_big, denied, files


def main() -> None:
    ap = argparse.ArgumentParser(description="案件目录外全盘搜索特征字符串")
    ap.add_argument("--feature", action="append")
    ap.add_argument("--case-dir", action="append", default=[], type=Path)
    ap.add_argument("--root", action="append", type=Path)
    ap.add_argument("--exclude", action="append", default=[], type=Path)
    ap.add_argument("--max-mb", type=int, default=256)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    r = Report("find_leaks", "SEC-01、SEC-11；上线必过第 5、21 项", a.out)
    feats = a.feature or list(FEATURES.values())
    roots = a.root or default_roots()
    if not roots:
        r.finish(UNMET, "没有可搜索的目录")
    patterns = []
    for f in feats:
        patterns += [(f"{f}（UTF-8）", f.encode("utf-8")), (f"{f}（UTF-16）", f.encode("utf-16-le"))]
    excludes = list(a.case_dir) + list(a.exclude)
    r.log(f"特征字符串：{', '.join(feats)}")
    r.log("搜索范围：" + "；".join(str(p) for p in roots))
    r.log("排除（案件目录与指定目录）：" + ("；".join(str(p) for p in excludes) or "无"))
    t0 = time.time()
    hits, big, denied, files = scan(roots, excludes, patterns, a.max_mb * 1024 * 1024, r)
    r.log(f"已搜索 {files} 个文件，用时 {time.time() - t0:.0f} 秒；无权限或读取失败 {denied} 个；超过 {a.max_mb}MB 跳过 {len(big)} 个")
    for p, s in big:
        r.log(f"  跳过（{s // 1024 // 1024}MB）：{p}")
    if hits:
        r.log(f"案件目录外命中 {len(hits)} 处：")
        for p, label in hits:
            r.log(f"  {p}　←　{label}")
        r.finish(FAIL, f"案件目录外有 {len(hits)} 处命中")
    r.finish(PASS, "案件目录外没有命中")


if __name__ == "__main__":
    main()
