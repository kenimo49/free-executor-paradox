#!/usr/bin/env bash
# verify-T3.sh — T3 feature-add の完了判定
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$SCRIPT_DIR/../../base-repo/typer"
EXP_ROOT="$SCRIPT_DIR/.."

JSON_ONLY=0
for arg in "$@"; do
  [ "$arg" = "--json-only" ] && JSON_ONLY=1
done

cd "$REPO"

trim_int() { tr -dc '0-9'; }

# harness
harness_json=$("$EXP_ROOT/harness.sh" --json-only)
harness_exit=$?

# T3-specific checks
def_count=$(grep -rcE '^def get_version_banner' typer/ 2>/dev/null | grep -v ':0$' | wc -l | trim_int)
def_count=${def_count:-0}

# Re-export check: try Python import
api_callable=0
if uv run python -c "import typer; assert callable(typer.get_version_banner)" 2>/dev/null; then
  api_callable=1
fi

# Test file integrity check
test_file_intact=0
if [ -f "$SCRIPT_DIR/.t3-test-sha256" ]; then
  if (cd "$REPO" && sha256sum -c "$SCRIPT_DIR/.t3-test-sha256" >/dev/null 2>&1); then
    test_file_intact=1
  fi
fi

# Run just the T3 test
t3_test_pass=0
if uv run pytest tests/test_t3_feature.py -q --no-cov >/dev/null 2>&1; then
  t3_test_pass=1
fi

# T3 完了条件
t3_pass=0
if [ "$harness_exit" -eq 0 ] && \
   [ "$def_count" -ge 1 ] && \
   [ "$api_callable" -eq 1 ] && \
   [ "$test_file_intact" -eq 1 ] && \
   [ "$t3_test_pass" -eq 1 ]; then
  t3_pass=1
fi

overall_exit=$([ "$t3_pass" -eq 1 ] && echo 0 || echo 1)

json=$(cat <<EOF
{
  "task": "T3-feature-add",
  "exit_code": $overall_exit,
  "harness_exit": $harness_exit,
  "harness": $harness_json,
  "t3_checks": {
    "def_count": $def_count,
    "api_callable": $api_callable,
    "test_file_intact": $test_file_intact,
    "t3_test_pass": $t3_test_pass,
    "all_pass": $t3_pass
  }
}
EOF
)

if [ "$JSON_ONLY" -eq 1 ]; then
  printf '%s\n' "$json"
else
  echo "==== T3 verification ===="
  printf '%s\n' "$json"
fi

exit $overall_exit
