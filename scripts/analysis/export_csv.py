"""Flatten results/*.jsonl into analysis/trials.csv for paper tables / external tools."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

EXP_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = EXP_ROOT / "data" / "results"
OUT_CSV = EXP_ROOT / "data" / "trials.csv"


def main() -> int:
    rows = []
    for f in sorted(RESULTS_DIR.glob("*.jsonl")):
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            usage = r.get("usage_by_role", {})
            opus = usage.get("claude-opus-4-7", {})
            haiku = usage.get("claude-haiku-4-5-20251001", usage.get("claude-haiku-4-5", {}))
            rows.append(
                {
                    "arm": r["arm"],
                    "task": r["task"],
                    "trial": r["trial"],
                    "success": int(r["success"]),
                    "blocked": int(r.get("blocked", False)),
                    "wall_sec": r["wall_sec"],
                    "iterations": r["iterations"],
                    "cost_usd": r["total_cost_usd"],
                    "opus_in": opus.get("input_tokens", 0),
                    "opus_out": opus.get("output_tokens", 0),
                    "opus_cache_w": opus.get("cache_creation_input_tokens", 0),
                    "opus_cache_r": opus.get("cache_read_input_tokens", 0),
                    "haiku_in": haiku.get("input_tokens", 0),
                    "haiku_out": haiku.get("output_tokens", 0),
                    "haiku_cache_w": haiku.get("cache_creation_input_tokens", 0),
                    "haiku_cache_r": haiku.get("cache_read_input_tokens", 0),
                    "qwen_present": int("qwen-local" in usage),
                    "verify_exit": (r.get("verify_final") or {}).get("exit_code"),
                }
            )
    if not rows:
        print("no rows", file=sys.stderr)
        return 1
    OUT_CSV.parent.mkdir(exist_ok=True)
    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT_CSV} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
