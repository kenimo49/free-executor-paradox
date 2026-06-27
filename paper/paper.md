# Orchestration vs Solo Model Selection on Code-Repair Tasks: A Harness-Judged Pareto Comparison of Opus, Haiku, and Local Qwen

**Author**: Ken Imoto (Propel-Lab LLC)
**Date**: 2026-06-27
**Code & data**: <https://github.com/kenimo49/iris-lab/tree/main/experiments/025-orchestrator-vs-solo>
**License**: CC-BY 4.0 (text), MIT (code), MIT (base repo `typer`)

---

## Abstract

We compare four LLM configurations on three Python code-repair tasks — a 25-error breakage recovery, a refactor, and a feature-add — using a single deterministic correctness judge (mypy + ruff + pytest exit codes). The configurations are two single-model "solo" arms (Anthropic Opus 4.7, Haiku 4.5) and two "orchestrator + executor" arms in which Opus orchestrates either local Qwen 3.5-9B (zero marginal token cost) or Anthropic Haiku.

Across 40 trials with n = 3 successful runs per cell, the cost / wall-time / iterations Pareto frontier varies across the three task types. On the smallest task, Opus solo dominates every cloud-only axis at \$0.17 / trial and 6 iterations median; only Haiku solo undercuts it on cost (\$0.08), at 3× the wall-time. On the longest task, Haiku solo wins on dollar cost — its success-only median of \$0.30 is 5.5× cheaper than the cheapest cloud arm (Opus + Haiku at \$1.67) — but the saving is bought at a 25% failure rate within our per-arm iteration cap.

Our central finding is mechanical: the canonical "strong orchestrator + cheap executor" structure (Opus + Qwen, arm B) is the most expensive cloud arm on every task we tested. Its orchestrator-side cache-reads of the executor's returned summaries grow input volume by 1.4–5.3× over Opus solo, and dominate any savings from delegating execution. The paper aims to make the underlying tradeoff cheap to measure on other codebases, not to crown a single winner.

---

## 1. Introduction

Agentic coding assistants are now routinely composed of more than one model. Practitioners must choose:

- whether to run a single capable model end-to-end ("solo"),
- whether to pair a stronger orchestrator with a cheaper executor ("orchestrated"),
- and which exact model fills each role.

The field has converged on two informal heuristics — "biggest model, every call" and "one cheap model, more retries" — neither of which is justified by direct comparison under a fair judge. Most published comparisons rely either on LLM-as-judge or on aggregate benchmarks (HumanEval, MBPP, SWE-bench), and neither captures the cost-iteration-correctness tradeoff faced by an agent that *is allowed to retry until it converges*.

This paper makes three contributions:

1. We use a **decision-deterministic** harness — three tools (mypy, ruff, pytest) whose exit codes alone constitute the correctness judgment. No LLM grades the work. This removes one common confounder from agentic-coding benchmarks.
2. We add a "**\$0 marginal cost executor**" axis to the orchestration comparison, in the form of a locally hosted Qwen 3.5-9B model.
3. We measure **iterations to convergence** as a primary metric alongside dollars and wall-time, giving budget-aware practitioners a directly actionable signal.

The empirical result of our small experiment is that the canonical "cheap-executor" orchestration form (Opus + Qwen, arm B) does not pay off on any of the three tasks we tested. The mechanism is straightforward: with prompt caching, the orchestrator's cost is dominated by its own context, which grows with executor output volume even when executor tokens themselves are free.

## 2. Related Work

**RouteLLM** [Ong et al., 2024] routes individual queries between strong and weak models based on a learned classifier. Our setting differs structurally: we measure the *full iterative loop* required to drive a deterministic judge to a green state, not a single query.

**FrugalGPT** [Chen et al., 2023] chains models in a cheap-to-expensive cascade, accepting an answer at the first stage with high enough confidence. We compare a cascade-adjacent setup (Opus orchestrator + cheap executor) under a hard convergence requirement.

