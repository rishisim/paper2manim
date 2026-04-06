"""Centralized model configuration, profiles, and token-cost helpers."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from typing import Any

# ── Provider / model constants ──────────────────────────────────────────────

OPENAI_GPT_54 = "gpt-5.4"
OPENAI_GPT_53_CODEX = "gpt-5.3-codex"
OPENAI_GPT_54_MINI = "gpt-5.4-mini"

CLAUDE_OPUS = "claude-opus-4-6"
CLAUDE_SONNET = "claude-sonnet-4-6"
CLAUDE_HAIKU = "claude-haiku-4-5-20251001"

DEFAULT_MODEL_PROFILE = "openai-default"
FALLBACK_MODEL_PROFILE = "anthropic-legacy"

# ── Gemini models ───────────────────────────────────────────────────────────

GEMINI_TTS = "gemini-2.5-flash-preview-tts"
GEMINI_PLANNER_LITE = "gemini-3.1-pro-preview"

# ── Coder tool-call limits ──────────────────────────────────────────────────

MAX_TOOL_CALLS_COMPLEX = 2
MAX_TOOL_CALLS_MEDIUM = 1
MAX_TOOL_CALLS_SIMPLE = 0

MAX_TOOL_CALLS_FIX_COMPLEX = 3
MAX_TOOL_CALLS_FIX_MEDIUM = 2
MAX_TOOL_CALLS_FIX_SIMPLE = 2


@dataclass(frozen=True)
class StageModelConfig:
    provider: str
    model: str
    reasoning_effort: str | None = None
    cache_retention: str | None = None
    cache_key_prefix: str = ""


MODEL_PROFILES: dict[str, dict[str, StageModelConfig]] = {
    DEFAULT_MODEL_PROFILE: {
        "plan": StageModelConfig("openai", OPENAI_GPT_54, "medium", "24h", "planner"),
        "code": StageModelConfig("openai", OPENAI_GPT_53_CODEX, "high", "in_memory", "coder"),
        "verify": StageModelConfig("openai", OPENAI_GPT_54_MINI, "low", "in_memory", "verify"),
        "vision": StageModelConfig("openai", OPENAI_GPT_54_MINI, "low", "in_memory", "critique"),
    },
    FALLBACK_MODEL_PROFILE: {
        "plan": StageModelConfig("anthropic", CLAUDE_SONNET, None, None, "planner"),
        "code": StageModelConfig("anthropic", CLAUDE_OPUS, None, None, "coder"),
        "verify": StageModelConfig("anthropic", CLAUDE_SONNET, None, None, "verify"),
        "vision": StageModelConfig("anthropic", CLAUDE_SONNET, None, None, "critique"),
    },
}

MODEL_PROFILE_ALIASES = {
    "openai": DEFAULT_MODEL_PROFILE,
    "anthropic": FALLBACK_MODEL_PROFILE,
    "opus": FALLBACK_MODEL_PROFILE,
    "sonnet": FALLBACK_MODEL_PROFILE,
}

_STAGE_OVERRIDE_ENV = {
    "plan": "PAPER2MANIM_STAGE_MODEL_PLAN",
    "code": "PAPER2MANIM_STAGE_MODEL_CODE",
    "verify": "PAPER2MANIM_STAGE_MODEL_VERIFY",
    "vision": "PAPER2MANIM_STAGE_MODEL_VISION",
}


# ── Token usage tracking ────────────────────────────────────────────────────

def new_token_counter() -> dict[str, Any]:
    """Return a fresh mutable token counter dict."""
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_input_tokens": 0,
        "api_calls": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "fallback_invocations": 0,
    }


def merge_token_usage(target: dict[str, Any], source: dict[str, Any]) -> None:
    """Add source counters into target (in place)."""
    for field in (
        "input_tokens",
        "output_tokens",
        "cached_input_tokens",
        "api_calls",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "fallback_invocations",
    ):
        target[field] = target.get(field, 0) + source.get(field, 0)


# ── Cost estimation ─────────────────────────────────────────────────────────

MODEL_RATES: dict[str, dict[str, float]] = {
    CLAUDE_OPUS: {
        "input": 5.0 / 1_000_000,
        "output": 25.0 / 1_000_000,
        "cache_creation_multiplier": 1.25,
        "cache_read_multiplier": 0.10,
    },
    CLAUDE_SONNET: {
        "input": 3.0 / 1_000_000,
        "output": 15.0 / 1_000_000,
        "cache_creation_multiplier": 1.25,
        "cache_read_multiplier": 0.10,
    },
    OPENAI_GPT_54: {
        "input": 2.50 / 1_000_000,
        "cached_input": 0.25 / 1_000_000,
        "output": 15.0 / 1_000_000,
    },
    OPENAI_GPT_53_CODEX: {
        "input": 1.75 / 1_000_000,
        "cached_input": 0.175 / 1_000_000,
        "output": 14.0 / 1_000_000,
    },
    OPENAI_GPT_54_MINI: {
        "input": 0.75 / 1_000_000,
        "cached_input": 0.08 / 1_000_000,
        "output": 4.50 / 1_000_000,
    },
}


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str = CLAUDE_OPUS,
    cached_input_tokens: int = 0,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Rough cost estimate in USD based on token counts and model."""
    rates = MODEL_RATES.get(model, MODEL_RATES[CLAUDE_OPUS])
    cost = output_tokens * rates["output"]

    if "cached_input" in rates:
        uncached_input_tokens = max(input_tokens - cached_input_tokens, 0)
        cost += uncached_input_tokens * rates["input"]
        cost += cached_input_tokens * rates["cached_input"]
    else:
        cost += input_tokens * rates["input"]
        cost += cache_creation_tokens * rates["input"] * rates.get("cache_creation_multiplier", 1.25)
        cost += cache_read_tokens * rates["input"] * rates.get("cache_read_multiplier", 0.10)

    return cost


