"""SEC-05（上线必过第 2 项）：案件 A 读不到案件 B 和其他文件——通过工具调用构造越权参数。

前提：工作台服务在运行（环境变量 LB_URL、LB_TOKEN），并且已按 acceptance\\manual\\案件隔离.md 准备好：
  - 案件 A = tests\\fixtures\\attack-01 的副本（含 外部目录链接 联接、外部文件链接.txt 符号链接）；
  - 案件 B = tests\\fixtures\\civil-01 的副本；
  - 在案件 A 的会话里发起过一次对话，拿到它的 task_id，放进环境变量 LB_TASK_A。
然后本脚本以案件 A 的 task_id 调 POST /core/tool，用各种越权参数调用 case_read_material、case_search、
case_read_input、case_read_wiki：返回里出现案件 B 的特征字符串或 win.ini 的内容，即不通过。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import FAIL, FEATURES, PASS, UNMET, Report, env_local, http, service  # noqa: E402

B_FEAT = FEATURES["civil-01"]
WININI = ("[fonts]", "[extensions]", "[mci extensions]", "for 16-bit app support")

NAMES = [
    "../civil-01/情况说明", "..\\civil-01\\情况说明", "../../civil-01/情况说明.txt",
    "C:\\Windows\\win.ini", "C:/Windows/win.ini", "\\\\?\\C:\\Windows\\win.ini", "/etc/passwd",
    "外部目录链接/情况说明", "外部目录链接/情况说明.txt", "外部文件链接", "外部文件链接.txt",
    "外部目录链接\\..\\..\\civil-01\\借条", "情况说明", "借条", "银行流水",      # B 的材料名
    "%2e%2e/civil-01/情况说明", "....//civil-01//情况说明", "AGENTS.md", ".dsh/skills/evil/SKILL",
    "CON", "a" * 300,
]


def calls():
    for n in NAMES:
        yield "case_read_material", {"name": n}
        yield "case_read_material", {"name": n, "start": 1, "max_chars": 2000}
    for q in (B_FEAT, "李某乙", "fonts"):
        yield "case_search", {"query": q}
    for i in (-1, 0, 999999):
        yield "case_read_input", {"index": i}
    for n in ("../../civil-01/借条", "C:\\Windows\\win.ini", "借条"):
        yield "case_read_wiki", {"section": "材料摘要", "name": n}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    r = Report("case_isolation", "SEC-05；上线必过第 2 项", a.out)
    svc = service()
    task = env_local().get("LB_TASK_A")
    if not svc:
        r.finish(UNMET, "工作台服务没有运行，或没有设置 LB_URL / LB_TOKEN（T3 之后按 manual\\案件隔离.md 准备）")
    if not task:
        r.finish(UNMET, "没有案件 A 会话的 task_id（环境变量 LB_TASK_A）")
    url, token = svc
    leaks, n = [], 0
    for tool, args in calls():
        st, _, body = http("POST", url + "/core/tool", {"task_id": task, "tool": tool, "args": args},
                           {"Authorization": f"Bearer {token}"}, timeout=30)
        n += 1
        text = body.decode("utf-8", "replace")
        ok = False
        try:
            ok = bool(json.loads(text).get("ok"))
        except ValueError:
            pass
        leak = B_FEAT in text or any(m in text for m in WININI)
        r.log(f"  {tool} {json.dumps(args, ensure_ascii=False)[:80]} → HTTP {st} ok={ok}{'  ← 泄露' if leak else ''}")
        if leak:
            leaks.append(f"{tool} {args}")
    r.log(f"共 {n} 次越权调用")
    if leaks:
        r.finish(FAIL, f"{len(leaks)} 次调用读到了案件 B 或系统文件的内容")
    r.finish(PASS, "所有越权调用都没有读到案件 B 或案件外文件的内容")


if __name__ == "__main__":
    main()
