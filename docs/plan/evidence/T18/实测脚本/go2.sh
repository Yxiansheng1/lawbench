#!/usr/bin/env bash
cd /d/lawbench-T18
OUT=/d/lawbench-B/docs/plan/evidence/T18/budget
while read -r skill cap; do
  echo "=== $skill $(date +%H:%M:%S)"
  node run_skill.mjs $skill $cap "D:/lawbench-T18/cases/$skill-2" tasks/$skill.txt 2>runs/$skill.log
  (cd /d/lawbench-B/service && .venv/Scripts/python.exe tools/t18_budget.py --case "D:/lawbench-T18/cases/$skill-2" --logs 'D:\lawbench-devhome-T18\Local\lawbench\logs' --out 'D:\lawbench-T18\budget-tmp' > /dev/null 2>&1)
  f=$(ls -t budget-tmp/budget-*.json | head -1); mv "$f" $OUT/budget-$skill.json && mv "${f%.json}.md" $OUT/budget-$skill.md
done <<'LIST'
contract-draft contract-draft
cross-exam-opinion cross-exam
tender-review bidding
case-archiving archiving
LIST
echo ALLDONE $(date +%H:%M:%S)
