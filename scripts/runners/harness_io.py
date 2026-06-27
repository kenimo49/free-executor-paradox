"""Wrappers for harness.sh / verify-T*.sh; parses JSON output."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

EXP_ROOT = Path(__file__).resolve().parent.parent.parent


def _parse_json_stdout(stdout: str, exit_code: int) -> dict:
    s = stdout.strip()
    # Drop any leading non-JSON noise; find first { and try from there.
    start = s.find("{")
    if start < 0:
        return {"exit_code": exit_code, "parse_error": True, "raw": s[-500:]}
    try:
        return json.loads(s[start:])
    except json.JSONDecodeError:
        return {"exit_code": exit_code, "parse_error": True, "raw": s[-500:]}


def run_harness() -> dict:
    p = subprocess.run(
        [str(EXP_ROOT / "scripts" / "harness.sh"), "--json-only"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    return _parse_json_stdout(p.stdout, p.returncode)


def run_verify(task: str) -> dict:
    script = EXP_ROOT / "scripts" / "breakage-pack" / f"verify-{task}.sh"
    if not script.exists():
        return run_harness()
    p = subprocess.run(
        [str(script), "--json-only"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    return _parse_json_stdout(p.stdout, p.returncode)


def reset_repo() -> None:
    subprocess.run(
        [str(EXP_ROOT / "scripts" / "breakage-pack" / "reset.sh")],
        check=True,
        capture_output=True,
        timeout=60,
    )


def inject_T1() -> None:
    subprocess.run(
        ["python3", str(EXP_ROOT / "scripts" / "breakage-pack" / "inject-breakage.py")],
        check=True,
        capture_output=True,
        timeout=60,
    )


def inject_T3() -> None:
    subprocess.run(
        [str(EXP_ROOT / "scripts" / "breakage-pack" / "inject-T3.sh")],
        check=True,
        capture_output=True,
        timeout=60,
    )


def setup_task(task: str) -> None:
    """reset + inject for the given task."""
    reset_repo()
    if task == "T1":
        inject_T1()
    elif task == "T2":
        pass
    elif task == "T3":
        inject_T3()
    else:
        raise ValueError(f"unknown task: {task}")


def verify_task(task: str) -> dict:
    if task == "T1":
        return run_harness()
    return run_verify(task)


def summarize_harness(h: dict) -> str:
    """Short human-readable summary for prompting the agent."""
    if h.get("parse_error"):
        return f"[harness parse error; raw tail: {h.get('raw', '')[:200]}]"
    parts = [f"exit_code={h.get('exit_code', '?')}"]
    if "harness" in h:
        h = h["harness"]
    if "mypy" in h:
        m = h["mypy"]
        parts.append(f"mypy errors={m.get('errors', '?')}")
    if "ruff_check" in h:
        r = h["ruff_check"]
        parts.append(f"ruff errors={r.get('errors', '?')}")
    if "pytest" in h:
        pt = h["pytest"]
        parts.append(
            f"pytest passed={pt.get('passed', '?')} failed={pt.get('failed', '?')} "
            f"collection_errors={pt.get('collection_errors', '?')}"
        )
    return ", ".join(parts)
