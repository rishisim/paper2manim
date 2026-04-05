"""Tests that all stage names used in pipeline.py are from a known set.

This catches typos in string literals — if a developer adds a stage name
that is not in the canonical list, this test will flag it.
"""

from __future__ import annotations

import ast
import os
import re

import pytest


# ---------------------------------------------------------------------------
# Canonical stage names used in the pipeline
# ---------------------------------------------------------------------------

# These are the stage names that the CLI front-end knows about.
# "done" is the terminal pseudo-stage.
VALID_STAGES = {
    "plan",
    "tts",
    "code",
    "code_retry",
    "verify",
    "render",
    "stitch",
    "timing",
    "concat",
    "overlay",
    "done",
}


def _extract_stage_literals(filepath: str) -> list[tuple[str, int]]:
    """Extract all string values assigned to the key "stage" in dict literals.

    Returns a list of (stage_name, line_number) tuples.
    """
    with open(filepath) as f:
        source = f.read()

    stages: list[tuple[str, int]] = []

    # Pattern 1: "stage": "value" or 'stage': 'value' (string literals)
    pattern_str = re.compile(r"""["']stage["']\s*:\s*["']([^"']+)["']""")
    # Pattern 2: "stage": Stage.VALUE (enum references)
    pattern_enum = re.compile(r"""["']stage["']\s*:\s*Stage\.(\w+)""")
    for i, line in enumerate(source.splitlines(), 1):
        for m in pattern_str.finditer(line):
            stages.append((m.group(1), i))
        for m in pattern_enum.finditer(line):
            # Convert enum name to value (e.g., PLAN -> plan)
            stages.append((m.group(1).lower(), i))

    return stages


# ---------------------------------------------------------------------------
# Test: all stage names in pipeline.py are valid
# ---------------------------------------------------------------------------

PIPELINE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "agents",
    "pipeline.py",
)


def test_pipeline_file_exists():
    assert os.path.exists(PIPELINE_PATH), f"Pipeline file not found: {PIPELINE_PATH}"


def test_all_stage_names_are_valid():
    """Every 'stage' literal in pipeline.py must be in the VALID_STAGES set."""
    stages = _extract_stage_literals(PIPELINE_PATH)
    assert len(stages) > 0, "No stage literals found — extraction regex may be broken"

    invalid = [(name, line) for name, line in stages if name not in VALID_STAGES]
    if invalid:
        details = "\n".join(f"  line {line}: stage='{name}'" for name, line in invalid)
        pytest.fail(f"Unknown stage names found in pipeline.py:\n{details}")


def test_core_stages_are_present():
    """At minimum, the pipeline should reference these critical stages."""
    stages = _extract_stage_literals(PIPELINE_PATH)
    found = {name for name, _ in stages}

    core = {"plan", "tts", "code", "done"}
    missing = core - found
    assert not missing, f"Core stages missing from pipeline.py: {missing}"


def test_no_duplicate_done_stage_in_sequence():
    """The 'done' stage should not appear in yield/dict blocks without 'final'."""
    # This is a heuristic check — done stage should always have final=True
    # The dict literal may span multiple lines, so check a window of +/- 10 lines.
    with open(PIPELINE_PATH) as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        if '"stage": "done"' in line or "'stage': 'done'" in line:
            # Check a window of surrounding lines for "final"
            window_start = max(0, i - 5)
            window_end = min(len(lines), i + 15)
            window = "".join(lines[window_start:window_end])
            assert "final" in window, (
                f"Line {i + 1}: 'done' stage without 'final' key in surrounding context — "
                f"the terminal update must include final=True"
            )
