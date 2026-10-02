"""find_leaks 续跑行为演示（T21 返修；输出贴进 docs\\plan\\evidence\\T21\\resume-demo.txt）。

在一个新建的临时目录里，用 d1、d2 两个子目录和一份含特征字符串的"泄露副本"，依次演示：
1. 两处副本 → 不通过；2. 同参数再跑 → 上次已跑完，从头来，仍不通过；3. 删掉副本 → 通过；
4. 在 d1 放一份新副本、不带 --fresh 再跑 → 不通过（修复前这里会沿用旧结果报"通过"）；
5. 模拟中断：进度标为没跑完并删掉一批 → 只重扫这一批，沿用的批次列出扫描时刻；
6. 模拟中断且沿用的批次已超过 24 小时 → 不沿用、重扫；
7. 再切一层（--split，模拟 %LOCALAPPDATA%）：big 的顶层文件、s1、s2 各算一批；s2 放副本 → 不通过；
   模拟中断、删掉 s2 这一批 → 只重扫 s2，其余沿用，仍不通过（命中只在 s2）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FEAT = "LBFX-CLSD01-P6V3"


def run(root: Path, out: Path, title: str, extra: tuple = ()) -> None:
    print(f"\n## {title}")
    r = subprocess.run([sys.executable, str(HERE / "find_leaks.py"), "--root", str(root), "--feature", FEAT,
                        "--out", str(out), *extra], capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    for line in r.stdout.splitlines():
        if line.startswith(("# 运行时间", "证据文件", "特征字符串", "搜索范围", "排除")):
            continue
        print(line.replace(str(root), "<root>").replace(str(out), "<out>"))
    print(f"exit={r.returncode}")


def state_file(out: Path) -> Path:
    return max(out.glob("find_leaks-*/进度.json"), key=lambda p: p.stat().st_mtime)


def main() -> None:
    base = Path(tempfile.mkdtemp(prefix="lbfx-resume-demo-"))
    root, out = base / "root", base / "out"
    (root / "d1").mkdir(parents=True)
    (root / "d2").mkdir()
    (root / "d1" / "正常.txt").write_text("与案件无关", encoding="utf-8")
    leak1, leak2 = root / "d1" / "副本.md", root / "d2" / "副本.md"
    leak1.write_text(f"案卷副本 {FEAT}", encoding="utf-8")
    leak2.write_text(f"案卷副本 {FEAT}", encoding="utf-8")
    print(f"# find_leaks 续跑行为演示  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    run(root, out, "1. d1、d2 各有一份副本，第一次运行 → 应不通过（2 处）")
    run(root, out, "2. 同样参数再跑 → 上次已跑完，从头来，仍不通过")
    leak1.unlink()
    leak2.unlink()
    run(root, out, "3. 删掉两份副本，不带 --fresh 再跑 → 应通过")
    leak1.write_text(f"新出现的副本 {FEAT}", encoding="utf-8")
    run(root, out, "4. 在 d1 新放一份副本，不带 --fresh 再跑 → 应不通过（修复前会沿用旧结果报通过）")
    sf = state_file(out)
    st = json.loads(sf.read_text(encoding="utf-8"))
    st["completed"] = False
    drop = next(k for k in st["done"] if k.endswith("d1"))
    del st["done"][drop]
    sf.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    run(root, out, "5. 模拟中断：进度标为没跑完、删掉 d1 这一批 → 只重扫 d1，其余沿用并列出扫描时刻")
    st = json.loads(sf.read_text(encoding="utf-8"))
    st["completed"] = False
    for v in st["done"].values():
        v["at"] = time.time() - 25 * 3600
    sf.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    run(root, out, "6. 模拟中断、沿用的批次都已超过 24 小时 → 全部重扫")

    big = root / "big"
    for n in ("s1", "s2"):
        (big / n).mkdir(parents=True)
    (big / "顶层.txt").write_text("与案件无关", encoding="utf-8")
    (big / "s1" / "正常.txt").write_text("与案件无关", encoding="utf-8")
    (big / "s2" / "副本.md").write_text(f"案卷副本 {FEAT}", encoding="utf-8")
    split = ("--split", str(big), "--fresh")
    run(root, out, "7a. 再切一层：--split big → big 的顶层文件、big\\s1、big\\s2 各算一批；s2 有副本 → 应不通过", split)
    sf = state_file(out)
    st = json.loads(sf.read_text(encoding="utf-8"))
    st["completed"] = False
    drop = next(k for k in st["done"] if k.endswith("s2"))
    del st["done"][drop]
    sf.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    run(root, out, "7b. 模拟中断、删掉 big\\s2 这一批，同参数（去掉 --fresh）续跑 → 只重扫 s2，其余沿用，仍不通过",
        split[:2])


if __name__ == "__main__":
    main()
