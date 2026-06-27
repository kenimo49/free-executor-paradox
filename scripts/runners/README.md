# runners/

4-arm runner implementation for exp025.

## quick start

```bash
# Setup: API key must be loadable (either in env or in /home/iris/repos/iris-lab/.env)
# typer base-repo must exist at base-repo/typer (see base-repo/BASE_VERIFICATION.md)

# Dry run (sets up repo, prints task prompt, no API call)
python -m runners.runner --arm A --task T3 --trial 0 --dry-run

# Real trial — appends to results/{arm}.jsonl
python -m runners.runner --arm A --task T3 --trial 0
```

## 4 arm layout

| arm | orchestrator | executor | implementation |
|-----|-------------|---------|----------------|
| A | Opus 4.7 | (solo) | `run_solo(OPUS, ...)` |
| B | Opus 4.7 | Qwen (local, qwen-task.sh agent mode) | `run_orchestrated(OPUS, "qwen", ...)` |
| C | Opus 4.7 | Haiku 4.5 (Anthropic SDK sub-loop) | `run_orchestrated(OPUS, "haiku", ...)` |
| D | Haiku 4.5 | (solo) | `run_solo(HAIKU, ...)` |

The orchestrator gets an extra `delegate_to_executor` tool. In Arm B, that tool
shells out to `qwen-task.sh --agent --dir <repo>`. In Arm C, it spins up a Haiku
tool-loop. Solo arms get `str_replace_editor` + `bash` directly.

## tools exposed to the agent

- `str_replace_editor` (view / create / str_replace / insert) — path-scoped to typer repo root
- `bash` — runs in typer repo root, 120s timeout per call
- `delegate_to_executor` (orchestrator only)

## prompt caching

`system` + `tools` + the latest user message get `cache_control: ephemeral` markers.
For the Haiku solo arm on T3 we observed:

- without caching: 183k input tokens, $0.20
- with caching: 21k regular + 15k cache write + 213k cache read, $0.08 (58% reduction)

## one-trial-per-arm baseline (T3 only)

Validated 2026-06-27 (n=1, not statistically meaningful, just smoke-test):

| arm | wall_sec | iterations | cost_usd | verify |
|-----|----------|------------|----------|--------|
| A | 60 | 6 | 0.17 | ✓ |
| B | 348 | 12 | 0.42 | ✓ |
| C | 130 | 9 | 0.35 | ✓ |
| D | 168 | 29 | 0.08 | ✓ |

T3 is small enough that Opus-solo dominates the Pareto frontier on $ / wall / iters
simultaneously. T1 (breakage recovery) is expected to flip parts of this.

## file layout

- `runner.py` — CLI entry, dispatches to `agent.trial(arm, task, trial_id, repo_root)`
- `agent.py` — `_tool_loop`, `run_solo`, `run_orchestrated`, `TrialResult`
- `tools.py` — `TOOL_SCHEMAS`, `ToolExecutor` (str_replace_editor + bash impls)
- `harness_io.py` — `setup_task`, `verify_task`, JSON parsing
- `task_prompts.py` — system prompts (SOLO / ORCHESTRATOR / EXECUTOR) + task descriptions
- `costs.py` — public rate-card pricing for cost computation

## known issues / future work

- No retry / resume of partial trials. If a trial crashes mid-loop, just re-run.
- `max_iters` is hard-coded (40 solo, 30 orchestrator). Tasks may need tuning.
- T1 hasn't been validated yet (the long one).
- Cost computation assumes public rate-card. If subscription billing is in effect,
  treat $ as "fair-comparison units" rather than actual spend.
