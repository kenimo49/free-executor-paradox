#!/usr/bin/env bash
# harness.sh — typer base-repo で mypy + ruff + pytest を順に叩き、結果を JSON で吐く
#
# 使い方:
#   ./harness.sh                  # human readable + JSON 両方出力
#   ./harness.sh --json-only      # JSON のみ (runner consumption 用)
#   ./harness.sh --fast           # pytest を --no-cov, -x で速度優先(default)
#   ./harness.sh --full           # pytest with coverage (slow)
#
# 終了コード:
#   0  全 green
#   1  何らかの harness fail
#   2  harness 実行自体が中断 (env error)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$SCRIPT_DIR/../base-repo/typer"

if [ ! -d "$REPO_DIR" ]; then
  echo '{"error":"base-repo/typer not found","exit_code":2}' >&2
  exit 2
fi

JSON_ONLY=0
MODE=fast
for arg in "$@"; do
  case "$arg" in
    --json-only) JSON_ONLY=1 ;;
    --fast)      MODE=fast ;;
    --full)      MODE=full ;;
  esac
done

cd "$REPO_DIR"

export TERMINAL_WIDTH=3000
export _TYPER_FORCE_DISABLE_TERMINAL=1
export _TYPER_RUN_INSTALL_COMPLETION_TESTS=0

t0=$(date +%s)

# --- mypy ---
mypy_out=$(uv run mypy typer 2>&1)
mypy_exit=$?
mypy_errors=$(printf '%s\n' "$mypy_out" | grep -cE '^.+:[0-9]+: error:' || true)

# --- ruff check ---
ruff_check_out=$(uv run ruff check typer tests docs_src scripts 2>&1)
ruff_check_exit=$?
ruff_check_errors=$(printf '%s\n' "$ruff_check_out" | grep -oE 'Found [0-9]+ error' | head -1 | grep -oE '[0-9]+' || true)
ruff_check_errors=${ruff_check_errors:-0}

# --- ruff format (informational only — not included in overall pass/fail) ---
ruff_fmt_out=$(uv run ruff format typer tests docs_src scripts --check 2>&1)
ruff_fmt_exit=$?
ruff_fmt_errors=$(printf '%s\n' "$ruff_fmt_out" | grep -cE 'Would reformat' || true)

# --- pytest ---
if [ "$MODE" = "fast" ]; then
  pytest_out=$(uv run pytest -q --no-cov --numprocesses=auto 2>&1)
else
  pytest_out=$(uv run pytest --cov --no-header -q --numprocesses=auto 2>&1)
fi
pytest_exit=$?
pytest_failed=$(printf '%s\n' "$pytest_out" | grep -oE '[0-9]+ failed' | head -1 | grep -oE '[0-9]+' || true)
pytest_passed=$(printf '%s\n' "$pytest_out" | grep -oE '[0-9]+ passed' | head -1 | grep -oE '[0-9]+' || true)
pytest_collection_errors=$(printf '%s\n' "$pytest_out" | grep -oE '[0-9]+ errors?( during collection| in [0-9])' | head -1 | grep -oE '^[0-9]+' || true)
pytest_failed=${pytest_failed:-0}
pytest_passed=${pytest_passed:-0}
pytest_collection_errors=${pytest_collection_errors:-0}

t1=$(date +%s)
elapsed=$((t1 - t0))

# overall (ruff_format is informational only; not part of pass/fail)
overall_exit=0
if [ "$mypy_exit" -ne 0 ] || [ "$ruff_check_exit" -ne 0 ] || [ "$pytest_exit" -ne 0 ]; then
  overall_exit=1
fi

# JSON output
json=$(cat <<EOF
{
  "exit_code": $overall_exit,
  "elapsed_sec": $elapsed,
  "mypy": {"exit": $mypy_exit, "errors": $mypy_errors},
  "ruff_check": {"exit": $ruff_check_exit, "errors": $ruff_check_errors},
  "ruff_format": {"exit": $ruff_fmt_exit, "errors": $ruff_fmt_errors, "informational": true},
  "pytest": {"exit": $pytest_exit, "failed": $pytest_failed, "passed": $pytest_passed, "collection_errors": $pytest_collection_errors}
}
EOF
)

if [ "$JSON_ONLY" -eq 1 ]; then
  printf '%s\n' "$json"
else
  echo "==== mypy ===="
  printf '%s\n' "$mypy_out" | tail -20
  echo "==== ruff check ===="
  printf '%s\n' "$ruff_check_out" | tail -10
  echo "==== ruff format ===="
  printf '%s\n' "$ruff_fmt_out" | tail -5
  echo "==== pytest ===="
  printf '%s\n' "$pytest_out" | tail -15
  echo "==== summary ===="
  printf '%s\n' "$json"
fi

exit $overall_exit
