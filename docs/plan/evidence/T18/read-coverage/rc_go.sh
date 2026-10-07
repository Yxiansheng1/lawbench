#!/usr/bin/env bash
cd /d/lawbench-T18
for c in rc-allscan; do
  echo "=== $c $(date +%H:%M:%S)"
  node run_skill.mjs criminal-reading-notes case-analysis D:/lawbench-T18/cases/$c tasks/rc.txt 2>runs/$c.log
  mv runs/criminal-reading-notes.json runs/$c.json
done
echo ALLDONE $(date +%H:%M:%S)
