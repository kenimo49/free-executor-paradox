#!/usr/bin/env bash
# verify-T2.sh — T2 refactor の完了判定
# 使い方:
#   verify-T2.sh                # human + JSON
#   verify-T2.sh --json-only    # JSON のみ (runner consumption 用)

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$SCRIPT_DIR/../../base-repo/typer"
EXP_ROOT="$SCRIPT_DIR/.."

JSON_ONLY=0
for arg in "$@"; do
  [ "$arg" = "--json-only" ] && JSON_ONLY=1
done

cd "$REPO"

# harness 経由で mypy + ruff + pytest を1回叩く
harness_json=$("$EXP_ROOT/harness.sh" --json-only)
harness_exit=$?

# T2-specific checks
new_file_exists=0
[ -f "typer/_param_extractor.py" ] && new_file_exists=1

trim_int() { tr -dc '0-9'; }
new_def_count=$(grep -cE '^def get_params_from_function' typer/_param_extractor.py 2>/dev/null | trim_int)
new_def_count=${new_def_count:-0}
old_def_count=$(grep -cE '^def get_params_from_function' typer/utils.py 2>/dev/null | trim_int)
old_def_count=${old_def_count:-0}

old_import_count=$(grep -rE 'from \.utils import[^#]*get_params_from_function|from typer\.utils import[^#]*get_params_from_function' typer/ tests/ 2>/dev/null | wc -l | trim_int)
old_import_count=${old_import_count:-0}
new_import_count=$(grep -rE 'from \._param_extractor import[^#]*get_params_from_function|from typer\._param_extractor import[^#]*get_params_from_function' typer/ tests/ 2>/dev/null | wc -l | trim_int)
new_import_count=${new_import_count:-0}

# T2 完了条件
t2_pass=0
if [ "$harness_exit" -eq 0 ] && \
   [ "$new_file_exists" -eq 1 ] && \
   [ "$new_def_count" -ge 1 ] && \
   [ "$old_def_count" -eq 0 ] && \
   [ "$old_import_count" -eq 0 ] && \
   [ "$new_import_count" -ge 1 ]; then
  t2_pass=1
fi

# overall exit: 0 if t2 pass else 1
overall_exit=$([ "$t2_pass" -eq 1 ] && echo 0 || echo 1)

json=$(cat <<EOF
{
  "task": "T2-refactor",
  "exit_code": $overall_exit,
  "harness_exit": $harness_exit,
  "harness": $harness_json,
  "t2_checks": {
    "new_file_exists": $new_file_exists,
    "new_def_count": $new_def_count,
    "old_def_count": $old_def_count,
    "old_import_count": $old_import_count,
    "new_import_count": $new_import_count,
    "all_pass": $t2_pass
  }
}
EOF
)

if [ "$JSON_ONLY" -eq 1 ]; then
  printf '%s\n' "$json"
else
  echo "==== T2 verification ===="
  printf '%s\n' "$json"
fi

exit $overall_exit
