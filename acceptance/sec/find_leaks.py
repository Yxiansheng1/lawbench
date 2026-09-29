"""SEC-01 / SEC-11（上线必过第 5、21 项）：在案件目录以外全盘搜索测试案卷的特征字符串。

python acceptance\\sec\\find_leaks.py --feature LBFX-CRIM01-7Q3Z --case-dir D:\\验收\\criminal-01
  --feature   可多次；缺省为 tests\\fixtures\\README.md 的全部 8 个特征字符串
  --case-dir  案件目录（可多次），命中在这些目录内的不算泄露
  --root      搜索范围（可多次）；缺省为 %USERPROFILE%、%APPDATA%、%LOCALAPPDATA%、%TEMP%、%DSH_HOME%
  --exclude   额外排除的目录（如测试样本所在的仓库、本工具的证据目录）
  --max-mb    跳过超过此大小的文件（缺省 256），跳过的文件逐个列出
  --fresh     不续跑，从头搜

按顶层目录分批：每扫完一批打印一行（文件数、命中数、耗时），结果单独写进证据目录下
find_leaks-<参数摘要>\批NNNN.txt，进度记在同目录的 进度.json。中断后用同样的参数再运行，
自动从没扫完的那一批继续；沿用的批次在证据里列出扫描时刻，超过 24 小时的不沿用、重扫。
一次运行全部扫完后标记为已完成，下一次运行自动从头开始（续跑只对没跑完的那一次有效）。
不排除任何目录（桌面端的缓存正是正文副本可能落脚的地方）。

按字节搜索 UTF-8 和 UTF-16LE 两种编码（特征字符串是 ASCII，GBK 同 UTF-8）；压缩文件（docx、zip）
里的内容搜不到，所以验收看的是"解压后的正文副本有没有落到案件外"。不跟随链接和联接。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FAIL, FEATURES, PASS, UNMET, Report  # noqa: E402


MAX_REUSE_S = 24 * 3600       # 中断前扫完的批次最多沿用 24 小时


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


def scan_one(p: Path, patterns, max_bytes, acc) -> None:
    try:
        size = p.stat().st_size
        if is_link(p) or size == 0:
            return
        if size > max_bytes:
            acc["big"].append([str(p), size])
            return
        acc["files"] += 1
        with open(p, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
            for label, pat in patterns:
                if m.find(pat) != -1:
                    acc["hits"].append([str(p), label])
    except (OSError, ValueError):
        acc["denied"] += 1


def batches(roots, excluded) -> list[tuple[str, Path, bool]]:
    """按顶层目录分批：每个根目录下的顶层文件算一批，每个顶层子目录各算一批。返回 (批名, 路径, 是否递归)。"""
    out = []
    for root in roots:
        if excluded(root):
            continue
        out.append((f"{root}（顶层文件）", root, False))
        try:
            subs = sorted(e for e in root.iterdir() if e.is_dir() and not is_link(e) and not excluded(e))
        except OSError:
            subs = []
        out += [(str(d), d, True) for d in subs]
    return out


def scan_batch(path: Path, recursive: bool, excluded, patterns, max_bytes) -> dict:
    acc = {"files": 0, "hits": [], "big": [], "denied": 0}
    t0 = time.time()
    if not recursive:
        try:
            for e in path.iterdir():
                if e.is_file():
                    scan_one(e, patterns, max_bytes, acc)
        except OSError:
            acc["denied"] += 1
    else:
        for dirpath, dirnames, filenames in os.walk(path, onerror=lambda e: None, followlinks=False):
            d = Path(dirpath)
            dirnames[:] = [n for n in dirnames if not is_link(d / n) and not excluded(d / n)]
            for n in filenames:
                scan_one(d / n, patterns, max_bytes, acc)
    acc["secs"] = round(time.time() - t0, 1)
    return acc


def run_key(feats, roots, excludes, max_mb) -> str:
    raw = json.dumps([feats, [str(p) for p in roots], sorted(str(p) for p in excludes), max_mb], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def main() -> None:
    ap = argparse.ArgumentParser(description="案件目录外全盘搜索特征字符串（按顶层目录分批，可中断续跑）")
    ap.add_argument("--feature", action="append")
    ap.add_argument("--case-dir", action="append", default=[], type=Path)
    ap.add_argument("--root", action="append", type=Path)
    ap.add_argument("--exclude", action="append", default=[], type=Path)
    ap.add_argument("--max-mb", type=int, default=256)
    ap.add_argument("--fresh", action="store_true", help="不续跑，丢掉上次的进度从头搜")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    r = Report("find_leaks", "SEC-01、SEC-11；上线必过第 5、21 项", a.out)
    feats = a.feature or list(FEATURES.values())
    roots = [p.resolve() for p in (a.root or default_roots())]
    if not roots:
        r.finish(UNMET, "没有可搜索的目录")
    patterns = []
    for f in feats:
        patterns += [(f"{f}（UTF-8）", f.encode("utf-8")), (f"{f}（UTF-16）", f.encode("utf-16-le"))]
    excludes = list(a.case_dir) + list(a.exclude)
    ex = [e.resolve() for e in excludes]

    def excluded(p: Path) -> bool:
        return any(p == e or e in p.parents for e in ex)

    r.log(f"特征字符串：{', '.join(feats)}")
    r.log("搜索范围：" + "；".join(str(p) for p in roots))
    r.log("排除（案件目录与指定目录）：" + ("；".join(str(p) for p in excludes) or "无"))

    key = run_key(feats, roots, excludes, a.max_mb)
    batch_dir = r.out_dir / f"find_leaks-{key}"
    state_file = batch_dir / "进度.json"
    batch_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
    r.log(f"本次运行开始：{started}")
    state = {"completed": False, "done": {}}
    if state_file.exists() and not a.fresh:
        old = json.loads(state_file.read_text(encoding="utf-8"))
        if old.get("completed", False):
            r.log("上次运行已全部扫完：本次从头开始（续跑只对没跑完的那一次有效）")
        else:
            fresh = {k: v for k, v in old.get("done", {}).items() if now - v.get("at", 0) <= MAX_REUSE_S}
            stale = len(old.get("done", {})) - len(fresh)
            state["done"] = fresh
            r.log(f"续跑：沿用上次中断前已扫完的 {len(fresh)} 批"
                  + (f"；另有 {stale} 批超过 24 小时，不沿用、重扫" if stale else ""))
    elif a.fresh:
        r.log("--fresh：从头开始")
    reused = set(state["done"])
    plan = batches(roots, excluded)
    r.log(f"共 {len(plan)} 批；每批结果单独写进 {batch_dir}")
    t_all = time.time()
    for i, (name, path, recursive) in enumerate(plan, 1):
        if name in state["done"]:
            continue
        acc = scan_batch(path, recursive, excluded, patterns, a.max_mb * 1024 * 1024)
        acc["at"] = time.time()
        state["done"][name] = acc
        lines = [f"批 {i}：{name}（{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(acc['at']))} 扫描）",
                 f"文件 {acc['files']} 个，命中 {len(acc['hits'])} 处，"
                 f"无权限或读取失败 {acc['denied']} 个，超大跳过 {len(acc['big'])} 个，用时 {acc['secs']} 秒"]
        lines += [f"  命中：{p}　←　{label}" for p, label in acc["hits"]]
        lines += [f"  跳过（{s // 1024 // 1024}MB）：{p}" for p, s in acc["big"]]
        (batch_dir / f"批{i:04d}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        print(f"[{i}/{len(plan)}] {name}：文件 {acc['files']} 个，命中 {len(acc['hits'])}，用时 {acc['secs']} 秒",
              flush=True)
    state["completed"] = True                        # 全部扫完：下次运行从头开始
    state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    names = {n for n, _, _ in plan}
    for n in sorted(reused & names):
        at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(state["done"][n].get("at", 0)))
        r.log(f"  沿用：{n}（{at} 扫描，中断前的结果）")
    state["done"] = {k: v for k, v in state["done"].items() if k in names}
    scanned_files = sum(v["files"] for k, v in state["done"].items() if k not in reused)
    reused_files = sum(v["files"] for k, v in state["done"].items() if k in reused)
    done = state["done"]
    files = sum(v["files"] for v in done.values())
    denied = sum(v["denied"] for v in done.values())
    big = [b for v in done.values() for b in v["big"]]
    hits = [h for v in done.values() for h in v["hits"]]
    r.log(f"已搜索 {files} 个文件：本次实际扫描 {scanned_files} 个（用时 {time.time() - t_all:.0f} 秒），"
          f"沿用中断前的结果 {reused_files} 个；无权限或读取失败 {denied} 个；超过 {a.max_mb}MB 跳过 {len(big)} 个")
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
