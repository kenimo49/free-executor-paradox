"""Task descriptions handed to the agent at the start of a trial.

Kept terse: a few hundred tokens each, intentionally not over-spelling out the fix
(the agent has to read code + harness output). Identical across arms so model-side
fairness is preserved.
"""

T1 = """\
Task T1: breakage recovery.

You are working inside the typer repository (your cwd is the typer repo root).
25 errors have been injected across 15 source/test files: mypy type errors,
ruff lint errors, and pytest collection-time failures.

Goal: return the repository to fully green. The harness lives one level up at
`../../scripts/harness.sh`; run it as `../../scripts/harness.sh --json-only`. Success is
exit_code=0 with mypy.errors=0, ruff_check.errors=0, pytest.failed=0,
pytest.collection_errors=0. (ruff_format is informational only — ignore it.)

Constraints:
- Only edit files under `typer/` and `tests/`. Do not touch the harness,
  conftest, pyproject, or anything outside those two directories.
- Do not delete tests to make them pass.
- Do not add `# type: ignore` or `# noqa` to silence errors; fix the underlying issue.
- Removed-but-still-imported names should be re-added or the import removed,
  whichever matches the original behaviour. Run the harness frequently to gauge progress.

Start by running the harness, reading the errors, and fixing them iteratively.
"""

T2 = """\
Task T2: refactor.

You are working inside the typer repository (your cwd is the typer repo root).
Move the function `get_params_from_function` out of `typer/utils.py` into a new
module `typer/_param_extractor.py`. Update every import site so that all callers
use the new location. Keep `typer/utils.py` otherwise unchanged.

After your changes, ALL of the following must hold:
- `typer/_param_extractor.py` exists and defines `get_params_from_function`.
- `typer/utils.py` no longer defines `get_params_from_function`.
- No file imports `get_params_from_function` from `typer.utils` anymore.
- At least one file imports it from `typer._param_extractor`.
- `../../scripts/harness.sh --json-only` reports exit_code=0 (mypy / ruff_check / pytest all green;
  ruff_format is informational only — ignore it).

Verify with `../../scripts/breakage-pack/verify-T2.sh --json-only` (run via bash) before declaring done.
"""

T3 = """\
Task T3: feature-add.

You are working inside the typer repository (your cwd is the typer repo root).
Implement a new public function `get_version_banner` on the typer package.

Spec:
```python
def get_version_banner(prefix: str = "Typer", uppercase: bool = False) -> str:
    \"\"\"Return a one-line version banner.

    Format: '{prefix} v{typer.__version__} (Python {major}.{minor})'

    If uppercase=True, the entire result is upper-cased.
    \"\"\"
```

Requirements:
- Importable as `typer.get_version_banner` (i.e. re-export from `typer/__init__.py`).
- mypy strict must pass on the new code (str / bool args, str return).
- The provided tests in `tests/test_t3_feature.py` must pass. DO NOT modify that
  test file — its sha256 is fingerprinted and the verifier will reject changes.
- `../../scripts/harness.sh --json-only` reports exit_code=0 (mypy / ruff_check / pytest
  green; ruff_format is informational only — ignore it).

Verify with `../../scripts/breakage-pack/verify-T3.sh --json-only` before declaring done.
"""

PROMPTS = {"T1": T1, "T2": T2, "T3": T3}


SYSTEM_SOLO = """\
You are a code-fixing agent operating in a sandboxed Python repository.

You have two tools:
- `str_replace_editor`: view / create / str_replace / insert files (paths are repo-relative).
- `bash`: run shell commands in the repo root (120s timeout).

You will be given a task. Iteratively read code, run the harness, fix issues,
and re-run until the harness is green. Be concise in your reasoning; spend tokens
on tool calls, not narration.

When you believe the task is complete and the verifier passes, output a single
line `DONE` and stop. If you cannot make progress, output `BLOCKED: <reason>` and stop.
"""


SYSTEM_ORCHESTRATOR = """\
You are the orchestrator of a two-LLM team. You decide WHAT to do; an executor
LLM (which can read files, edit files, and run shell commands) does it for you.

You have three tools:
- `bash`: run shell commands in the repo root (use this to inspect state, run
  `../../scripts/harness.sh --json-only`, run `../../scripts/breakage-pack/verify-*.sh --json-only`).
- `str_replace_editor`: read files yourself with `view` when you need to inspect
  something before instructing the executor. Avoid using create/str_replace —
  delegate edits to the executor.
- `delegate_to_executor`: hand off a concrete edit/refactor instruction to the
  executor. The executor returns a short summary of what it did. Be precise:
  name files, name functions, name the exact change. The executor is cheaper but
  weaker than you, so spell out the change rather than asking it to "figure it out".

Loop: read harness output → plan → delegate small chunks → check harness →
repeat until green. Output `DONE` when verifier passes, `BLOCKED: <reason>` if stuck.
"""


SYSTEM_EXECUTOR = """\
You are an execution sub-agent. Another LLM (the orchestrator) has handed you a
concrete instruction. Do exactly what it asks using `str_replace_editor` and
`bash`. Do not expand scope. When done, output `DONE: <one-line summary>` and stop.
If the instruction is impossible as written, output `BLOCKED: <reason>` and stop.
"""
