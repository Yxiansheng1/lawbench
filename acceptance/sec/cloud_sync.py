"""SEC-14（上线必过第 20 项）：案件文件夹位于云同步目录时拒绝打开并提示。

python acceptance\\sec\\cloud_sync.py
前提：工作台服务在运行（LB_URL、LB_TOKEN）。脚本在下面几个位置各建一个空的测试案件文件夹，
调 POST /api/case/open，应全部被拒绝（返回失败体，提示移到本机普通文件夹）；再在普通目录建一个作对照，
应能打开。测完删掉自己建的测试文件夹（只删本脚本建的、名为 lbfx-云同步验收-* 的空文件夹）。
  - %OneDrive%（或 %USERPROFILE%\\OneDrive）下
  - 名字含"坚果云"的目录下（%TEMP%\\坚果云同步\\）
  - 名字含"百度网盘"的目录下（%TEMP%\\百度网盘同步空间\\）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FAIL, PASS, UNMET, Report, http, service  # noqa: E402

NAME = "lbfx-云同步验收-案件"


def targets() -> list[tuple[str, Path]]:
    t = Path(tempfile.gettempdir())
    out = []
    od = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    od_path = Path(od) if od else Path(os.environ.get("USERPROFILE", "C:\\")) / "OneDrive"
    if od_path.exists():
        out.append(("OneDrive", od_path / NAME))
    out.append(("坚果云", t / "坚果云同步" / NAME))
    out.append(("百度网盘", t / "百度网盘同步空间" / NAME))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    r = Report("cloud_sync", "SEC-14；上线必过第 20 项", a.out)
    svc = service()
    if not svc:
        r.finish(UNMET, "工作台服务没有运行，或没有设置 LB_URL / LB_TOKEN")
    url, token = svc
    made: list[Path] = []
    wrong = []
    try:
        cases = targets() + [("普通目录（对照）", Path(tempfile.gettempdir()) / "lbfx-普通目录" / NAME)]
        for label, p in cases:
            if not p.exists():
                p.mkdir(parents=True)
                made.append(p)
            st, _, body = http("POST", url + "/api/case/open", {"path": str(p), "template": None},
                               {"Authorization": f"Bearer {token}"}, timeout=30)
            text = body.decode("utf-8", "replace")
            try:
                ok = bool(json.loads(text).get("ok"))
            except ValueError:
                ok = False
            r.log(f"  {label}：HTTP {st} ok={ok} {text[:120]}")
            if label.startswith("普通目录"):
                if not ok:
                    wrong.append("普通目录没能打开")
            elif ok:
                wrong.append(f"{label} 下的案件被打开了")
        if "OneDrive" not in [t[0] for t in targets()]:
            r.log("  注意：本机没有 OneDrive 目录，OneDrive 一项没有测")
    finally:
        for p in made:
            for q in [p, *p.parents]:
                if q.name.startswith("lbfx-") or q.name in ("坚果云同步", "百度网盘同步空间"):
                    try:
                        q.rmdir()   # 只删空文件夹
                    except OSError:
                        pass
    if wrong:
        r.finish(FAIL, "；".join(wrong))
    r.finish(PASS, "云同步目录下的案件都被拒绝，普通目录能打开")


if __name__ == "__main__":
    main()
