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
MAX_TOOL_CALLS_SIMPLE = 0

# During self-correction, allow more tool calls so the model can look up docs/examples
MAX_TOOL_CALLS_FIX_COMPLEX = 3
MAX_TOOL_CALLS_FIX_SIMPLE = 2
