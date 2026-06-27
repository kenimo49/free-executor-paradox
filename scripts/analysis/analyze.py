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
    """Stacked bar: Opus token breakdown per task per arm (cache_read / input / cache_write / output)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        return
    tasks = ["T1", "T2", "T3"]
    arms = ["A", "B", "C"]
    labels = {"A": "A:\nOpus solo", "B": "B:\nOpus+Qwen", "C": "C:\nOpus+Haiku"}
    components = ["cache_read", "input", "cache_write", "output"]
    comp_labels = {
        "cache_read":  "cache_read  (0.10x rate)",
        "input":       "input  (1.00x rate)",
        "cache_write": "cache_write  (1.25x rate)",
        "output":      "output  (5.00x rate)",
    }
    comp_colors = {
        "cache_read":  "#a8d8ea",
        "input":       "#1f77b4",
        "cache_write": "#ffb347",
        "output":      "#d62728",
    }
    key_map = {
        "input": "input_tokens",
        "output": "output_tokens",
        "cache_write": "cache_creation_input_tokens",
        "cache_read": "cache_read_input_tokens",
    }

    def opus_med(arm, task, comp):
        ts = [t for t in g.get((arm, task), []) if t["success"]]
        if not ts:
            return 0
        return statistics.median(
            t["usage_by_role"].get("claude-opus-4-7", {}).get(key_map[comp], 0) for t in ts
        )

    fig, axes = plt.subplots(1, 3, figsize=(11, 5), sharey=False)
    for task_idx, task in enumerate(tasks):
        ax = axes[task_idx]
        x = np.arange(len(arms))
        bottom = np.zeros(len(arms))
        for comp in components:
            vals = np.array([opus_med(a, task, comp) / 1000 for a in arms])
            ax.bar(x, vals, 0.65, bottom=bottom,
                   label=comp_labels[comp] if task_idx == 0 else "",
                   color=comp_colors[comp], edgecolor="white", linewidth=0.5)
            bottom += vals
        for i, a in enumerate(arms):
            total = sum(opus_med(a, task, c) for c in components) / 1000
            ax.text(i, total, f"{total:.0f}k", ha="center", va="bottom", fontsize=9, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels([labels[a] for a in arms], fontsize=9)
        ax.set_title(f"Task {task}", fontsize=11)
        ax.grid(axis="y", alpha=0.3)
        ax.set_ylim(0, ax.get_ylim()[1] * 1.18)
        if task_idx == 0:
            ax.set_ylabel("Opus-side tokens (x1000, success-only median)")

    fig.suptitle("Free-Executor Paradox: Opus token breakdown - cache_read dominates orchestrated arms",
                 fontsize=12, y=1.00)
    handles, lbls = axes[0].get_legend_handles_labels()
    fig.legend(handles, lbls, loc="lower center", ncol=4, bbox_to_anchor=(0.5, -0.02), fontsize=9)
    fig.tight_layout(rect=(0, 0.04, 1, 0.98))
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out_path}")


def mechanism_schematic(out_path: Path) -> None:
    """Causal-chain schematic of the free-executor paradox."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
    except ImportError:
        return
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 5)
    ax.axis("off")

    boxes = [
        (0.2, 1.5, 1.9, 2.0, "Orchestrator\n(Opus)\nplans next step", "#fce4d6"),
        (2.6, 1.5, 1.9, 2.0, "delegate_to_executor(\n  instruction)", "#fff3b3"),
        (5.0, 1.5, 1.9, 2.0, "Executor\n(Qwen / Haiku)\nedits files", "#d4edda"),
        (7.4, 1.5, 2.4, 2.0, "returns\nsummary string\n(<= 4000 chars)", "#cfe2f3"),
    ]
    for x, y, w, h, txt, c in boxes:
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05",
                                    facecolor=c, edgecolor="black", linewidth=1.2))
        ax.text(x + w/2, y + h/2, txt, ha="center", va="center", fontsize=10)

    arrows = [(2.1, 2.5, 2.6, 2.5), (4.5, 2.5, 5.0, 2.5), (6.9, 2.5, 7.4, 2.5)]
    for x1, y1, x2, y2 in arrows:
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="->,head_width=0.3,head_length=0.4",
                                     color="#444", linewidth=1.8, mutation_scale=15))

    ax.add_patch(FancyArrowPatch((8.6, 1.5), (1.0, 1.5),
                                 arrowstyle="->,head_width=0.4,head_length=0.5",
                                 connectionstyle="arc3,rad=-0.35",
                                 color="#c0392b", linewidth=2.2, mutation_scale=15))
    ax.text(5.0, 0.35,
            "summary appended to orchestrator context\n=> cache_write next turn, cache_read every subsequent turn",
            ha="center", va="center", fontsize=10, color="#c0392b", fontweight="bold")

    ax.text(5.0, 4.55, "Causal chain of the Free-Executor Paradox",
            ha="center", va="center", fontsize=13, fontweight="bold")
    ax.text(5.0, 4.1,
            "Even though Qwen tokens are $0, every additional turn re-bills the orchestrator for the summary it already saw.",
            ha="center", va="center", fontsize=10, style="italic", color="#444")

    fig.tight_layout()
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
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
        OUT_DIR.mkdir(exist_ok=True, parents=True)
        for t in ["T1", "T2", "T3"]:
            pareto_plot(g, t, OUT_DIR / f"pareto-{t}.png")
        token_growth_plot(g, OUT_DIR / "token-growth.png")
        mechanism_schematic(OUT_DIR / "mechanism.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
