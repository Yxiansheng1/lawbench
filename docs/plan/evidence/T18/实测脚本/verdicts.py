import sys
sys.stdout.reconfigure(encoding="utf-8")
V = {
    "criminal-reading-notes": "✔ 展示「全部 4 份」请确认，没再问",
    "criminal-evidence-review": "✔ 展示「辩护方」请确认",
    "cross-exam-opinion": "✔ 范围、发问提纲合成一题请确认",
    "defense-opinion": "问了 1 次（第一版答题脚本未记下题面）",
    "criminal-applications": "问受理机关（样本没写必问口径；材料里的办案机关作推荐项）",
    "sentence-calc": "问了 1 次（题面未记下）；没出草稿",
    "case-wiki-build": "✔ 流水线不提问",
    "legal-workflow": "未问；对话里直接给出导航（2 次调用完成）",
    "contract-review": "✗ 关注点（focus）没给，应提问，实际没问",
    "contract-draft": "✔ 未谈拢的付款、质保等列为选择题请确认（4 题）",
    "doc-revise": "未问（样本无必问口径）",
    "pre-issue-check": "未问（样本无必问口径）",
    "case-reading-notes": "✗ 应列出 5 份材料请确认范围，实际没问",
    "general-drafting": "未问（样本无必问口径）",
    "litigation-docs": "✗ 法院没给，应提问，实际没问；落款写了【待补充：法院全称】，没有推断",
    "tender-review": "✔ 身份、重点都展示请确认（2 题）",
    "bid-drafting": "✗ 投标人全称应带出处请确认，实际没问；也没出草稿",
    "case-archiving": "✔ 已给的（金助理编号、卷类）请确认；办案结果、律师费是否收齐提问（3 题）",
}
rows = open(sys.argv[1], encoding="utf-8").read().splitlines()
out = [rows[0].rstrip() + " 必问问题（已有的请确认、缺的才问） |", rows[1].rstrip() + "---|"]
for r in rows[2:]:
    out.append(r.rstrip() + f" {V[r.split('|')[2].strip()]} |")
print("\n".join(out))
