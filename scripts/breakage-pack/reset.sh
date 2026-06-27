#!/usr/bin/env bash
# Reset typer base-repo to clean state (revert any injection).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$SCRIPT_DIR/../../base-repo/typer"
cd "$REPO"
git checkout -- .
git clean -fd typer/ tests/ 2>/dev/null || true
# qwen-task agent mode leaves .claw/sessions; not part of typer
rm -rf .claw .pytest_cache .mypy_cache .ruff_cache __pycache__ 2>/dev/null || true
echo "reset OK: typer at $(git rev-parse --short HEAD)"
