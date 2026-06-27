"""Load results/*.jsonl → summary stats + Mann-Whitney U pairwise tests + Pareto plot.

Usage:
    python analysis/analyze.py            # print tables to stdout
    python analysis/analyze.py --plot     # also write analysis/pareto-{T1,T2,T3}.png
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

EXP_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = EXP_ROOT / "data" / "results"
OUT_DIR = EXP_ROOT / "results" / "figures"


def load_rows() -> list[dict]:
    rows = []
    for f in sorted(RESULTS_DIR.glob("*.jsonl")):
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            # Filter out credit-error / no-token rows
            if r.get("iterations", 0) == 0 and not r.get("success"):
                continue
            rows.append(r)
    return rows


def group(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    g = defaultdict(list)
    for r in rows:
        g[(r["arm"], r["task"])].append(r)
    return dict(g)


def summary_table(g: dict, success_only: bool = True) -> str:
    """Summary table with bootstrap CI for cost and cost-per-success column."""
    out = [
        f"{'arm':<4}{'task':<6}{'n_s/n':<6}{'wall_med':<9}{'iters':<7}"
        f"{'cost_med':<10}{'cost_95CI':<18}{'cost/succ':<10}{'success':<8}"
    ]
    for k in sorted(g):
        arm, task = k
        trials = g[k]
        n_total = len(trials)
        succ = [t for t in trials if t["success"]]
        subset = succ if success_only else trials
        n = len(subset)
        if n == 0:
            out.append(f"{arm:<4}{task:<6}{f'0/{n_total}':<6}{'—':<9}{'—':<7}{'—':<10}{'—':<18}{'—':<10}{'0.00':<8}")
            continue
        costs = [t["total_cost_usd"] for t in subset]
        sr = len(succ) / n_total
        wmed = statistics.median(t["wall_sec"] for t in subset)
        imed = statistics.median(t["iterations"] for t in subset)
        cmed = statistics.median(costs)
        ci_lo, ci_hi = bootstrap_ci_median(costs)
        ci_str = f"[{ci_lo:.2f},{ci_hi:.2f}]" if not math.isnan(ci_lo) else "—"
        cps = cmed / sr if sr > 0 else float("inf")
        cps_str = f"{cps:.3f}" if cps != float("inf") else "inf"
        out.append(
            f"{arm:<4}{task:<6}{f'{n}/{n_total}':<6}{wmed:<9.1f}{imed:<7.1f}"
            f"{cmed:<10.4f}{ci_str:<18}{cps_str:<10}{sr:<8.2f}"
        )
    return "\n".join(out)


def cliffs_delta_table(g: dict, task: str) -> str:
    arms = ["A", "B", "C", "D"]
    out = [f"\nCliff's delta + magnitude (cost_usd) for task {task}, success-only:"]
    out.append("      " + "  ".join(f"{a:<14}" for a in arms))
    for a in arms:
        row = [f"{a:<6}"]
        ca = [t["total_cost_usd"] for t in g.get((a, task), []) if t["success"]]
        for b in arms:
            if a == b:
                row.append(f"{'—':<14}")
                continue
            cb = [t["total_cost_usd"] for t in g.get((b, task), []) if t["success"]]
            d, mag = cliffs_delta(ca, cb)
            row.append(f"{d:+.2f}({mag[:3]:>3}) ")
        out.append("  ".join(row))
    return "\n".join(out)


def mann_whitney_u(a: list[float], b: list[float]) -> float:
    """Return U statistic (smaller of U1/U2). Standalone, no scipy."""
    n1, n2 = len(a), len(b)
    if n1 == 0 or n2 == 0:
        return float("nan")
    combined = sorted([(v, "a") for v in a] + [(v, "b") for v in b])
    ranks = {}
    i = 0
    while i < len(combined):
        j = i
        while j + 1 < len(combined) and combined[j + 1][0] == combined[i][0]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[k] = avg_rank
        i = j + 1
    r1 = sum(r for k, r in ranks.items() if combined[k][1] == "a")
    u1 = r1 - n1 * (n1 + 1) / 2
    u2 = n1 * n2 - u1
    return min(u1, u2)


def mann_whitney_p_approx(a: list[float], b: list[float]) -> float:
    """Normal approximation p-value (two-sided). Rough — for n<10 take with grain of salt."""
    n1, n2 = len(a), len(b)
    if n1 < 3 or n2 < 3:
        return float("nan")
    u = mann_whitney_u(a, b)
    mu = n1 * n2 / 2
    sigma = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    if sigma == 0:
        return 1.0
    z = (u - mu) / sigma
    # Two-sided p via erfc
    p = math.erfc(abs(z) / math.sqrt(2))
    return p


def cliffs_delta(a: list[float], b: list[float]) -> tuple[float, str]:
    """Cliff's delta effect size (-1..1) + magnitude label.

    Magnitude (Romano et al., 2006):
        |d| < 0.147  negligible
        |d| < 0.330  small
        |d| < 0.474  medium
        else         large
    """
    if not a or not b:
        return (float("nan"), "n/a")
    gt = lt = 0
    for x in a:
        for y in b:
            if x > y:
                gt += 1
            elif x < y:
                lt += 1
    d = (gt - lt) / (len(a) * len(b))
    ad = abs(d)
    mag = "negligible" if ad < 0.147 else "small" if ad < 0.33 else "medium" if ad < 0.474 else "large"
    return (d, mag)


def bootstrap_ci_median(values: list[float], n_resamples: int = 10000, alpha: float = 0.05, seed: int = 42) -> tuple[float, float]:
    """Bootstrap CI for the median. Deterministic seed for reproducibility."""
    if len(values) < 2:
        return (float("nan"), float("nan"))
    import random
    rng = random.Random(seed)
    n = len(values)
    medians = []
    for _ in range(n_resamples):
        sample = [values[rng.randint(0, n - 1)] for _ in range(n)]
        medians.append(statistics.median(sample))
    medians.sort()
    lo = medians[int(n_resamples * alpha / 2)]
    hi = medians[int(n_resamples * (1 - alpha / 2)) - 1]
    return (lo, hi)


def pairwise_cost(g: dict, task: str) -> str:
    arms = ["A", "B", "C", "D"]
    out = [f"\nMann-Whitney U (cost_usd) for task {task}, two-sided p (normal approx):"]
    header = "      " + "  ".join(f"{a:<8}" for a in arms)
    out.append(header)
    for a in arms:
        row = [f"{a:<6}"]
        ca = [r["total_cost_usd"] for r in g.get((a, task), []) if r["success"]]
        for b in arms:
            if a == b:
                row.append("—       ")
                continue
            cb = [r["total_cost_usd"] for r in g.get((b, task), []) if r["success"]]
            p = mann_whitney_p_approx(ca, cb)
            if math.isnan(p):
                row.append("n<3     ")
            else:
                row.append(f"{p:<8.3f}")
        out.append("  ".join(row))
    return "\n".join(out)


def pareto_plot(g: dict, task: str, out_path: Path) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[matplotlib not installed; skipping plot]", file=sys.stderr)
        return

    arms = ["A", "B", "C", "D"]
    colors = {"A": "#d62728", "B": "#2ca02c", "C": "#1f77b4", "D": "#ff7f0e"}
    labels = {
        "A": "A: Opus solo",
        "B": "B: Opus+Qwen",
        "C": "C: Opus+Haiku",
        "D": "D: Haiku solo",
    }
    fig, ax = plt.subplots(figsize=(7, 5))
    for a in arms:
        trials = g.get((a, task), [])
        if not trials:
            continue
        xs = [t["total_cost_usd"] for t in trials]
        ys = [t["wall_sec"] for t in trials]
        styles = ["o" if t["success"] else "x" for t in trials]
        for x, y, s in zip(xs, ys, styles):
            ax.scatter(x, y, c=colors[a], marker=s, s=60, alpha=0.8)
        # median point bigger
        if any(t["success"] for t in trials):
            sx = sorted([t["total_cost_usd"] for t in trials if t["success"]])
            sy = sorted([t["wall_sec"] for t in trials if t["success"]])
            if sx:
                ax.scatter(
                    statistics.median(sx),
                    statistics.median(sy),
                    c=colors[a],
                    marker="s",
                    s=120,
                    edgecolors="k",
                    linewidths=1.5,
                    label=labels[a],
                )
    ax.set_xlabel("cost (USD)")
    ax.set_ylabel("wall time (s)")
    ax.set_title(f"task {task}: cost × wall Pareto (○=success, ×=fail, ▪=median)")
    ax.grid(alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    print(f"wrote {out_path}")


def token_growth_plot(g: dict, out_path: Path) -> None:
    """Bar chart: Opus input + cache_read per task per arm, B/A and C/A multipliers."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    tasks = ["T1", "T2", "T3"]
    arms = ["A", "B", "C"]
    labels = {"A": "A: Opus solo", "B": "B: Opus + Qwen", "C": "C: Opus + Haiku"}
    colors = {"A": "#d62728", "B": "#2ca02c", "C": "#1f77b4"}

    def opus_in(arm, task):
        ts = [t for t in g.get((arm, task), []) if t["success"]]
        if not ts:
            return 0
        return statistics.median(
            t["usage_by_role"].get("claude-opus-4-7", {}).get("input_tokens", 0)
            + t["usage_by_role"].get("claude-opus-4-7", {}).get("cache_read_input_tokens", 0)
            for t in ts
        )

    import numpy as np
    x = np.arange(len(tasks))
    width = 0.27
    fig, ax = plt.subplots(figsize=(8, 5))
    for i, arm in enumerate(arms):
        vals = [opus_in(arm, t) / 1000 for t in tasks]
        offset = (i - 1) * width
        bars = ax.bar(x + offset, vals, width, label=labels[arm], color=colors[arm], alpha=0.85)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.0f}k", ha="center", va="bottom", fontsize=9)

    # Multiplier annotations B/A and C/A
    for j, t in enumerate(tasks):
        a = opus_in("A", t)
        b = opus_in("B", t)
        c = opus_in("C", t)
        if a > 0:
            txt = f"B/A={b/a:.2f}×\nC/A={c/a:.2f}×"
            ax.annotate(txt, xy=(j, max(b, a, c) / 1000), xytext=(j, max(b, a, c) / 1000 * 1.18),
                        ha="center", fontsize=9, color="#555")

    ax.set_xticks(x)
    ax.set_xticklabels(tasks)
    ax.set_ylabel("Opus side: input + cache_read tokens (×1000, median)")
    ax.set_title("Free Executor Paradox: Opus context grows when delegating")
    ax.legend(loc="upper right")
    ax.grid(axis="y", alpha=0.3)
    ax.set_ylim(0, ax.get_ylim()[1] * 1.25)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    print(f"wrote {out_path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plot", action="store_true")
    args = ap.parse_args()
    rows = load_rows()
    print(f"loaded {len(rows)} trial rows from {RESULTS_DIR}\n")
    g = group(rows)
    print(summary_table(g))
    for t in ["T1", "T2", "T3"]:
        print(pairwise_cost(g, t))
        print(cliffs_delta_table(g, t))
    if args.plot:
        OUT_DIR.mkdir(exist_ok=True)
        for t in ["T1", "T2", "T3"]:
            pareto_plot(g, t, OUT_DIR / f"pareto-{t}.png")
        token_growth_plot(g, OUT_DIR / "token-growth.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
