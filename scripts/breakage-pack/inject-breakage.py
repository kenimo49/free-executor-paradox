#!/usr/bin/env python3
"""
T1: Breakage Recovery — Deterministic Injection Script

Injects 25 errors across 15 files of typer (commit b210c0e):
- 10 type errors  (mypy detects)
- 10 lint errors  (ruff check detects)
- 5 test failures (pytest detects)

Each injection is rule-based and deterministic:
  same base commit + same script = same breakage state.

Usage:
    python inject-breakage.py               # apply breakage (assumes green base)
    python inject-breakage.py --verify      # verify base state is green (sha256 check)
    python inject-breakage.py --dry-run     # show what would be changed
    python inject-breakage.py --report      # print structured report of applied changes

Reset (after running):
    cd ../../base-repo/typer && git checkout -- .
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent / "base-repo" / "typer"
SRC = REPO_ROOT / "typer"


@dataclass
class Injection:
    """Single deterministic edit."""
    id: str
    category: str  # "type" | "lint" | "test"
    file: str
    description: str
    # Either (find/replace) for exact-match, or (prepend) for adding lines
    find: str | None = None
    replace: str | None = None
    prepend: str | None = None
    applied: bool = False
    error: str = ""


# ============================================================
# 25 deterministic injections
# ============================================================
# Designed to: (a) be detectable by harness, (b) be fixable from harness output,
# (c) span 15 files for cross-file orchestration evaluation.

INJECTIONS: list[Injection] = [
    # ---------- 型エラー 10件 (mypy) ----------
    Injection(
        id="TYPE-01", category="type", file="typer/__main__.py",
        description="戻り型 int だが str を返す helper を __main__ に追加",
        prepend='def _broken_typed_helper() -> int:\n    return "not an int"  # type-error injection T1\n\n\n',
    ),
    Injection(
        id="TYPE-02", category="type", file="typer/colors.py",
        description="型エラー: int annotation に str リテラルを代入する変数追加",
        prepend='BROKEN_INT_VAR: int = "not an int"  # type-error injection T1\n',
    ),
    Injection(
        id="TYPE-03", category="type", file="typer/_typing.py",
        description="戻り型 str だが int を返す helper を追加",
        prepend='def _broken_str_helper() -> str:\n    return 42  # type-error injection T1\n\n\n',
    ),
    Injection(
        id="TYPE-04", category="type", file="typer/_types.py",
        description="引数型 int だが str を渡す呼び出しを追加",
        prepend='def _broken_caller(x: int) -> int:\n    return _broken_caller("not int")  # type-error injection T1\n\n\n',
    ),
    Injection(
        id="TYPE-05", category="type", file="typer/completion.py",
        description="Optional[int] を int として扱う(None 不可) injection",
        prepend='def _broken_optional_to_int(x: int | None) -> int:\n    return x + 1  # type-error injection T1 (None + int)\n\n\n',
    ),
    Injection(
        id="TYPE-06", category="type", file="typer/utils.py",
        description="戻り型 list[int] だが list[str] を返す",
        prepend='def _broken_return_list() -> list[int]:\n    return ["a", "b", "c"]  # type-error injection T1\n\n\n',
    ),
    Injection(
        id="TYPE-07", category="type", file="typer/testing.py",
        description="dict[str, int] だが dict[str, str] を返す",
        prepend='def _broken_return_dict() -> dict[str, int]:\n    return {"k": "v"}  # type-error injection T1\n\n\n',
    ),
    Injection(
        id="TYPE-08", category="type", file="typer/models.py",
        description="bool annotation に str を代入",
        prepend='_BROKEN_BOOL: bool = "not bool"  # type-error injection T1\n\n\n',
    ),
    Injection(
        id="TYPE-09", category="type", file="typer/rich_utils.py",
        description="未定義属性アクセス(attr-defined)",
        prepend='class _BrokenAttr:\n    def go(self) -> int:\n        return self.nonexistent_attr  # type-error injection T1\n\n\n',
    ),
    Injection(
        id="TYPE-10", category="type", file="typer/main.py",
        description="関数 signature と呼び出しの型不一致",
        prepend='def _broken_typed_chain(n: int) -> int:\n    return _broken_typed_chain("not int")  # type-error injection T1\n\n\n',
    ),

    # ---------- lint エラー 10件 (ruff check) ----------
    Injection(
        id="LINT-01", category="lint", file="typer/__main__.py",
        description="未使用 import (F401)",
        prepend="import os  # noqa-disable for injection — actually F401\n",
    ),
    Injection(
        id="LINT-02", category="lint", file="typer/colors.py",
        description="未使用 import (F401)",
        prepend="import json  # F401 injection T1\n",
    ),
    Injection(
        id="LINT-03", category="lint", file="typer/_typing.py",
        description="未使用 import (F401)",
        prepend="import sys  # F401 injection T1\n",
    ),
    Injection(
        id="LINT-04", category="lint", file="typer/utils.py",
        description="未使用 import (F401)",
        prepend="import math  # F401 injection T1\n",
    ),
    Injection(
        id="LINT-05", category="lint", file="typer/_completion_classes.py",
        description="未使用変数 (F841)",
        prepend='def _broken_unused_var() -> None:\n    unused_local_xyz = 42  # F841 injection T1\n    return None\n\n\n',
    ),
    Injection(
        id="LINT-06", category="lint", file="typer/_completion_shared.py",
        description="未使用変数 (F841)",
        prepend='def _broken_unused_var_two() -> None:\n    another_unused = "abc"  # F841 injection T1\n    return None\n\n\n',
    ),
    Injection(
        id="LINT-07", category="lint", file="typer/models.py",
        description="未定義名 (F821)",
        prepend='def _broken_undefined() -> int:\n    return _undefined_name_xyz  # F821 injection T1\n\n\n',
    ),
    Injection(
        id="LINT-08", category="lint", file="typer/rich_utils.py",
        description="未定義名 (F821)",
        prepend='def _broken_undefined_two() -> int:\n    return _another_undefined_name  # F821 injection T1\n\n\n',
    ),
    Injection(
        id="LINT-09", category="lint", file="typer/testing.py",
        description="star import banned-api (F403 + flake8-tidy-imports)",
        prepend="from os.path import *  # F403 injection T1\n",
    ),
    Injection(
        id="LINT-10", category="lint", file="typer/params.py",
        description="未使用 import (F401)",
        prepend="import warnings as _broken_warnings  # F401 injection T1\n",
    ),

    # ---------- test failures 5件 (pytest) ----------
    # 既存 test が落ちるよう、ロジックを微改変する
    # test failures: prepend `assert False` to test files so pytest collection fails
    Injection(
        id="TEST-01", category="test", file="tests/test_ambiguous_params.py",
        description="test file 先頭に assert False を inject (collection失敗で test失敗)",
        prepend='assert False, "T1 TEST-01 injection — remove this line to recover"\n',
    ),
    Injection(
        id="TEST-02", category="test", file="tests/test_callback_warning.py",
        description="test file 先頭に assert False を inject",
        prepend='assert False, "T1 TEST-02 injection — remove this line to recover"\n',
    ),
    Injection(
        id="TEST-03", category="test", file="tests/test_exit_errors.py",
        description="test file 先頭に assert False を inject",
        prepend='assert False, "T1 TEST-03 injection — remove this line to recover"\n',
    ),
    Injection(
        id="TEST-04", category="test", file="tests/test_annotated.py",
        description="test file 先頭に assert False を inject",
        prepend='assert False, "T1 TEST-04 injection — remove this line to recover"\n',
    ),
    Injection(
        id="TEST-05", category="test", file="tests/test_deprecation.py",
        description="test file 先頭に assert False を inject",
        prepend='assert False, "T1 TEST-05 injection — remove this line to recover"\n',
    ),
]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def apply_injection(inj: Injection, dry_run: bool = False) -> None:
    target = REPO_ROOT / inj.file
    if not target.exists():
        inj.error = f"file not found: {target}"
        return

    content = target.read_text()

    if inj.find is not None and inj.replace is not None:
        if inj.find not in content:
            inj.error = f"find string not present in {inj.file}"
            return
        if content.count(inj.find) > 1:
            inj.error = f"find string ambiguous (multiple matches) in {inj.file}"
            return
        new_content = content.replace(inj.find, inj.replace, 1)
    elif inj.prepend is not None:
        # Insert AFTER the last top-level import (both source and test files).
        # For test files this still triggers a collection error (assert False runs during
        # module load), but avoids E402 (module-level import not at top) cascading.
        if False:
            pass
        else:
            # Use AST to find the END line of the last top-level Import/ImportFrom node.
            # This correctly handles multi-line `from x import (\n  A,\n  B,\n)` blocks
            # and skips imports nested inside functions/classes.
            import ast

            lines = content.split("\n")
            try:
                tree = ast.parse(content)
            except SyntaxError:
                inj.error = f"file already has SyntaxError; cannot AST-parse {inj.file}"
                return

            last_import_end_lineno = 0
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    end = getattr(node, "end_lineno", node.lineno)
                    if end and end > last_import_end_lineno:
                        last_import_end_lineno = end

            if last_import_end_lineno == 0:
                new_content = inj.prepend + content
            else:
                # insert AFTER the last import line (end_lineno is 1-indexed; list index = end_lineno)
                prepend_block = "\n" + inj.prepend.rstrip("\n")
                lines.insert(last_import_end_lineno, prepend_block)
                new_content = "\n".join(lines)
    else:
        inj.error = "no find/replace or prepend defined"
        return

    if not dry_run:
        target.write_text(new_content)
    inj.applied = True


def verify_base_state() -> bool:
    """Check that the repo is at the expected base commit (no prior injection)."""
    import subprocess
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    head = result.stdout.strip()
    # b210c0e is the expected base
    if not head.startswith("b210c0e"):
        print(f"WARN: HEAD is {head}, expected b210c0e", file=sys.stderr)
    # Check no uncommitted changes
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    dirty = result.stdout.strip()
    if dirty:
        print(f"ERROR: working tree dirty — please reset first:\n{dirty}", file=sys.stderr)
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="only check base state is clean")
    parser.add_argument("--dry-run", action="store_true", help="show what would change")
    parser.add_argument("--report", action="store_true", help="emit JSON report after apply")
    parser.add_argument("--skip-verify", action="store_true", help="skip dirty-tree check")
    args = parser.parse_args()

    if not args.skip_verify and not verify_base_state():
        return 2

    if args.verify:
        print("base state OK")
        return 0

    for inj in INJECTIONS:
        apply_injection(inj, dry_run=args.dry_run)

    failed = [inj for inj in INJECTIONS if not inj.applied]
    succeeded = [inj for inj in INJECTIONS if inj.applied]

    if args.report:
        report = {
            "total": len(INJECTIONS),
            "applied": len(succeeded),
            "failed": len(failed),
            "by_category": {
                cat: sum(1 for i in succeeded if i.category == cat)
                for cat in ["type", "lint", "test"]
            },
            "injections": [asdict(i) for i in INJECTIONS],
        }
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"applied {len(succeeded)}/{len(INJECTIONS)} injections")
        for inj in failed:
            print(f"  FAILED {inj.id} ({inj.file}): {inj.error}")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
