#!/usr/bin/env bash
# sequential T18 runs; each: UI run, then budget table for that case
cd /d/lawbench-T18
PY=/d/lawbench-B/service/.venv/Scripts/python.exe
OUT=/d/lawbench-B/docs/plan/evidence/T18/budget
mkdir -p $OUT
while read -r skill cap; do
  [ -z "$skill" ] && continue
  [ -f runs/$skill.json ] && continue
  echo "=== $skill $(date +%H:%M:%S)"
  node run_skill.mjs $skill $cap "D:/lawbench-T18/cases/$skill" tasks/$skill.txt 2>runs/$skill.log
  (cd /d/lawbench-B/service && $PY tools/t18_budget.py --case "D:/lawbench-T18/cases/$skill" --logs 'D:\lawbench-devhome-T18\Local\lawbench\logs' --out "D:\lawbench-T18\budget-tmp" > /dev/null 2>&1)
  f=$(ls -t budget-tmp/budget-*.json 2>/dev/null | head -1); [ -n "$f" ] && mv "$f" $OUT/budget-$skill.json && mv "${f%.json}.md" $OUT/budget-$skill.md
done <<'LIST'
contract-review contract-review
contract-draft contract-draft
litigation-docs litigation-docs
criminal-evidence-review case-analysis
sentence-calc sentence-calc
criminal-applications bail-application
defense-opinion defense-opinion
cross-exam-opinion cross-exam
general-drafting lawyer-letter
tender-review bidding
bid-drafting bidding
case-archiving archiving
case-reading-notes general-docs
pre-issue-check litigation-docs
doc-revise litigation-docs
legal-workflow defense-opinion
LIST
echo ALLDONE $(date +%H:%M:%S)
