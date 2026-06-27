"""Pricing constants ($USD per 1M tokens, public rate card as of 2026-06).

Sources:
- Claude Opus 4.7: $15/M input, $75/M output. Prompt caching: write = base × 1.25, read = base × 0.10.
- Claude Haiku 4.5: $1/M input, $5/M output. Prompt caching: same multipliers.
- Qwen (local Ollama, exp021/exp024 stack): marginal cost 0 (electricity ignored).
"""

_OPUS = {
    "input": 15.0,
    "output": 75.0,
    "cache_write": 15.0 * 1.25,
    "cache_read": 15.0 * 0.10,
}
_HAIKU = {
    "input": 1.0,
    "output": 5.0,
    "cache_write": 1.0 * 1.25,
    "cache_read": 1.0 * 0.10,
}
_ZERO = {"input": 0.0, "output": 0.0, "cache_write": 0.0, "cache_read": 0.0}

PRICING = {
    "claude-opus-4-7": _OPUS,
    "claude-opus-4-7-20251123": _OPUS,
    "claude-haiku-4-5": _HAIKU,
    "claude-haiku-4-5-20251001": _HAIKU,
    "qwen-local": _ZERO,
}


def usd_cost(model: str, usage: dict) -> float:
    """Compute $ cost from usage dict {input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens}."""
    p = PRICING[model]
    return (
        usage.get("input_tokens", 0) * p["input"]
        + usage.get("output_tokens", 0) * p["output"]
        + usage.get("cache_creation_input_tokens", 0) * p["cache_write"]
        + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
    ) / 1_000_000