**Mixture-of-Agents** [Wang et al., 2024] aggregates outputs across multiple LLMs with LLM-judge synthesis. Our orchestrator-executor structure is functionally adjacent but uses a deterministic harness as judge.

**HuggingGPT** [Shen et al., 2023] and **Voyager** [Wang et al., 2023] use planner-executor decompositions but do not measure per-trial dollar cost against a deterministic correctness oracle.

For evaluation context, **SWE-bench** [Jimenez et al., 2024] grades agentic code changes against real-world repository tests. Our setup is a much smaller, controlled variant in which the same harness is reused across configurations rather than a benchmark suite of unseen problems.

To our knowledge, we are not aware of a prior published comparison that combines (i) Anthropic Opus vs Haiku on the same task harness, (ii) a locally hosted "free executor" axis, and (iii) a non-LLM judge.

## 3. Method

### 3.1 Arms

| arm | orchestrator | executor | role split |
|-----|--------------|---------|------------|
| A | Opus 4.7 | (solo) | one model handles everything |
| B | Opus 4.7 | Qwen 3.5-9B (local, Ollama, via `qwen-task --agent`) | Opus plans + verifies, Qwen edits |
| C | Opus 4.7 | Haiku 4.5 (Anthropic SDK sub-loop) | Opus plans + verifies, Haiku edits |
| D | Haiku 4.5 | (solo) | one cheap model handles everything |

All four arms call the Anthropic API directly through the SDK and have access to identical tools: a `str_replace_editor` (view / create / str_replace / insert) scoped to the typer repository root, and a `bash` tool with a 120-second timeout. Orchestrators (B, C) additionally have a `delegate_to_executor(instruction)` tool that hands a single concrete instruction string to the executor.

The orchestrator and executor see **slightly different system prompts**. The solo system prompt (A, D) lets the model freely use `str_replace_editor`. The orchestrator prompt asks the model to avoid editing directly and to delegate edits instead. This asymmetry is intentional — it is how a real orchestrator/executor split would be deployed — but it is also a confounder, since it shapes the orchestrator's behavior beyond just adding the delegate tool. We return to this in §6.

Anthropic prompt caching is enabled identically on every call: `system`, tool definitions, and the most recent user message are marked with `cache_control: ephemeral`. No `temperature` or `seed` is set on either Anthropic or Qwen calls, so trial-to-trial variance reflects sampling stochasticity.

### 3.2 Tasks

