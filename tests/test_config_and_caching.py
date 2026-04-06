"""Tests for agents.config — token counters, cost estimation, and model routing."""

from __future__ import annotations

from agents.config import (
    DEFAULT_MODEL_PROFILE,
    OPENAI_GPT_53_CODEX,
    OPENAI_GPT_54,
    estimate_cost,
    merge_token_usage,
    new_token_counter,
    resolve_stage_model,
)


# ---------------------------------------------------------------------------
# new_token_counter
# ---------------------------------------------------------------------------

def test_token_counter_has_cache_fields():
    counter = new_token_counter()
    assert "cached_input_tokens" in counter
    assert "cache_creation_input_tokens" in counter
    assert "cache_read_input_tokens" in counter
    assert counter["cached_input_tokens"] == 0
    assert counter["cache_creation_input_tokens"] == 0
    assert counter["cache_read_input_tokens"] == 0


def test_token_counter_has_standard_fields():
    counter = new_token_counter()
    assert counter["input_tokens"] == 0
    assert counter["output_tokens"] == 0
    assert counter["api_calls"] == 0


# ---------------------------------------------------------------------------
# merge_token_usage
# ---------------------------------------------------------------------------

def test_merge_includes_cache_fields():
    target = new_token_counter()
    source = {
        "input_tokens": 100,
        "output_tokens": 50,
        "api_calls": 1,
        "cache_creation_input_tokens": 200,
        "cache_read_input_tokens": 300,
    }
    merge_token_usage(target, source)
    assert target["cache_creation_input_tokens"] == 200
    assert target["cache_read_input_tokens"] == 300
    assert target["input_tokens"] == 100


def test_merge_handles_missing_cache_fields():
    target = new_token_counter()
    source = {"input_tokens": 10, "output_tokens": 5, "api_calls": 1}
    merge_token_usage(target, source)
    assert target["cache_creation_input_tokens"] == 0
    assert target["cache_read_input_tokens"] == 0


# ---------------------------------------------------------------------------
# estimate_cost
# ---------------------------------------------------------------------------

def test_estimate_cost_basic():
    cost = estimate_cost(1000, 500, model="claude-opus-4-6")
    assert cost > 0


def test_estimate_cost_with_cache_read():
    # Cache reads are 0.1x base rate, so should be much cheaper
    cost_no_cache = estimate_cost(1000, 500, model="claude-opus-4-6")
    cost_with_cache = estimate_cost(
        0, 500, model="claude-opus-4-6",
        cache_read_tokens=1000,
    )
    assert cost_with_cache < cost_no_cache


def test_estimate_cost_with_cache_creation():
    # Cache creation is 1.25x base rate
    cost_no_cache = estimate_cost(1000, 500, model="claude-opus-4-6")
    cost_with_creation = estimate_cost(
        0, 500, model="claude-opus-4-6",
        cache_creation_tokens=1000,
    )
    assert cost_with_creation > cost_no_cache * 0.5  # creation is 1.25x, so > half


def test_estimate_cost_zero_tokens():
    assert estimate_cost(0, 0) == 0.0


def test_estimate_cost_openai_cached_input_is_discounted():
    cost_no_cache = estimate_cost(1000, 500, model=OPENAI_GPT_54)
    cost_with_cache = estimate_cost(1000, 500, model=OPENAI_GPT_54, cached_input_tokens=800)
    assert cost_with_cache < cost_no_cache


# ---------------------------------------------------------------------------
# Model routing (medium tier)
# ---------------------------------------------------------------------------

def test_model_routing_medium():
    from agents.coder import _get_model_for_complexity

    assert _get_model_for_complexity("medium") == OPENAI_GPT_53_CODEX


def test_model_routing_complex():
    from agents.coder import _get_model_for_complexity

    assert _get_model_for_complexity("complex") == OPENAI_GPT_53_CODEX


def test_tool_budget_medium():
    from agents.coder import _get_tool_budget
    from agents.config import MAX_TOOL_CALLS_MEDIUM, MAX_TOOL_CALLS_FIX_MEDIUM

    assert _get_tool_budget("medium") == MAX_TOOL_CALLS_MEDIUM
    assert _get_tool_budget("medium", fix=True) == MAX_TOOL_CALLS_FIX_MEDIUM


def test_default_profile_is_openai():
    plan_cfg = resolve_stage_model("plan", profile=DEFAULT_MODEL_PROFILE)
    assert plan_cfg.model == OPENAI_GPT_54
    assert plan_cfg.provider == "openai"
