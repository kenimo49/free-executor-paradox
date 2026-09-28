#!/usr/bin/env bash
# claude -p replication: arms x tasks x trials, interleaved so that time-of-day drift hits every arm.
# Skips (arm, task, trial) already present in data/results-claude-p/{arm}.jsonl. Fail-tolerant.
set -u
cd "$(dirname "$0")/.."
OUT=../data/results-claude-p
for trial in 0 1 2; do
  for task in T3 T2 T1; do
    for arm in A B Bs Bt; do
      if [ -f "$OUT/$arm.jsonl" ] && python3 -c "
import json,sys
sys.exit(0 if any(r['task']=='$task' and r['trial']==$trial for r in map(json.loads,open('$OUT/$arm.jsonl'))) else 1)"; then
        continue
      fi
      echo "=== $(date +%H:%M) $arm $task $trial"
      timeout 6000 python3 -m claude_p.runner --arm "$arm" --task "$task" --trial "$trial" || echo "  (fail or timeout)"
    done
  done
done
echo "=== all done $(date +%H:%M)"
