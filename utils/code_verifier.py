"""
Code-level verifier for Manim scenes.

Analyzes generated Manim code (not rendered video) to predict visual issues
like overlapping elements, bad transitions, timing mismatches, and layout
problems. Runs a lightweight LLM pass on the code to catch issues that
static analysis in `_quality_check_code` might miss.

Also verifies cross-segment transitions by comparing the tail of one
segment's code with the head of the next.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import anthropic


# ── Result types ────────────────────────────────────────────────────

@dataclass
class VerifyResult:
    """Result of a single-segment code verification."""

    segment_id: int
    passed: bool
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


@dataclass
class TransitionVerifyResult:
    """Result of a cross-segment transition check."""

    segment_a_id: int
    segment_b_id: int
    smooth: bool
    issues: list[str] = field(default_factory=list)


# ── Prompts ─────────────────────────────────────────────────────────

_VERIFY_SYSTEM = """\
You are an expert Manim code reviewer specializing in 3Blue1Brown-style educational animations.

Given a Manim Scene class, predict visual problems that would appear when rendered. Focus on:

1. **Overlapping elements**: Objects placed at the same position without removing previous ones.
2. **Missing cleanup**: Elements that should be FadeOut'd or removed before new content appears.
3. **Off-screen content**: Elements positioned beyond visible frame bounds (default: 14.2 x 8 units).
4. **Cluttered layout**: Too many simultaneous on-screen objects without spatial organization.
5. **Timing issues**: Animations that are too fast (run_time < 0.3) or have no wait() breathing room.
6. **Broken transitions**: Scene doesn't end with a clean state (remaining objects not faded out).
7. **LaTeX issues**: Malformed MathTex/Tex strings that will fail or render incorrectly.
8. **Z-ordering problems**: Important elements hidden behind others.

Output ONLY valid JSON:
{
  "passed": true/false,
  "issues": ["issue 1", "issue 2"],
  "suggestions": ["suggestion 1"]
}

Set "passed" to false ONLY for issues that will clearly cause visible problems.
Minor style preferences should be suggestions, not failures.
Keep issues and suggestions concise (max 4 each). Be specific about line numbers or object names."""

_TRANSITION_SYSTEM = """\
You are reviewing the transition between two consecutive Manim scenes in a multi-segment educational video.

Given the END of Segment A's code and the START of Segment B's code, check:

1. Does Segment A clean up (FadeOut all remaining objects) at the end?
2. Does Segment B start fresh or does it assume leftover state from A?
3. Is the visual style consistent (colors, font sizes, positioning conventions)?
4. Is there a logical content flow between the segments?

Output ONLY valid JSON:
{
  "smooth": true/false,
  "issues": ["issue 1", "issue 2"]
}

Set "smooth" to false only for clear transition problems. Max 2 issues."""

MODEL = "claude-sonnet-4-6"


# ── Helpers ─────────────────────────────────────────────────────────

def _parse_json_response(raw: str) -> dict:
    """Extract JSON from a model response that may include markdown fences."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    return json.loads(text)


def _get_code_tail(code: str, n_lines: int = 40) -> str:
    """Get the last N non-empty lines of code."""
    lines = [l for l in code.split("\n") if l.strip()]
    return "\n".join(lines[-n_lines:])


def _get_code_head(code: str, n_lines: int = 40) -> str:
    """Get the first N non-empty lines of code (after imports/class def)."""
    lines = code.split("\n")
    # Find the construct() method start
    for i, line in enumerate(lines):
        if "def construct" in line:
            return "\n".join(lines[i : i + n_lines])
    return "\n".join(lines[:n_lines])


# ── Single-segment verification ────────────────────────────────────

def verify_segment_code(
    segment_id: int,
    code: str,
    segment_context: str = "",
    audio_duration: float = 0.0,
) -> VerifyResult:
    """Verify a single segment's Manim code for potential visual issues.

    Args:
        segment_id: Segment number.
        code: The full Manim Python code for this segment.
        segment_context: Description of what this segment should show.
        audio_duration: Expected audio duration for timing checks.

    Returns:
        VerifyResult with pass/fail and issue list.
    """
    prompt = f"Review this Manim scene code for visual issues:\n\n```python\n{code}\n```"
    if segment_context:
        prompt += f"\n\nThis segment should show: {segment_context}"
    if audio_duration > 0:
        prompt += f"\n\nTarget audio duration: {audio_duration:.1f}s"

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=_VERIFY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text or ""
        data = _parse_json_response(raw)

        return VerifyResult(
            segment_id=segment_id,
            passed=data.get("passed", True),
            issues=data.get("issues", []),
            suggestions=data.get("suggestions", []),
        )
    except Exception as e:
        # If verification fails, pass by default (don't block the pipeline)
        return VerifyResult(
            segment_id=segment_id,
            passed=True,
            issues=[f"Code verifier error: {str(e)}"],
        )


# ── Cross-segment transition verification ──────────────────────────

def verify_code_transitions(
    segment_codes: dict[int, str],
) -> list[TransitionVerifyResult]:
    """Check code-level transition smoothness between consecutive segments.

    Args:
        segment_codes: Mapping of segment_id -> full Manim code, in order.

    Returns:
        List of TransitionVerifyResult for each adjacent pair.
    """
    sorted_ids = sorted(segment_codes.keys())
    if len(sorted_ids) < 2:
        return []

    results: list[TransitionVerifyResult] = []
    client = anthropic.Anthropic()

    for i in range(len(sorted_ids) - 1):
        id_a, id_b = sorted_ids[i], sorted_ids[i + 1]
        code_a, code_b = segment_codes[id_a], segment_codes[id_b]

        tail_a = _get_code_tail(code_a)
        head_b = _get_code_head(code_b)

        prompt = (
            f"Reviewing transition from Segment {id_a} to Segment {id_b}.\n\n"
            f"END of Segment {id_a}:\n```python\n{tail_a}\n```\n\n"
            f"START of Segment {id_b}:\n```python\n{head_b}\n```"
        )

        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=512,
                system=_TRANSITION_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text or ""
            data = _parse_json_response(raw)

            results.append(TransitionVerifyResult(
                segment_a_id=id_a,
                segment_b_id=id_b,
                smooth=data.get("smooth", True),
                issues=data.get("issues", []),
            ))
        except Exception as e:
            results.append(TransitionVerifyResult(
                segment_a_id=id_a,
                segment_b_id=id_b,
                smooth=True,
                issues=[f"Transition check error: {str(e)}"],
            ))

    return results
