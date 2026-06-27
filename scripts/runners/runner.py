"""Entry point for exp025 trials.

Usage:
    python -m runners.runner --arm A --task T3 --trial 0
    python -m runners.runner --arm B --task T1 --trial 0 --dry-run
    python -m runners.runner --arm A --task T3 --trial 0 --max-iters 25

JSONL is appended to results/{arm}.jsonl.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

EXP_ROOT = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = EXP_ROOT / "base-repo" / "typer"
RESULTS = EXP_ROOT / "data" / "results"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["A", "B", "C", "D"])
    ap.add_argument("--task", required=True, choices=["T1", "T2", "T3"])
    ap.add_argument("--trial", type=int, required=True)
    ap.add_argument("--max-iters", type=int, default=None,
                    help="cap on outer turn count (default: arm-specific)")
    ap.add_argument("--dry-run", action="store_true",
                    help="setup repo + print prompt; do not call any model")
    args = ap.parse_args()

    if not REPO_ROOT.exists():
        print(f"ERR: {REPO_ROOT} missing. See base-repo/BASE_VERIFICATION.md.", file=sys.stderr)
        return 2

    if args.dry_run:
        from . import harness_io, task_prompts
        harness_io.setup_task(args.task)
        print(f"== setup complete (task={args.task}) ==")
        print(harness_io.summarize_harness(harness_io.verify_task(args.task)))
        print(f"== prompt (arm={args.arm}) ==")
        print(task_prompts.PROMPTS[args.task][:1000])
        return 0

    from . import agent
    result = agent.trial(args.arm, args.task, args.trial, REPO_ROOT, max_iters=args.max_iters)

    RESULTS.mkdir(exist_ok=True)
    out_path = RESULTS / f"{args.arm}.jsonl"
    with out_path.open("a") as f:
        f.write(result.to_jsonl() + "\n")

    print(result.to_jsonl())
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
