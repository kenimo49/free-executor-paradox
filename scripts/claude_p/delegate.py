"""Executor wrapper for the claude -p orchestrator arms (B / Bs / Bt).

The orchestrator (Claude Code, Opus) calls this through Bash:

    python3 ../../scripts/claude_p/delegate.py --mode typed --task T1 "instruction..."

The executor itself is identical across modes (qwen-task.sh --agent, Qwen 3.5-9B on Ollama).
Only the text returned to the orchestrator differs:

- free  : stdout/stderr, truncated to 4000 chars (same as the SDK arm B in the paper)
- short : the same text cut to ~300 chars (control: length only)
- typed : no executor prose. Deterministic verifier counts + files changed + a Jev-style
          typed judgment p_done (probability from one-token logprobs of a local model),
          plus at most one error line. Designed to be ~50-100 tokens.

Every call is appended to $FEP_DELEGATE_LOG (jsonl) with the returned length, so the
analysis can relate orchestrator token growth to what the executor returned.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import time
import urllib.request
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
QWEN_TASK = SCRIPTS / "qwen-task.sh"
HARNESS = SCRIPTS / "harness.sh"
OLLAMA = os.environ.get("OLLAMA_HOST", "http://100.72.192.8:11434") + "/api/chat"
JUDGE_MODEL = os.environ.get("FEP_JUDGE_MODEL", "qwen3.5:9b")


def run_executor(instruction: str, cwd: Path, timeout: int = 600) -> tuple[str, int]:
    try:
        p = subprocess.run([str(QWEN_TASK), "--agent", "--dir", str(cwd), instruction],
                           capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "") + ("\n--- stderr ---\n" + p.stderr if p.stderr else "")
        return out, p.returncode
    except subprocess.TimeoutExpired:
        return f"qwen executor TIMEOUT after {timeout}s", 124


def fmt_free(out: str, rc: int) -> str:
    if len(out) > 4000:
        out = out[:2000] + "\n[... truncated ...]\n" + out[-2000:]
    return out + f"\n[qwen exit={rc}]"


def fmt_short(out: str, rc: int) -> str:
    if len(out) > 300:
        out = out[:150] + "\n[...]\n" + out[-150:]
    return out + f"\n[qwen exit={rc}]"


def harness_counts(task: str) -> dict:
    script = SCRIPTS / "breakage-pack" / f"verify-{task}.sh"
    cmd = [str(script if (task in ("T2", "T3") and script.exists()) else HARNESS), "--json-only"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    s = p.stdout[p.stdout.find("{"):] if "{" in p.stdout else "{}"
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return {"exit_code": p.returncode, "parse_error": True}


def first_error(cwd: Path) -> str:
    for cmd in (["uv", "run", "mypy", "typer"], ["uv", "run", "ruff", "check", "typer", "tests", "--output-format", "concise"],
                ["uv", "run", "pytest", "-q", "--no-cov", "-x", "--no-header"]):
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)
        if p.returncode != 0:
            for line in (p.stdout + p.stderr).splitlines():
                if "error" in line.lower() or "FAILED" in line or line.startswith("E "):
                    return line.strip()[:160]
    return ""


def judge_done(instruction: str, out: str, counts: dict) -> float:
    """Jev-style noul: P(Y) of a one-letter answer, renormalised over {Y, N}."""
    prompt = ("An executor model was given an instruction and ran it. Using the instruction, the tail of its log, and the "
              "verifier counts, did the executor complete the instruction as asked? Answer with a single letter, Y or N.\n\n"
              f"Instruction: {instruction[:1200]}\n\nLog tail: {out[-800:]}\n\nVerifier: {json.dumps(counts)}")
    body = {"model": JUDGE_MODEL, "stream": False, "think": False, "logprobs": True, "top_logprobs": 20,
            "options": {"temperature": 0, "num_predict": 1}, "messages": [{"role": "user", "content": prompt}]}
    try:
        req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.load(r)
        raw = {"Y": 0.0, "N": 0.0}
        for t in d["logprobs"][0]["top_logprobs"]:
            if t["token"].strip() in raw:
                raw[t["token"].strip()] += math.exp(t["logprob"])
        m = sum(raw.values())
        return round(raw["Y"] / m, 3) if m > 0 else -1.0
    except Exception:  # noqa: BLE001
        return -1.0


def fmt_typed(instruction: str, out: str, rc: int, task: str, cwd: Path) -> str:
    v = harness_counts(task)
    c = v.get("harness", v) if isinstance(v.get("harness"), dict) else v
    diff = subprocess.run(["git", "diff", "--name-only"], cwd=cwd, capture_output=True, text=True).stdout.split()
    new = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "typer", "tests"], cwd=cwd, capture_output=True, text=True).stdout.split()
    res = {
        "executor_exit": rc,
        "files_changed": len(diff) + len(new),
        "green": v.get("exit_code") == 0,
        "mypy": (c.get("mypy") or {}).get("errors"),
        "ruff": (c.get("ruff_check") or {}).get("errors"),
        "pytest_failed": (c.get("pytest") or {}).get("failed"),
        "collection_errors": (c.get("pytest") or {}).get("collection_errors"),
        "p_done": judge_done(instruction, out, c),
    }
    checks = v.get(f"{task.lower()}_checks")
    if isinstance(checks, dict):
        res["verify_failed"] = [k for k, ok in checks.items() if ok in (False, 0, "false") and k != "all_pass"][:5]
    if not res["green"]:
        res["first_error"] = first_error(cwd)
    return json.dumps(res, ensure_ascii=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["free", "short", "typed"], required=True)
    ap.add_argument("--task", choices=["T1", "T2", "T3"], required=True)
    ap.add_argument("instruction", nargs="+")
    a = ap.parse_args()
    instruction = " ".join(a.instruction)
    cwd = Path.cwd()
    t0 = time.time()
    out, rc = run_executor(instruction, cwd)
    t1 = time.time()
    if a.mode == "free":
        ret = fmt_free(out, rc)
    elif a.mode == "short":
        ret = fmt_short(out, rc)
    else:
        ret = fmt_typed(instruction, out, rc, a.task, cwd)
    log = os.environ.get("FEP_DELEGATE_LOG")
    if log:
        with open(log, "a") as f:
            f.write(json.dumps({"mode": a.mode, "task": a.task, "instr_chars": len(instruction), "exec_out_chars": len(out),
                                "returned_chars": len(ret), "exec_sec": round(t1 - t0, 1), "format_sec": round(time.time() - t1, 1),
                                "exit": rc}) + "\n")
    print(ret)


if __name__ == "__main__":
    main()
