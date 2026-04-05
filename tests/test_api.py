"""Tests for the agents.coder module — model config, tool definitions, and helpers.

Does NOT make real API calls; all Anthropic interactions are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

def test_model_constants_exist():
    from agents.config import CLAUDE_OPUS as MODEL_PRO, CLAUDE_SONNET as MODEL_FAST

    assert isinstance(MODEL_PRO, str) and len(MODEL_PRO) > 0
    assert isinstance(MODEL_FAST, str) and len(MODEL_FAST) > 0
    assert MODEL_PRO != MODEL_FAST


def test_get_model_for_complexity_complex():
    from agents.coder import _get_model_for_complexity
    from agents.config import CLAUDE_OPUS as MODEL_PRO

    assert _get_model_for_complexity("complex") == MODEL_PRO


def test_get_model_for_complexity_simple():
    from agents.coder import _get_model_for_complexity
    from agents.config import CLAUDE_SONNET as MODEL_FAST

    assert _get_model_for_complexity("simple") == MODEL_FAST


def test_get_model_for_complexity_default():
    from agents.coder import _get_model_for_complexity
    from agents.config import CLAUDE_OPUS as MODEL_PRO

    assert _get_model_for_complexity() == MODEL_PRO


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

def test_build_tools_returns_list():
    from agents.coder import _build_tools

    tools = _build_tools()
    assert isinstance(tools, list)
    assert len(tools) >= 1


def test_build_tools_have_required_fields():
    from agents.coder import _build_tools

    tools = _build_tools()
    for tool in tools:
        assert "name" in tool, f"Tool missing 'name': {tool}"
        assert "description" in tool, f"Tool missing 'description': {tool}"
        assert "input_schema" in tool, f"Tool missing 'input_schema': {tool}"
        schema = tool["input_schema"]
        assert schema.get("type") == "object", f"Tool '{tool['name']}' schema type is not 'object'"


def test_build_tools_known_names():
    """All expected tool names are present."""
    from agents.coder import _build_tools

    tool_names = {t["name"] for t in _build_tools()}
    expected = {"fetch_manim_docs", "fetch_manim_file", "search_web"}
    assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"


# ---------------------------------------------------------------------------
# Code-fence stripping
# ---------------------------------------------------------------------------

def test_strip_code_fences_with_python_fences():
    from agents.coder import _strip_code_fences

    raw = '```python\nfrom manim import *\nclass A(Scene): pass\n```'
    result = _strip_code_fences(raw)
    assert result.startswith("from manim import *")
    assert "```" not in result


def test_strip_code_fences_no_fences():
    from agents.coder import _strip_code_fences

    raw = "from manim import *\nclass A(Scene): pass"
    result = _strip_code_fences(raw)
    assert result == raw


def test_strip_code_fences_plain_fences():
    from agents.coder import _strip_code_fences

    raw = '```\nfrom manim import *\n```'
    result = _strip_code_fences(raw)
    assert "```" not in result
    assert "from manim import *" in result


# ---------------------------------------------------------------------------
# Error compaction
# ---------------------------------------------------------------------------

def test_compact_error_empty():
    from agents.coder import _compact_error

    assert _compact_error("") == "No error output was captured."
    assert _compact_error(None) == "No error output was captured."


def test_compact_error_preserves_traceback():
    from agents.coder import _compact_error

    error = (
        "Traceback (most recent call last):\n"
        '  File "scene.py", line 10\n'
        "NameError: name 'foo' is not defined\n"
    )
    result = _compact_error(error)
    assert "Traceback" in result
    assert "NameError" in result


# ---------------------------------------------------------------------------
# Tool dispatch (mocked)
# ---------------------------------------------------------------------------

def test_dispatch_tool_call_unknown():
    from agents.coder import _dispatch_tool_call

    result = _dispatch_tool_call("nonexistent_tool", {})
    assert "Unknown tool" in result


@patch("agents.coder.fetch_manim_docs", return_value="doc text")
def test_dispatch_tool_call_fetch_docs(mock_docs):
    from agents.coder import _dispatch_tool_call

    result = _dispatch_tool_call("fetch_manim_docs", {"topic": "circle"})
    assert result == "doc text"
    mock_docs.assert_called_once_with(topic="circle")


@patch("agents.coder.search_web", return_value="search results")
def test_dispatch_tool_call_search_web(mock_search):
    from agents.coder import _dispatch_tool_call

    result = _dispatch_tool_call("search_web", {"query": "manim 3D"})
    assert result == "search results"
    mock_search.assert_called_once_with(query="manim 3D")


# ---------------------------------------------------------------------------
# run_coder_agent yields expected structure (mocked API)
# ---------------------------------------------------------------------------

def _make_mock_response(text: str = "from manim import *\nclass S(Scene):\n  def construct(self): pass"):
    """Create a mock Anthropic Messages response with a single text block."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = "end_turn"
    return resp


@patch("agents.coder.run_manim_code")
@patch("agents.coder.anthropic")
def test_run_coder_agent_yields_status_dicts(mock_anthropic_mod, mock_run_manim):
    """run_coder_agent should yield dicts with 'status' and end with 'final'."""
    from agents.coder import run_coder_agent

    # Mock the Anthropic client
    mock_client = MagicMock()
    mock_anthropic_mod.Anthropic.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response()

    # Mock Manim execution: simulate success
    mock_run_manim.return_value = {
        "success": True,
        "video_path": "/tmp/test.mp4",
        "error": None,
    }

    updates = list(run_coder_agent(
        instructions="Draw a circle",
        max_retries=1,
        scene_class_name="TestScene",
    ))

    # Must have at least one update and the last one must be final
    assert len(updates) >= 1
    final = updates[-1]
    assert final.get("final") is True


@patch("agents.coder.run_manim_code")
@patch("agents.coder.anthropic")
def test_run_coder_agent_includes_tool_call_counts(mock_anthropic_mod, mock_run_manim):
    from agents.coder import run_coder_agent

    mock_client = MagicMock()
    mock_anthropic_mod.Anthropic.return_value = mock_client
    mock_client.messages.create.return_value = _make_mock_response()

    mock_run_manim.return_value = {
        "success": True,
        "video_path": "/tmp/test.mp4",
        "error": None,
    }

    updates = list(run_coder_agent(
        instructions="Draw a triangle",
        max_retries=1,
    ))

    final = updates[-1]
    assert "tool_call_counts" in final
    assert isinstance(final["tool_call_counts"], dict)
