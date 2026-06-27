#!/usr/bin/env bash
# inject-T3.sh — T3 用テストファイルを tests/ に配置
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$SCRIPT_DIR/../../base-repo/typer"

cat > "$REPO/tests/test_t3_feature.py" <<'EOF'
"""T3 feature test — provided by experiment, do not modify."""
import sys

import typer


def test_get_version_banner_default() -> None:
    result = typer.get_version_banner()
    assert result.startswith("Typer v")
    assert "Python" in result
    assert str(sys.version_info.major) in result
    assert str(sys.version_info.minor) in result


def test_get_version_banner_prefix() -> None:
    result = typer.get_version_banner(prefix="MyTool")
    assert result.startswith("MyTool v")


def test_get_version_banner_uppercase() -> None:
    result = typer.get_version_banner(uppercase=True)
    assert result == result.upper()
    assert "TYPER" in result
EOF

# Save SHA256 to detect unauthorized modification
sha256sum "$REPO/tests/test_t3_feature.py" > "$SCRIPT_DIR/.t3-test-sha256"
echo "T3 test file injected at tests/test_t3_feature.py"
echo "sha256 recorded in breakage-pack/.t3-test-sha256"
