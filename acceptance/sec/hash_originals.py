"""SEC-08（上线必过第 4、21 项）：原件哈希前后比对。

python acceptance\\sec\\hash_originals.py snapshot <案件目录> <清单.json>   # 验收开始前
python acceptance\\sec\\hash_originals.py compare  <案件目录> <清单.json>   # 验收做完后（含导入、归档之后）

原件区 = 案件目录中除 工作区\\、成果\\ 和以 . 开头的项以外的全部文件（formats.md 第 1 节）。
compare：已有原件的 sha256 一个都不能变、不能少；新增的原件只列出（由律师导入产生，只新增、不覆盖）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FAIL, PASS, UNMET, Report  # noqa: E402

SKIP_TOP = {"工作区", "成果"}


def originals(case: Path) -> dict[str, str]:
    out = {}
    for p in sorted(case.rglob("*")):
        rel = p.relative_to(case)
        if rel.parts[0] in SKIP_TOP or any(x.startswith(".") for x in rel.parts):
            continue
        if p.is_file() and not p.is_symlink():
            out[rel.as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["snapshot", "compare"])
    ap.add_argument("case", type=Path)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    r = Report(f"hash_originals-{a.mode}", "SEC-08；上线必过第 4、21 项", a.out)
    if not a.case.is_dir():
        r.finish(UNMET, f"案件目录不存在：{a.case}")
    now = originals(a.case)
    if a.mode == "snapshot":
        a.manifest.write_text(json.dumps(now, ensure_ascii=False, indent=1), encoding="utf-8")
        r.log(f"已记录 {len(now)} 个原件的 sha256 → {a.manifest}")
        r.finish(PASS, "快照已保存，验收完成后运行 compare")
    if not a.manifest.exists():
        r.finish(UNMET, "没有验收前的快照，先运行 snapshot")
    before = json.loads(a.manifest.read_text(encoding="utf-8"))
    changed = [k for k in before if k in now and now[k] != before[k]]
    missing = [k for k in before if k not in now]
    added = [k for k in now if k not in before]
    r.log(f"验收前 {len(before)} 个原件，现在 {len(now)} 个")
    for k in changed:
        r.log(f"  被改动：{k}")
    for k in missing:
        r.log(f"  被删除或移走：{k}")
    for k in added:
        r.log(f"  新增（应为律师导入）：{k}")
    if changed or missing:
        r.finish(FAIL, f"{len(changed)} 个原件被改动，{len(missing)} 个不见了")
    r.finish(PASS, f"已有原件全部未变；新增 {len(added)} 个")


if __name__ == "__main__":
    main()
