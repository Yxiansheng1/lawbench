"""Spec 3.3 数据落点（SEC-01、SEC-11；上线必过第 21 项"软件自己的附件目录为空"）。

python acceptance\\sec\\dsh_locations.py [--dsh-home <目录>]
在用测试案卷完整走一遍（含拖入导入、粘贴图片、对话）之后运行：
- 附件目录（$DSH_HOME 下名为 attachments 的目录）为空；
- $DSH_HOME\\sessions 下没有会话记录（会话应按案件存到 <案件>\\工作区\\会话\\）；
- $DSH_HOME\\.credentials.yaml 不存在，或不含 Key（Key 在 Windows 凭据管理器，Spec 8.1）；
- 系统临时目录里没有工具输出的溢出文件（名字含 spill）。
$DSH_HOME 缺省取环境变量 DSH_HOME，没有时取 %USERPROFILE%\\.dsh。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FAIL, PASS, UNMET, Report  # noqa: E402

KEYISH = re.compile(r"(LAWFIRM_KEY|api[_-]?key|sk-[A-Za-z0-9]{8,})", re.I)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsh-home", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    r = Report("dsh_locations", "Spec 3.3；SEC-01、SEC-11；上线必过第 21 项", a.out)
    home = a.dsh_home or Path(os.environ.get("DSH_HOME") or Path(os.environ.get("USERPROFILE", "~")) / ".dsh")
    if not home.exists():
        r.finish(UNMET, f"找不到 DSH 数据目录 {home}（客户端装好并用测试案卷走一遍后再测，T17 之后）")
    bad = []
    att = [p for p in home.rglob("*") if p.is_dir() and p.name.lower() in ("attachments", "attachment")]
    for d in att:
        files = [p for p in d.rglob("*") if p.is_file()]
        r.log(f"附件目录 {d}：{len(files)} 个文件")
        if files:
            bad.append(f"附件目录不为空（{len(files)} 个文件）")
    if not att:
        r.log("没有找到附件目录（未创建，视为空）")
    sess = home / "sessions"
    n = len([p for p in sess.rglob("*") if p.is_file()]) if sess.exists() else 0
    r.log(f"{sess}：{n} 个文件")
    if n:
        bad.append(f"$DSH_HOME\\sessions 下有 {n} 个会话文件")
    cred = home / ".credentials.yaml"
    if cred.exists():
        hit = bool(KEYISH.search(cred.read_text(encoding="utf-8", errors="replace")))
        r.log(f"{cred}：存在，{'含疑似 Key 的内容' if hit else '不含 Key'}")
        if hit:
            bad.append(".credentials.yaml 含 Key")
    else:
        r.log(f"{cred}：不存在")
    spill = [p for p in Path(tempfile.gettempdir()).rglob("*spill*")]
    r.log(f"临时目录中名字含 spill 的项：{len(spill)} 个")
    if spill:
        bad.append(f"临时目录有 {len(spill)} 个溢出文件")
    if bad:
        r.finish(FAIL, "；".join(bad))
    r.finish(PASS, "附件目录为空，会话不在 $DSH_HOME，凭据文件不含 Key，没有溢出文件")


if __name__ == "__main__":
    main()
