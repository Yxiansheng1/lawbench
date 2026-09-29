"""重新生成 tests\\fixtures\\ 下的 8 个虚构样本案件。

用法：
    python tests\\fixtures\\_gen\\make_all.py              # 生成到 tests\\fixtures\\
    python tests\\fixtures\\_gen\\make_all.py --out <目录>  # 生成到别的目录（干净目录复现用）

只删除并重建 8 个样本目录；wiki-test\\、三份用例 JSON 和 README.md 不动。
依赖见同目录 requirements.txt；需要 Windows 自带的中文字体（黑体、宋体、楷体）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common as C  # noqa: E402
import case_attack01  # noqa: E402
import case_broken  # noqa: E402
import case_civil01  # noqa: E402
import case_closed01  # noqa: E402
import case_contract01  # noqa: E402
import case_criminal01  # noqa: E402
import case_invoices01  # noqa: E402
import case_tender01  # noqa: E402

MODULES = [case_criminal01, case_civil01, case_contract01, case_attack01,
           case_broken, case_closed01, case_tender01, case_invoices01]
CASES = [m.CASE for m in MODULES]


def _remove_links(d: Path) -> None:
    """先拆掉链接本身，避免删除目录时顺着联接删到案件外。"""
    for dirpath, dirnames, filenames in os.walk(d, followlinks=False):
        for n in dirnames + filenames:
            p = Path(dirpath) / n
            if p.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(p)):
                if p.is_dir() and not p.is_symlink():
                    os.rmdir(p)          # 联接：rmdir 只删联接，不动目标
                else:
                    p.unlink()
        dirnames[:] = [n for n in dirnames if (Path(dirpath) / n).exists()
                       and not (Path(dirpath) / n).is_symlink()]


def tree_size(d: Path) -> int:
    """目录下普通文件的总字节数，不跟随链接和联接。"""
    total = 0
    for dirpath, dirnames, filenames in os.walk(d, followlinks=False):
        dirnames[:] = [n for n in dirnames if not os.path.isjunction(Path(dirpath) / n)]
        for n in filenames:
            p = Path(dirpath) / n
            if not p.is_symlink():
                total += p.stat().st_size
    return total


def clean(out: Path) -> None:
    for case in CASES:
        d = out / case
        if d.exists():
            _remove_links(d)
            shutil.rmtree(d)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=C.FIXTURES)
    args = ap.parse_args()
    out: Path = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    clean(out)
    for m in MODULES:
        r = m.build(out)
        extra = f"  链接：{r}" if isinstance(r, dict) else ""
        print(f"[生成] {m.CASE}{extra}")
    total = sum(tree_size(out / c) for c in CASES)
    print(f"[完成] 8 个样本案件，共 {total / 1024 / 1024:.2f} MB，输出目录 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