def estimate_cache_savings(model: str, cached_input_tokens: int = 0, cache_read_tokens: int = 0) -> float:
    """Estimate the savings from cached input tokens."""
    rates = MODEL_RATES.get(model, MODEL_RATES[CLAUDE_OPUS])
    if cached_input_tokens and "cached_input" in rates:
        return cached_input_tokens * max(rates["input"] - rates["cached_input"], 0.0)
    if cache_read_tokens:
        read_rate = rates["input"] * rates.get("cache_read_multiplier", 0.10)
        return cache_read_tokens * max(rates["input"] - read_rate, 0.0)
    return 0.0


# ── Model/profile resolution ─────────────────────────────────────────────────

def normalize_model_selection(value: str | None) -> str:
    if not value:
        return DEFAULT_MODEL_PROFILE
    low = value.strip().lower()
    return MODEL_PROFILE_ALIASES.get(low, value.strip())


def infer_provider(model: str) -> str:
    if model.startswith("claude-"):
        return "anthropic"
    return "openai"


def get_model_profile() -> str:
    configured = os.environ.get("PAPER2MANIM_MODEL_PROFILE")
    return normalize_model_selection(configured)


def get_system_prompt_prefix() -> str:
    return (os.environ.get("PAPER2MANIM_SYSTEM_PROMPT_PREFIX") or "").strip()


def model_profile_summary(profile: str | None = None) -> dict[str, str]:
    active = normalize_model_selection(profile or get_model_profile())
    plan_cfg = resolve_stage_model("plan", profile=active)
    code_cfg = resolve_stage_model("code", profile=active)
    verify_cfg = resolve_stage_model("verify", profile=active)
    vision_cfg = resolve_stage_model("vision", profile=active)
    return {
        "profile": active,
        "plan": f"{plan_cfg.provider}:{plan_cfg.model}",
        "code": f"{code_cfg.provider}:{code_cfg.model}",
        "verify": f"{verify_cfg.provider}:{verify_cfg.model}",
        "vision": f"{vision_cfg.provider}:{vision_cfg.model}",
    }


def _override_for_stage(stage: str) -> str | None:
    explicit = os.environ.get(_STAGE_OVERRIDE_ENV[stage])
    if explicit:
        return explicit.strip()
    legacy = (os.environ.get("PAPER2MANIM_MODEL_OVERRIDE") or "").strip()
    if legacy and stage in {"plan", "code"}:
        return legacy
    return None


def resolve_stage_model(
    stage: str,
    *,
    complexity: str = "complex",
    fix: bool = False,
    profile: str | None = None,
) -> StageModelConfig:
    active = normalize_model_selection(profile or get_model_profile())
    profile_cfg = MODEL_PROFILES.get(active, MODEL_PROFILES[DEFAULT_MODEL_PROFILE])
    base = profile_cfg[stage]
    override = _override_for_stage(stage)
    provider = infer_provider(override) if override else base.provider
    model = override or base.model
    reasoning_effort = base.reasoning_effort
    cache_retention = base.cache_retention
    cache_key_prefix = base.cache_key_prefix

    if stage == "code" and provider == "openai":
        reasoning_effort = "high" if fix or complexity == "complex" else "medium"

    return StageModelConfig(
        provider=provider,
        model=model,
        reasoning_effort=reasoning_effort,
        cache_retention=cache_retention,
        cache_key_prefix=cache_key_prefix,
    )


def resolve_fallback_stage_model(
    stage: str,
    *,
    complexity: str = "complex",
    fix: bool = False,
    profile: str | None = None,
) -> StageModelConfig | None:
    active = normalize_model_selection(profile or get_model_profile())
    fallback_profile = FALLBACK_MODEL_PROFILE if active == DEFAULT_MODEL_PROFILE else DEFAULT_MODEL_PROFILE
    fallback_cfg = resolve_stage_model(stage, complexity=complexity, fix=fix, profile=fallback_profile)
    primary_cfg = resolve_stage_model(stage, complexity=complexity, fix=fix, profile=active)
    if (fallback_cfg.provider, fallback_cfg.model) == (primary_cfg.provider, primary_cfg.model):
        return None
    return fallback_cfg


def build_prompt_cache_key(prefix: str, *parts: str) -> str:
    clean_parts = [prefix] + [part for part in parts if part]
    digest = hashlib.sha256("::".join(clean_parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"
