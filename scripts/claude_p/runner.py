"""One trial of the claude -p (Claude Code) replication.

    cd scripts && python3 -m claude_p.runner --arm Bt --task T3 --trial 0

Arms (orchestrator is always Claude Code headless, model pinned to Opus 4.7 as in the paper):
    A   Opus solo (Read/Edit/Write/Bash/Grep/Glob)
    B   Opus + Qwen, executor returns free-form text (<=4000 chars)       -- paper arm B
    Bs  Opus + Qwen, same text cut to ~300 chars                          -- length-only control
    Bt  Opus + Qwen, typed return (verifier counts + Jev-style p_done)    -- proposed

The only difference between B / Bs / Bt is the --mode passed to delegate.py.
Results are appended to data/results-claude-p/{arm}.jsonl.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from runners import harness_io, task_prompts

EXP_ROOT = Path(__file__).resolve().parent.parent.parent
REPO = EXP_ROOT / "base-repo" / "typer"
OUT = EXP_ROOT / "data" / "results-claude-p"
MODEL = os.environ.get("FEP_OPUS", "claude-opus-4-7")
MODES = {"B": "free", "Bs": "short", "Bt": "typed"}
RETURN_DESC = {
    "free": "the executor's own log of what it did (free-form text, possibly truncated)",
    "short": "a short excerpt of the executor's log (about 300 characters)",
    "typed": ("one line of JSON: verifier counts after the edit (green, mypy, ruff, pytest_failed, collection_errors), "
              "files_changed, p_done (a local judge's probability that your instruction was completed), and at most one error line"),
}

SOLO = """You are a code-fixing agent operating in a sandboxed Python repository (your cwd).
Iteratively read code, run the harness, fix issues, and re-run until the verifier is green.
Be concise in your reasoning; spend tokens on tool calls, not narration. Never run commands in the background.
When the task is complete and the verifier passes, output a single line `DONE` and stop.
If you cannot make progress, output `BLOCKED: <reason>` and stop."""

ORCH = """You are the orchestrator of a two-LLM team. You decide WHAT to do; an executor LLM (which can read files,
edit files and run shell commands) does the editing for you.

- Use Read / Grep / Glob and Bash to inspect state and to run the harness / verifier.
- Do NOT edit files yourself (no Edit/Write, no sed -i, no shell redirection into files). Delegate every edit with:
    python3 ../../scripts/claude_p/delegate.py --mode {mode} --task {task} "<precise instruction>"
  The command returns {ret}.
- The executor is cheaper but weaker than you: name files, functions and the exact change.
- Never run commands in the background.

Loop: read harness output -> plan -> delegate small chunks -> check -> repeat until green.
Output `DONE` when the verifier passes, `BLOCKED: <reason>` if stuck."""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["A", "B", "Bs", "Bt"])
    ap.add_argument("--task", required=True, choices=["T1", "T2", "T3"])
    ap.add_argument("--trial", type=int, required=True)
    ap.add_argument("--max-turns", type=int, default=80)
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    harness_io.setup_task(a.task)
    dlog = OUT / "delegate-logs" / f"{a.arm}-{a.task}-{a.trial}.jsonl"
    dlog.parent.mkdir(exist_ok=True)
    dlog.unlink(missing_ok=True)

    if a.arm == "A":
        system, tools = SOLO, "Bash,Read,Edit,Write,Grep,Glob"
    else:
        mode = MODES[a.arm]
        system, tools = ORCH.format(mode=mode, task=a.task, ret=RETURN_DESC[mode]), "Bash,Read,Grep,Glob"

    cmd = ["claude", "-p", "--model", MODEL, "--output-format", "json", "--tools", tools, "--allowedTools", tools.replace(",", " "),
           "--permission-mode", "dontAsk", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--setting-sources", "project", "--no-session-persistence", "--max-turns", str(a.max_turns),
           "--append-system-prompt", system, task_prompts.PROMPTS[a.task]]
    env = dict(os.environ, FEP_DELEGATE_LOG=str(dlog), BASH_DEFAULT_TIMEOUT_MS="900000", BASH_MAX_TIMEOUT_MS="1500000")
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=5400)
        raw = p.stdout
    except subprocess.TimeoutExpired as e:
        raw = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
    wall = time.time() - t0
    try:
        res = json.loads(raw[raw.find("{"):])
    except (json.JSONDecodeError, ValueError):
        res = {"parse_error": True, "raw_tail": raw[-500:]}
    verify = harness_io.run_verify(a.task) if a.task != "T1" else harness_io.run_harness()
    delegates = [json.loads(l) for l in dlog.open()] if dlog.exists() else []
    rec = {
        "arm": a.arm, "task": a.task, "trial": a.trial, "model": MODEL, "claude_version": subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip(),
        "success": verify.get("exit_code") == 0, "wall_sec": round(wall, 1),
        "num_turns": res.get("num_turns"), "stop": res.get("subtype") or res.get("stop_reason"), "result_tail": str(res.get("result", ""))[-200:],
        "usage": res.get("usage"), "modelUsage": res.get("modelUsage"), "total_cost_usd": res.get("total_cost_usd"),
        "n_delegate": len(delegates), "returned_chars": sum(d["returned_chars"] for d in delegates),
        "exec_out_chars": sum(d["exec_out_chars"] for d in delegates), "delegates": delegates, "verify": verify,
    }
    with (OUT / f"{a.arm}.jsonl").open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps({k: rec[k] for k in ("arm", "task", "trial", "success", "wall_sec", "num_turns", "n_delegate", "returned_chars", "total_cost_usd")}))
    return 0 if rec["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