All three tasks operate on the [`typer`](https://github.com/tiangolo/typer) repository at commit `b210c0e` (v0.26.8, MIT license). Each trial begins with `git checkout -- . && git clean -fd typer/ tests/` to restore the base state. The base repository is cloned at experiment time, not vendored.

**T1 — Breakage recovery.** A Python script using `ast.parse` deterministically injects 25 errors across 15 source / test files: 10 mypy type errors, 10 ruff lint errors, and 5 pytest collection-time failures (`assert False` lines prepended after the last top-level import in five test modules). The agent must return the harness to fully green.

**T2 — Refactor.** Move the function `get_params_from_function` from `typer/utils.py` to a new module `typer/_param_extractor.py`. Update every import site so that no file imports the function from the old location and at least one imports it from the new location. All tests must continue to pass.

**T3 — Feature-add.** Implement `get_version_banner(prefix: str = "Typer", uppercase: bool = False) -> str`, re-export it from `typer/__init__.py`, and make it pass a provided test file. The test file is fingerprinted with SHA-256 at injection time; the verifier rejects any modification to it. We acknowledge that this fingerprinting biases T3 toward "specification-following" behavior — agents that read the spec carefully are advantaged over agents that explore.

### 3.3 Harness

A bash script runs `uv run mypy`, `uv run ruff check`, `uv run ruff format` (informational only, not a failure condition), and `uv run pytest` in sequence and emits a single JSON blob with per-tool counts. A green base on this harness takes 22 seconds and reports 1356 tests passing. T3 adds 3 expected passes. `verify-T2.sh` and `verify-T3.sh` add task-specific structural checks (e.g. function moved to new module, public API callable, fingerprinted test unchanged).

### 3.4 Metrics

Per trial, we record:

- **success** — verifier exit code = 0,
- **iterations** — outer turns of the tool loop on the orchestrator side,
- **wall_sec** — seconds from `setup_task` to verifier completion,
- **cost_usd** — tokens × public rate card (Opus 4.7: \$15 / \$75 per M input / output; Haiku 4.5: \$1 / \$5; cache write 1.25×, cache read 0.10× of the input rate; Qwen marginal cost \$0),
- per-role token usage (input / output / cache_write / cache_read).

### 3.5 Trial budget

Per-arm outer-loop caps are a design variable, not a model property. We set them to give each arm fair chance to converge under realistic budgets:

| arm | T1 cap | T2 cap | T3 cap |
|-----|-------:|-------:|-------:|
| A   |     40 |     40 |     40 |
| B   |     80 |     60 |     60 |
| C   |     40 |     40 |     40 |
| D   |    100 |    120 |     80 |

D (Haiku solo) needs the highest cap because its per-iteration capability is lowest. Within these caps, failures count against the cell's success rate rather than being silently retried. We aim for n ≥ 3 *successful* trials per (arm, task) cell. Trials that exhaust the cap are recorded as failures and excluded from median statistics (their counts contribute to the visible success rate).

### 3.6 Statistical procedure

We report median and IQR per cell (success-only), and pairwise Mann-Whitney U tests on the cost-usd column within each task. Two-sided p-values use a normal approximation; under that approximation and n = 3–4 per cell, p = 0.050 is the boundary value. An exact Mann-Whitney U would yield slightly different small-sample p; we read p = 0.050 here as "as different as this sample size can show under this approximation" rather than as a strong significance claim.

## 4. Results

### 4.1 Summary table (success-only medians, n = 3 successful trials per cell)

| arm | task | n_succ / n_total | wall_med (s) | iters_med | cost_med (\$) | success rate |
|-----|------|:----------------:|-------------:|----------:|--------------:|-------------:|
| A Opus solo | T1 | 3 / 3 | 253 | 36 | 1.74 | 1.00 |
| A Opus solo | T2 | 3 / 4 | 233 | 26 | 1.11 | 0.75 |
| A Opus solo | T3 | 3 / 3 | **69** | **6** | 0.17 | 1.00 |
| B Opus+Qwen | T1 | 3 / 4 | 484 | 38 | 2.27 | 0.75 |
| B Opus+Qwen | T2 | 3 / 3 | 443 | 27 | 1.38 | 1.00 |
| B Opus+Qwen | T3 | 3 / 3 | 348 | 12 | 0.42 | 1.00 |
| C Opus+Haiku | T1 | 3 / 3 | 400 | **28** | 1.67 | 1.00 |
| C Opus+Haiku | T2 | 3 / 3 | 275 | **20** | **0.92** † | 1.00 |
| C Opus+Haiku | T3 | 3 / 3 | 145 | 11 | 0.38 | 1.00 |
| D Haiku solo | T1 | 3 / 4 | 758 | 89 | **0.30** | 0.75 |
| D Haiku solo | T2 | 3 / 4 | 507 | 70 | **0.23** | 0.75 |
| D Haiku solo | T3 | 3 / 3 | 208 | 29 | **0.08** | 1.00 |

Bolded numbers are per-task per-column winners. † C is the cheapest *cloud* arm on T2; D is cheaper overall but with a 25% failure rate. Cell totals: 40 trials, total Anthropic spend \$35.98.

### 4.2 Pareto frontiers

Three plots (`analysis/pareto-{T1,T2,T3}.png`) show cost (USD) on the x-axis and wall-time (seconds) on the y-axis. Each arm contributes a colored cluster of trial dots and a square marker at the success-only median.

- **T3 (feature-add).** Opus solo (red) at \$0.17 / 69 s is Pareto-dominant on wall-time and undominated except by Haiku solo on cost. D (orange) is the cost minimum at \$0.08 but ~3× slower. B and C are both Pareto-dominated by A on this task.
- **T2 (refactor).** D (\$0.23 / 507 s) and C (\$0.92 / 275 s) anchor the frontier; A is on the frontier (\$1.11 / 233 s) by being faster than C; B (\$1.38 / 443 s) is dominated.
- **T1 (breakage, 25 errors).** D holds the cost extreme (\$0.30 / 758 s); C takes over (\$1.67 / 400 s) for cloud-only setups; A holds the wall-time extreme (\$1.74 / 253 s); B is dominated on both axes by C. One D trial, one A T2 trial, one B T1 trial, and one D T2 trial fail at the per-arm cap.

### 4.3 Pairwise Mann-Whitney U (cost) per task

Two-sided p-values, normal approximation:

| task | A vs B | A vs C | A vs D | B vs C | B vs D | C vs D |
|------|-------:|-------:|-------:|-------:|-------:|-------:|
| T1   | 0.050  | 0.827  | 0.050  | 0.127  | 0.050  | 0.050  |
| T2   | 0.050  | 0.827  | 0.050  | 0.275  | 0.050  | 0.050  |
| T3   | 0.275  | 0.275  | 0.050  | 0.275  | 0.050  | 0.050  |

Under this approximation, we did not detect a cost difference between A and C on T1 and T2 (p = 0.827). D's cost is at the minimum observable p (= 0.050) against every other arm on every task, but the small sample size limits the strength of this claim. B (Opus + Qwen) is at the same boundary p versus A on T1 and T2, despite Qwen's tokens being free at the meter.

### 4.4 The "free executor" paradox

Compare the per-arm Opus-side token volume `input + cache_read_input` across tasks (success-only median):

| arm role | T1 (Opus in + cache_r) | T2 | T3 |
|----------|----------------------:|---:|---:|
| A (Opus solo) | 534,586 | 226,474 | 13,320 |
| B (Opus orchestrating Qwen) | 733,142 | 313,914 | 62,864 |
| C (Opus orchestrating Haiku) | 421,622 | 159,640 | 44,016 |

The B-over-A ratio of cache_read alone is **1.38× on T1, 1.39× on T2, and 5.26× on T3**. Even though B's executor (Qwen) is free, the orchestrator side of B reads back more cache tokens per iteration than Opus solo. Two observations follow.

First, the multiplier is largest on T3, the smallest task. The base context (system + tools + initial prompt) is amortized across iterations; on long tasks (T1/T2) it is a smaller fraction of total input, so the orchestration overhead is less visible. On short tasks, the overhead dominates.

Second, C (Opus + Haiku) sees a smaller cache_read footprint than A (Opus solo) on T1 and T2 (0.79× and 0.70× of A). The executor in C does substantive work that Opus would otherwise have to do itself, and the executor's *summary* (not its full output) is what flows back into Opus.

The mechanism is therefore not "executor outputs free → orchestrator reads them all." It is "executor outputs summary → orchestrator reads summary, and on small tasks the summary is large relative to the base." This is consistent with our observed cost ordering: B is most expensive on T3 (where the multiplier is 5.3×), and only modestly more expensive than A on T1 (where the multiplier is 1.4×).

## 5. Discussion

### 5.1 Why orchestration loses on dollars in our setup

In a one-shot RouteLLM-style query, the orchestrator's only cost is the routing decision; the chosen model bears the answer-generation cost alone. In an iterative tool-loop, however, the orchestrator must read whatever the executor returns through its `delegate_to_executor` tool — in our implementation, that is a truncated stdout summary (Qwen, up to 4000 chars) or the executor's final text (Haiku, up to 1500 chars), not the executor's full intermediate output. Even so, that returned summary accumulates in the orchestrator's context across 30–80 iterations on T1 and feeds into cache_write and cache_read on every subsequent turn.

A free executor's "free" applies only to that executor's own tokens. The orchestrator's cost grows in proportion to how much it must *re-read* about what the executor did, not how much the executor itself produced.

### 5.2 When orchestration would win

Our setup does not reproduce the regimes in which orchestration is most likely to pay:

- Executors whose returned summaries are tightly bounded — e.g. one structured diff, not free-form prose. Our `qwen-task --agent` wrapper does not enforce that.
- Tasks with many independent sub-problems that can run in parallel under one orchestration. Our three tasks are inherently sequential within a single trial.
- Repeated trials in which the orchestrator can amortize its cache across runs. We reset the harness between trials, so each trial pays its own `cache_write`.

A reasonable next experiment would constrain executor return size to a few hundred tokens per delegation and rerun arm B; we expect the gap to A to narrow, and perhaps invert on T3 specifically.

### 5.3 The cost-reliability tradeoff

The cost ordering D ≪ C ≈ A < B is qualified by reliability. D's per-trial cost advantage on T1 (\$0.30 vs C \$1.67, ratio 5.5×) is bought at a 25% failure rate within our per-arm iteration cap. For a CI pipeline that retries failed runs, the expected cost is roughly `cost_med / success_rate`; D's *expected* T1 cost becomes \$0.40, narrowing the cloud-vs-Haiku gap from 5.5× to 4.2×. For a human in the loop who pays for failed runs as time, the gap is wider.

The right model choice is a function of the cost of failure recovery, not just of median cost per trial.

### 5.4 Performance differs across task types

T3 (feature-add) requires about 6 iterations of edit-test-edit. Within that small budget, Opus's per-iteration efficiency pays for itself: A is undominated on wall-time, iterations, and cloud-only cost simultaneously. T1 (25-error recovery) requires 30–90 iterations regardless of model; here Haiku's lower per-iteration cost dominates the dollar axis, and C — sharing cheap iteration-time costs between Opus and Haiku — is the cheapest cloud-only arm. T2 sits between the two on iteration count, and C narrowly wins the cloud-only cost axis (\$0.92 vs A's \$1.11).

These three task types are not points along a single "complexity" axis we have measured. They differ in iteration count, in the structural specificity of the verifier, and in how much the agent is rewarded for spec-reading versus exploration. We describe the result as "varies across task types" rather than as "rotates with complexity."

The practical guidance we are willing to give is narrower: **use the cheaper-per-iteration model when the task requires many iterations, and consider orchestration when the executor's returned summary can be tightly bounded** — neither of which our arm B reliably delivers.

## 6. Limitations

- **Single repository.** All three tasks are scoped within `typer` v0.26.8. Broader generalization (httpx, click, larger codebases) is future work.
- **Two cloud models.** We compare Anthropic Opus 4.7 and Haiku 4.5 only. Sonnet, GPT-class models, and Gemini are absent.
- **One local executor.** Qwen 3.5-9B is the only local model tested. A 30B-class local model would shift wall-time and possibly executor capability, but not dollar cost.
- **Trial-to-trial variance.** Our n = 3 per cell yields a minimum two-sided Mann-Whitney p of 0.050 under normal approximation. Stronger claims require larger n. Within-cell variance is non-trivial: A T3 iterations were 6 / 6 / 16 across three trials, and C T2 iterations were 17 / 20 / 36 — much wider than a "single converged trajectory" reading would suggest.
- **Sampling non-determinism.** We did not pin `temperature` or `seed` on any Anthropic or Qwen call. Reported variance is sampling-driven and partly an artifact of API defaults.
- **Iteration cap as design variable.** The per-arm cap (table in §3.5) is set by the experimenter. Failures within budget would become successes given a larger cap, and the visible success-rate column is therefore a function of cap policy, not pure model capability.
- **System-prompt asymmetry between solo and orchestrator arms.** A and D's prompts let them edit freely; B and C's orchestrator prompts ask them to avoid direct edits and delegate instead. This is faithful to how the structures are deployed in practice but is a confounder for any "structure alone" comparison.
- **Test fingerprinting (T3).** SHA-256 fingerprinting of the T3 test file biases T3 toward spec-following behavior over exploration.
- **The harness itself.** `mypy + ruff + pytest exit code = 0` is one correctness oracle. Code-review quality, security, and maintainability are not measured here.

## 7. Conclusion

We did not set out to declare a winner. We set out to ask whether the cost gap between "use Opus everywhere" and "use Opus to orchestrate something cheap" is large enough to justify the extra plumbing.

For our particular cheap-executor instantiation — Opus orchestrating local Qwen 3.5-9B (arm B) — the answer is *no on every task we tested*. The mechanism is straightforward: prompt-cached orchestration re-reads the executor's returned summary on every iteration, so an executor that is "free" at the token meter is not free at the orchestrator's input.

The picture is more nuanced for Opus + Haiku (arm C), which beats Opus solo on the cloud-only dollar axis for T2 and ties it for T1. Within the cloud, "orchestrate when the executor is also a competent reasoner" is a defensible heuristic; "orchestrate so the executor can be free" is not in our setup.

The contribution we hope is most reusable is the methodology, not the verdict. A harness-judged comparison cost about \$36 of API time and a few hours of wall-clock to produce twelve cells of Pareto data on a real codebase. The numbers should be small enough for practitioners to run their own comparisons on their own codebases.

---

## Reproducibility

Tested on Ubuntu 22.04 with Python 3.10+ (typer requires `>= 3.10`), `uv` 0.4+, and `anthropic` Python SDK 0.83+. The Qwen executor uses Ollama 0.4+ on a Tailscale-reachable host running model `qwen3.5:9b`, exposed via the `qwen-task --agent` wrapper from `iris-hub/.claude/skills/qwen-task/`.

```bash
# 1. Clone iris-lab + go to experiment dir
git clone https://github.com/kenimo49/iris-lab
cd iris-lab/experiments/025-orchestrator-vs-solo

# 2. Clone base repo (typer at 0.26.8, commit b210c0e)
git clone --depth 1 --branch 0.26.8 https://github.com/tiangolo/typer base-repo/typer
(cd base-repo/typer && uv sync)

# 3. Confirm green base on the harness
./harness.sh --json-only   # expect exit_code=0, 1356 passed

# 4. Provide ANTHROPIC_API_KEY (env or iris-lab/.env)
export ANTHROPIC_API_KEY=...

# 5. (Optional) point at Ollama host for arm B
export OLLAMA_HOST=http://<tailscale-host>:11434

# 6. Run a single trial end-to-end
python -m runners.runner --arm A --task T3 --trial 0

# 7. Full re-run targeting n=3 successes/cell
./runners/batch.sh all 3

# 8. Regenerate tables + Pareto plots
python3 analysis/analyze.py --plot
python3 analysis/export_csv.py
```

For arm B specifically: if Ollama / Tailscale are unavailable, arm B trials will time out at the delegate-tool boundary; arms A, C, D remain runnable.

## Acknowledgements

The `typer` project (Sebastián Ramírez et al., MIT) provided the substrate. The Qwen team open-sourced the model used in arm B. The Codex CLI from OpenAI was used to perform an independent read-only review of this manuscript prior to revision; the review is noted on Zenodo.

## References

- Ong, I., Almahairi, A., et al. *RouteLLM: Learning to Route LLMs with Preference Data.* arXiv:2406.18665, 2024.
- Chen, L., Zaharia, M., Zou, J. *FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving Performance.* arXiv:2305.05176, 2023.
- Wang, J., et al. *Mixture-of-Agents Enhances Large Language Model Capabilities.* arXiv:2406.04692, 2024.
- Shen, Y., et al. *HuggingGPT: Solving AI Tasks with ChatGPT and its Friends in Hugging Face.* arXiv:2303.17580, 2023.
- Wang, G., et al. *Voyager: An Open-Ended Embodied Agent with Large Language Models.* arXiv:2305.16291, 2023.
- Jimenez, C. E., et al. *SWE-bench: Can Language Models Resolve Real-World GitHub Issues?* arXiv:2310.06770, 2024.
