#!/usr/bin/env bash
# batch.sh — sequential trial runner. Idempotent: skips cells that already have
# enough successful trials. Tolerant of individual trial failures.
#
# Usage:
#   ./runners/batch.sh all           # target n=3 success/cell across all (arm,task)
#   ./runners/batch.sh all 5         # target n=5 success/cell
#   ./runners/batch.sh status        # print current per-cell coverage
#
# Per-arm default max_iters (override per (arm,task) via case below):
#   A=40, B=60, C=40, D=80
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

TARGET="${2:-3}"

# Per-cell maximum trial id we will reach (TARGET successes + extra retries headroom)
HARD_CAP=6

# Per-cell override of max_iters, keyed "arm-task"
maxiters_for() {
  case "$1" in
    B-T1) echo 80 ;;
    D-T1) echo 100 ;;
    D-T2) echo 120 ;;
    *)    echo "" ;;
  esac
}

# count successes in ../data/results/{arm}.jsonl for given task
count_success() {
  local arm=$1 task=$2
  local f="../data/results/$arm.jsonl"
  [ -f "$f" ] || { echo 0; return; }
  python3 -c "
import json,sys
with open('$f') as fh:
    n=sum(1 for l in fh if l.strip() and (j:=json.loads(l)).get('task')=='$task' and j.get('success'))
print(n)
" 2>/dev/null || echo 0
}

next_trial_id() {
  local arm=$1 task=$2
  local f="../data/results/$arm.jsonl"
  [ -f "$f" ] || { echo 0; return; }
  python3 -c "
import json
ids=[]
with open('$f') as fh:
    for l in fh:
        if not l.strip(): continue
        j=json.loads(l)
        if j.get('task')=='$task': ids.append(j.get('trial',0))
print(max(ids)+1 if ids else 0)
" 2>/dev/null || echo 0
}

run_one() {
  local arm=$1 task=$2 trial=$3
  local mi
  mi=$(maxiters_for "$arm-$task")
  local extra=""
  [ -n "$mi" ] && extra="--max-iters $mi"
  echo "[$(date +%H:%M:%S)] arm=$arm task=$task trial=$trial $extra"
  set +e
  python3 -m runners.runner --arm "$arm" --task "$task" --trial "$trial" $extra 2>&1 | tail -2
  local rc=${PIPESTATUS[0]}
  set -e
  echo "[$(date +%H:%M:%S)] exit=$rc"
  return 0  # always continue
}

cmd="${1:-}"

if [ "$cmd" = "status" ]; then
  printf "%-4s %-6s %-12s %-10s\n" "arm" "task" "successes" "next_trial"
  for arm in A B C D; do
    for task in T1 T2 T3; do
      printf "%-4s %-6s %-12s %-10s\n" "$arm" "$task" "$(count_success $arm $task)" "$(next_trial_id $arm $task)"
    done
  done
  exit 0
fi

if [ "$cmd" = "all" ]; then
  # Order: fast/cheap first so we get quick feedback
  for arm in A C B D; do
    for task in T3 T2 T1; do
      while true; do
        s=$(count_success $arm $task)
        if [ "$s" -ge "$TARGET" ]; then
          echo "[$(date +%H:%M:%S)] arm=$arm task=$task done (success=$s ≥ $TARGET)"
          break
        fi
        nid=$(next_trial_id $arm $task)
        if [ "$nid" -ge "$HARD_CAP" ]; then
          echo "[$(date +%H:%M:%S)] arm=$arm task=$task HARD_CAP=$HARD_CAP reached (success=$s)"
          break
        fi
        run_one "$arm" "$task" "$nid"
      done
    done
  done
  echo "[$(date +%H:%M:%S)] batch done."
  exit 0
fi

echo "usage: $0 [all [target_n]|status]"
exit 1
