"""Agent loops: solo (single Anthropic model) and orchestrated (Opus + executor).

Executor variants:
- AnthropicExecutor: a Haiku (or any Anthropic model) sub-loop with full tool access.
- QwenExecutor:      spawns qwen-task.sh --agent in the repo dir.

Token usage is accumulated per role into the returned dict; the runner attributes
$ cost from there.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from . import task_prompts
from .costs import usd_cost
from .tools import TOOL_SCHEMAS, ToolExecutor

OPUS = "claude-opus-4-7"
HAIKU = "claude-haiku-4-5-20251001"

QWEN_TASK_SH = "/home/iris/repos/iris-hub/.claude/skills/qwen-task/qwen-task.sh"


def _empty_usage() -> dict:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


def _accumulate(acc: dict, u) -> None:
    """Accumulate usage from anthropic.types.Usage into acc dict."""
    for k in acc:
        v = getattr(u, k, 0) or 0
        acc[k] += v


@dataclass
class TrialResult:
    arm: str
    task: str
    trial: int
    success: bool
    wall_sec: float
    iterations: int
    blocked: bool = False
    usage_by_role: dict = field(default_factory=dict)
    cost_usd_by_role: dict = field(default_factory=dict)
    total_cost_usd: float = 0.0
    verify_final: dict = field(default_factory=dict)
    error: str | None = None

    def to_jsonl(self) -> str:
        return json.dumps(
            {
                "arm": self.arm,
                "task": self.task,
                "trial": self.trial,
                "success": self.success,
                "blocked": self.blocked,
                "wall_sec": round(self.wall_sec, 2),
                "iterations": self.iterations,
                "usage_by_role": self.usage_by_role,
                "cost_usd_by_role": {k: round(v, 6) for k, v in self.cost_usd_by_role.items()},
                "total_cost_usd": round(self.total_cost_usd, 6),
                "verify_final": self.verify_final,
                "error": self.error,
            },
            ensure_ascii=False,
        )


def _anthropic_client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        # Try iris-lab .env
        env = Path("/home/iris/repos/iris-lab/.env")
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip("'\"")
                    break
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not found in env or iris-lab/.env")
    return anthropic.Anthropic(api_key=key)


def _with_cache(blocks: list, on_last: bool = True) -> list:
    """Add ephemeral cache_control to the last text/tool_result block in blocks."""
    if not on_last or not blocks:
        return blocks
    # Find the last cacheable block (must be a dict with type)
    for i in range(len(blocks) - 1, -1, -1):
        b = blocks[i]
        if isinstance(b, dict) and b.get("type") in ("text", "tool_result"):
            b = dict(b)
            b["cache_control"] = {"type": "ephemeral"}
            blocks = list(blocks)
            blocks[i] = b
            return blocks
    return blocks


def _tool_loop(
    client: anthropic.Anthropic,
    model: str,
    system: str,
    user_prompt: str,
    tool_schemas: list[dict],
    tool_runner,
    max_iters: int = 40,
    max_tokens: int = 4096,
    usage_acc: dict | None = None,
    extra_tool_handler=None,
) -> tuple[str, int, dict]:
    """Run a tool-use loop until the model emits a non-tool stop_reason.

    Returns (final_text, iterations, usage_acc).
    `tool_runner` handles str_replace_editor + bash. `extra_tool_handler(name, args)
    -> (str, bool)|None` lets orchestrator hook in `delegate_to_executor`.

    Prompt caching: system + tools are cached statically; the latest user
    message in messages history is cache-marked on each turn so prior turns
    are read from cache.
    """
    if usage_acc is None:
        usage_acc = _empty_usage()
    messages = [{"role": "user", "content": user_prompt}]

    # static cache: system + tools
    system_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    cached_tools = [dict(t) for t in tool_schemas]
    cached_tools[-1] = {**cached_tools[-1], "cache_control": {"type": "ephemeral"}}

    iterations = 0
    final_text = ""
    while iterations < max_iters:
        iterations += 1
        # Mark latest user-side content (tool_result list, or initial string) for caching
        send_messages = [dict(m) for m in messages]
        last = send_messages[-1]
        if last["role"] == "user":
            content = last["content"]
            if isinstance(content, str):
                last["content"] = [
                    {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}
                ]
            elif isinstance(content, list):
                last["content"] = _with_cache(content)
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_blocks,
            tools=cached_tools,
            messages=send_messages,
        )
        _accumulate(usage_acc, resp.usage)
        assistant_blocks = []
        tool_uses = []
        text_chunks = []
        for block in resp.content:
            if block.type == "text":
                assistant_blocks.append({"type": "text", "text": block.text})
                text_chunks.append(block.text)
            elif block.type == "tool_use":
                assistant_blocks.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )
                tool_uses.append(block)
        messages.append({"role": "assistant", "content": assistant_blocks})
        final_text = "\n".join(text_chunks)

        if resp.stop_reason != "tool_use":
            break

        tool_results = []
        for tu in tool_uses:
            out, is_err = (None, False)
            if extra_tool_handler is not None:
                handled = extra_tool_handler(tu.name, tu.input)
                if handled is not None:
                    out, is_err = handled
            if out is None:
                out, is_err = tool_runner.run(tu.name, tu.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": out or "[empty]",
                    "is_error": is_err,
                }
            )
        messages.append({"role": "user", "content": tool_results})

    return final_text, iterations, usage_acc


def _qwen_delegate(repo_root: Path, instruction: str, timeout: int = 600) -> str:
    """Spawn qwen-task.sh --agent in repo_root with the given instruction.

    Returns truncated stdout/stderr summary. Token cost = 0 (local).
    """
    try:
        p = subprocess.run(
            [QWEN_TASK_SH, "--agent", "--dir", str(repo_root), instruction],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (p.stdout or "") + ("\n--- stderr ---\n" + p.stderr if p.stderr else "")
        if len(out) > 4000:
            out = out[:2000] + "\n[... truncated ...]\n" + out[-2000:]
        return out + f"\n[qwen exit={p.returncode}]"
    except subprocess.TimeoutExpired:
        return f"qwen executor TIMEOUT after {timeout}s"
    except Exception as e:
        return f"qwen executor exception: {e}"


def _haiku_delegate(
    client: anthropic.Anthropic,
    repo_root: Path,
    instruction: str,
    usage_acc: dict,
    tool_runner: ToolExecutor,
    max_iters: int = 20,
) -> str:
    """Spawn a Haiku tool-loop with the instruction. Accumulates Haiku tokens."""
    final, iters, _ = _tool_loop(
        client=client,
        model=HAIKU,
        system=task_prompts.SYSTEM_EXECUTOR,
        user_prompt=instruction,
        tool_schemas=TOOL_SCHEMAS,
        tool_runner=tool_runner,
        max_iters=max_iters,
        max_tokens=4096,
        usage_acc=usage_acc,
    )
    return f"executor ({iters} iters): {final[:1500]}"


DELEGATE_TOOL = {
    "name": "delegate_to_executor",
    "description": (
        "Hand a concrete instruction to the executor LLM. The executor will edit "
        "files / run commands as instructed and return a summary. Be precise: "
        "name files, name functions, name the exact change."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "instruction": {
                "type": "string",
                "description": "Concrete instruction for the executor.",
            },
        },
        "required": ["instruction"],
    },
}


def run_solo(model: str, task: str, repo_root: Path, max_iters: int = 40) -> tuple[str, int, dict]:
    """Arm A (Opus) / Arm D (Haiku): single model with full tool access."""
    client = _anthropic_client()
    runner = ToolExecutor(repo_root=repo_root)
    usage = _empty_usage()
    final, iters, _ = _tool_loop(
        client=client,
        model=model,
        system=task_prompts.SYSTEM_SOLO,
        user_prompt=task_prompts.PROMPTS[task],
        tool_schemas=TOOL_SCHEMAS,
        tool_runner=runner,
        max_iters=max_iters,
        usage_acc=usage,
    )
    return final, iters, {model: usage}


def run_orchestrated(
    orchestrator: str,
    executor_kind: str,
    task: str,
    repo_root: Path,
    max_iters: int = 30,
    max_exec_iters: int = 20,
) -> tuple[str, int, dict]:
    """Arm B (Opus+Qwen) / Arm C (Opus+Haiku).

    executor_kind: 'qwen' or 'haiku'.
    """
    client = _anthropic_client()
    runner = ToolExecutor(repo_root=repo_root)
    orch_usage = _empty_usage()
    exec_usage = _empty_usage()

    def handler(name: str, args: dict):
        if name != "delegate_to_executor":
            return None
        instr = args.get("instruction", "")
        if not instr:
            return ("instruction empty", True)
        if executor_kind == "qwen":
            return (_qwen_delegate(repo_root, instr), False)
        if executor_kind == "haiku":
            return (
                _haiku_delegate(client, repo_root, instr, exec_usage, runner, max_exec_iters),
                False,
            )
        return (f"unknown executor_kind: {executor_kind}", True)

    schemas = TOOL_SCHEMAS + [DELEGATE_TOOL]
    final, iters, _ = _tool_loop(
        client=client,
        model=orchestrator,
        system=task_prompts.SYSTEM_ORCHESTRATOR,
        user_prompt=task_prompts.PROMPTS[task],
        tool_schemas=schemas,
        tool_runner=runner,
        max_iters=max_iters,
        usage_acc=orch_usage,
        extra_tool_handler=handler,
    )

    usage = {orchestrator: orch_usage}
    if executor_kind == "qwen":
        usage["qwen-local"] = _empty_usage()
    else:
        usage[HAIKU] = exec_usage
    return final, iters, usage


def trial(arm: str, task: str, trial_id: int, repo_root: Path, max_iters: int | None = None) -> TrialResult:
    from . import harness_io

    t0 = time.time()
    harness_io.setup_task(task)
    # Defaults per arm; allow override
    default_iters = {"A": 40, "B": 60, "C": 40, "D": 80}[arm]
    mi = max_iters if max_iters is not None else default_iters
    try:
        if arm == "A":
            final, iters, usage = run_solo(OPUS, task, repo_root, max_iters=mi)
        elif arm == "B":
            final, iters, usage = run_orchestrated(OPUS, "qwen", task, repo_root, max_iters=mi)
        elif arm == "C":
            final, iters, usage = run_orchestrated(OPUS, "haiku", task, repo_root, max_iters=mi)
        elif arm == "D":
            final, iters, usage = run_solo(HAIKU, task, repo_root, max_iters=mi)
        else:
            raise ValueError(f"unknown arm: {arm}")
    except Exception as e:
        return TrialResult(
            arm=arm,
            task=task,
            trial=trial_id,
            success=False,
            wall_sec=time.time() - t0,
            iterations=0,
            error=f"{type(e).__name__}: {e}",
        )

    verify = harness_io.verify_task(task)
    success = verify.get("exit_code", 1) == 0
    blocked = "BLOCKED" in (final or "").upper()[:200]

    cost_by_role = {m: usd_cost(m, u) for m, u in usage.items()}
    return TrialResult(
        arm=arm,
        task=task,
        trial=trial_id,
        success=success,
        blocked=blocked,
        wall_sec=time.time() - t0,
        iterations=iters,
        usage_by_role=usage,
        cost_usd_by_role=cost_by_role,
        total_cost_usd=sum(cost_by_role.values()),
        verify_final={
            "exit_code": verify.get("exit_code"),
            "summary": harness_io.summarize_harness(verify),
        },
    )
