"""T18 实测汇总：runs/*.json + 各案件 result.json + budget-*.json → 18 行表（Markdown）与 JSON。只读元数据与计数。"""
import glob
import json
import pathlib
import re
import sys
from collections import Counter

T = pathlib.Path(r"D:\lawbench-T18")
EV = pathlib.Path(r"D:\lawbench-B\docs\plan\evidence\T18")
SKILLS = pathlib.Path(r"D:\lawbench-B\skills")
ORDER = ["criminal-reading-notes", "criminal-evidence-review", "cross-exam-opinion", "defense-opinion",
         "criminal-applications", "sentence-calc", "case-wiki-build", "legal-workflow", "contract-review",
         "contract-draft", "doc-revise", "pre-issue-check", "case-reading-notes", "general-drafting",
         "litigation-docs", "tender-review", "bid-drafting", "case-archiving"]


def case_dir(skill):
    two = T / "cases" / f"{skill}-2"
    return two if two.is_dir() else T / "cases" / skill


def main():
    rows, data = [], []
    for i, skill in enumerate(ORDER, 1):
        run = {}
        if (T / "runs" / f"{skill}.json").is_file():
            run = json.loads((T / "runs" / f"{skill}.json").read_text(encoding="utf-8"))
        b = {}
        bj = EV / "budget" / f"budget-{skill}.json"
        if bj.is_file():
            rs = json.loads(bj.read_text(encoding="utf-8"))["rows"]
            want = run.get("task_id")
            b = next((r for r in rs if r["task_id"] == want), None) or (rs[-1] if rs else {})
        res = {}
        if b.get("task_id"):
            p = case_dir(skill) / "工作区" / "任务" / b["task_id"] / "result.json"
            if p.is_file():
                res = json.loads(p.read_text(encoding="utf-8"))
        cc = res.get("citation_check") or {}
        cls = Counter(f"{x['class']}{'!' if x['severity'] == 'must_fix' else ''}" for x in cc.get("problems", []))
        cite = "—"
        if cc:
            st = cc.get("stats", {})
            ae = "、".join(f"{k.rstrip('!')}{'必改' if k.endswith('!') else '提示'}×{n}" for k, n in sorted(cls.items()))
            cite = f"{st.get('citations', 0)} 处；必改 {st.get('must_fix', 0)}" + (f"（{ae}）" if ae else "")
        m = b.get("measured") or {}
        bud = b.get("budget") or {}
        drafts = [d["path"].split("/")[-1] for d in res.get("drafts", [])]
        status = b.get("status") or run.get("status")
        q = "；".join(a for a in run.get("answers", [])) or ("未问" if m.get("tools", {}).get("ask_user_question") is None else "问了（见记录）")
        rows.append(f"| {i} | {skill} | {status} | {m.get('model_calls', '—')} / {bud.get('model_calls', '—')} | "
                    f"{m.get('tool_calls', '—')} / {bud.get('tool_calls', '—')} | {b.get('minutes', '—')} | "
                    f"{'是' if status == 'budget_stopped' else '否'} | {len(drafts)} | {cite} |")
        data.append({"skill": skill, "task_id": b.get("task_id"), "status": status, "measured": m, "budget": bud,
                     "minutes": b.get("minutes"), "drafts": drafts, "citation_check": {"stats": cc.get("stats"),
                     "classes": dict(cls)}, "answers": run.get("answers", []), "wall_s": run.get("wall_s")})
    print("| # | Skill | 状态 | 模型 实测 / 上限 | 工具 实测 / 上限 | 分钟 | 触发预算 | 草稿版本数 | 出处核对（A–G，! 为必改） |")
    print("|---|---|---|---|---|---|---|---|---|")
    print("\n".join(rows))
    (T / "aggregate.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
