"""Centralized model configuration for all pipeline agents.

All model name strings and tool-call limits live here so they can be
changed in one place.  The ``PAPER2MANIM_MODEL_OVERRIDE`` env var
(set by the CLI via ``pipeline_runner.py``) is read here and applied
to the primary Claude model.
"""

from __future__ import annotations

import os

# ── Claude models ─────────────────────────────────────────────────────

CLAUDE_OPUS = os.environ.get("PAPER2MANIM_MODEL_OVERRIDE", "claude-opus-4-6")
CLAUDE_SONNET = "claude-sonnet-4-6"

# ── Gemini models ─────────────────────────────────────────────────────

GEMINI_TTS = "gemini-2.5-flash-preview-tts"
GEMINI_PLANNER_LITE = "gemini-3.1-pro-preview"

# ── Coder tool-call limits ────────────────────────────────────────────

MAX_TOOL_CALLS_COMPLEX = 2
MAX_TOOL_CALLS_MEDIUM = 1
MAX_TOOL_CALLS_SIMPLE = 0

# During self-correction, allow more tool calls so the model can look up docs/examples
MAX_TOOL_CALLS_FIX_COMPLEX = 3
MAX_TOOL_CALLS_FIX_MEDIUM = 2
MAX_TOOL_CALLS_FIX_SIMPLE = 2


# ── Token usage tracking ─────────────────────────────────────────────

def new_token_counter() -> dict:
    """Return a fresh mutable token counter dict."""
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "api_calls": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


def merge_token_usage(target: dict, source: dict) -> None:
    """Add source counters into target (in place)."""
    target["input_tokens"] += source.get("input_tokens", 0)
    target["output_tokens"] += source.get("output_tokens", 0)
    target["api_calls"] += source.get("api_calls", 0)
    target["cache_creation_input_tokens"] += source.get("cache_creation_input_tokens", 0)
    target["cache_read_input_tokens"] += source.get("cache_read_input_tokens", 0)


# ── Cost estimation ──────────────────────────────────────────────────

# Approximate rates in USD per token (as of early 2025).
# These are estimates and may not reflect current pricing.
MODEL_RATES: dict[str, tuple[float, float]] = {
    "claude-opus-4-6":   (15.0 / 1_000_000, 75.0 / 1_000_000),   # $15/M in, $75/M out
    "claude-sonnet-4-6": (3.0 / 1_000_000,  15.0 / 1_000_000),   # $3/M in,  $15/M out
}


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str = "claude-opus-4-6",
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Rough cost estimate in USD based on token counts and model.

    When prompt caching is active, ``cache_creation_tokens`` are charged at
    1.25x the base input rate and ``cache_read_tokens`` at 0.1x.  The
    remaining ``input_tokens`` (uncached) are charged at the standard rate.
    """
    in_rate, out_rate = MODEL_RATES.get(model, MODEL_RATES["claude-opus-4-6"])
    cost = output_tokens * out_rate
    # Uncached input tokens at standard rate
    cost += input_tokens * in_rate
    # Cache write: 1.25x base input rate
    cost += cache_creation_tokens * in_rate * 1.25
    # Cache read: 0.1x base input rate
    cost += cache_read_tokens * in_rate * 0.1
    return cost
