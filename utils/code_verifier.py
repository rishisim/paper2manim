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

from agents.config import resolve_fallback_stage_model, resolve_stage_model
from utils.llm_provider import run_text_completion

# ── Result types ────────────────────────────────────────────────────

@dataclass
class VerifyResult:
    """Result of a single-segment code verification."""

    segment_id: int
    passed: bool
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    static_issues: list[str] = field(default_factory=list)
    verification_tier: str = "static"
    quality_risk: str = "medium"
    expensive_features: list[str] = field(default_factory=list)
    llm_invoked: bool = False


@dataclass
class StaticQualityReport:
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    expensive_features: list[str] = field(default_factory=list)
    risk_score: int = 0
    quality_risk: str = "low"


@dataclass
class TransitionVerifyResult:
    """Result of a cross-segment transition check."""

    segment_a_id: int
    segment_b_id: int
    smooth: bool
    issues: list[str] = field(default_factory=list)
    verification_tier: str = "static"


@dataclass
class TimingNormalizationResult:
    changed: bool
    code: str
    estimated_before: float | None = None
    estimated_after: float | None = None
    residual_delta: float | None = None
    mode: str = "unchanged"
    reason: str | None = None


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
    lines = [line for line in code.split("\n") if line.strip()]
    return "\n".join(lines[-n_lines:])


def _get_code_head(code: str, n_lines: int = 40) -> str:
    """Get the first N non-empty lines of code (after imports/class def)."""
    lines = code.split("\n")
    # Find the construct() method start
    for i, line in enumerate(lines):
        if "def construct" in line:
            return "\n".join(lines[i : i + n_lines])
    return "\n".join(lines[:n_lines])


def _risk_label(score: int) -> str:
    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def static_quality_check(code: str, render_risk: str = "medium") -> StaticQualityReport:
    """Flag obvious clutter/layout risks before expensive rendering."""
    issues: list[str] = []
    warnings: list[str] = []
    expensive_features: list[str] = []
    risk_score = {"low": 0, "medium": 1, "high": 3}.get(render_risk, 1)

    play_calls = len(re.findall(r"\bself\.play\(", code))
    create_calls = len(re.findall(r"\b(Create|Write|FadeIn|GrowArrow|TransformMatchingTex|AnimationGroup|LaggedStart)\(", code))
    fadeout_calls = len(re.findall(r"\bFadeOut\(", code))
    move_to_origin_calls = len(re.findall(r"\.move_to\(ORIGIN\)", code))
    label_origin_risks = len(re.findall(r"(label|text)\w*\s*=.*?\.move_to\(ORIGIN\)", code, flags=re.IGNORECASE))
    wait_calls = len(re.findall(r"\bself\.wait\(", code))
    always_redraw_calls = len(re.findall(r"\balways_redraw\(", code))
    updater_calls = len(re.findall(r"\b(add_updater|updater|ValueTracker)\b", code))
    three_d_calls = len(re.findall(r"\b(ThreeDScene|Surface|set_camera_orientation|begin_ambient_camera_rotation)\b", code))
    high_res_surface = len(re.findall(r"resolution\s*=\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)", code))
    plot_calls = len(re.findall(r"\b(plot|FunctionGraph)\(", code))
    final_waits = re.findall(r"\bself\.wait\(\s*(\d+(?:\.\d+)?)?\s*\)\s*$", code, flags=re.MULTILINE)

    if play_calls >= 6 and fadeout_calls == 0:
        issues.append("Scene has many animation beats but no FadeOut cleanup, which risks cluttered transitions.")
        risk_score += 2
    if create_calls >= 10 and fadeout_calls <= 1:
        issues.append("Many objects are introduced with very little cleanup; simplify or clear zones between ideas.")
        risk_score += 2
    if move_to_origin_calls >= 4:
        issues.append("Repeated .move_to(ORIGIN) suggests unrelated objects may overlap in the main zone.")
        risk_score += 1
    if label_origin_risks:
        issues.append("A label/text object is moved to ORIGIN instead of being placed relative to its target.")
        risk_score += 1
    if play_calls >= 3 and wait_calls == 0:
        issues.append("Scene animates multiple beats without any explicit self.wait() breathing room.")
        risk_score += 1
    if not final_waits:
        warnings.append("Final beat has no explicit hold; the ending may feel abrupt or lose its anchor frame.")
        risk_score += 1
    elif float(final_waits[-1] or 1.0) < 0.5:
        warnings.append("Final hold is very short; preserve the closing anchor visual slightly longer.")
        risk_score += 1

    if always_redraw_calls:
        expensive_features.append("always_redraw")
        risk_score += 2
    if updater_calls:
        expensive_features.append("updaters")
        risk_score += 1
    if three_d_calls:
        expensive_features.append("3d_camera")
        risk_score += 2
    if high_res_surface:
        expensive_features.append("high_res_surface")
        risk_score += 1
    if plot_calls >= 3:
        expensive_features.append("dense_plotting")
        risk_score += 1

    quality_risk = _risk_label(risk_score)
    return StaticQualityReport(
        issues=issues,
        warnings=warnings,
        expensive_features=sorted(set(expensive_features)),
        risk_score=risk_score,
        quality_risk=quality_risk,
    )


_NUMERIC_LITERAL_RE = r"(\d+(?:\.\d+)?)"
_WAIT_CALL_RE = re.compile(rf"(?P<prefix>\bself\.wait\(\s*)(?P<value>{_NUMERIC_LITERAL_RE})?(?P<suffix>\s*\))")


def _estimate_scene_duration(code: str) -> float | None:
    """Estimate scene duration from explicit numeric run_time/wait values.

    This intentionally stays conservative: it only sums literal values such as
    ``run_time=1.5`` and ``self.wait(0.8)``. If the code uses expressions or
    helper variables for most timings, we return ``None`` rather than guessing.
    """
    run_times = [
        float(match)
        for match in re.findall(rf"\brun_time\s*=\s*{_NUMERIC_LITERAL_RE}", code)
    ]
    waits = [
        float(match)
        for match in re.findall(rf"\bself\.wait\(\s*{_NUMERIC_LITERAL_RE}\s*\)", code)
    ]
    bare_waits = len(re.findall(r"\bself\.wait\(\s*\)", code))
    if not run_times and not waits and not bare_waits:
        return None
    return sum(run_times) + sum(waits) + bare_waits


def _timing_issue(code: str, audio_duration: float) -> str | None:
    """Return a concrete timing mismatch issue if the scene is clearly off."""
    if audio_duration <= 0:
        return None

    estimated = _estimate_scene_duration(code)
    if estimated is None:
        return None

    delta = estimated - audio_duration
    tolerance = max(1.2, audio_duration * 0.12)
    if abs(delta) <= tolerance:
        return None

    direction = "too long" if delta > 0 else "too short"
    return (
        f"Estimated scene timing ({estimated:.1f}s) is {direction} for the "
        f"target audio ({audio_duration:.1f}s)."
    )


def normalize_scene_timing(
    code: str,
    audio_duration: float,
    *,
    max_residual: float = 0.75,
) -> TimingNormalizationResult:
    """Apply a small deterministic timing fix when the mismatch is wait-driven.

    The default path only edits explicit ``self.wait(...)`` calls. It never
    rewrites ``run_time=...`` animation durations.
    """
    if audio_duration <= 0:
        return TimingNormalizationResult(False, code, reason="missing target audio duration")

    estimated = _estimate_scene_duration(code)
    if estimated is None:
        return TimingNormalizationResult(False, code, reason="scene timing cannot be estimated")

    delta = audio_duration - estimated
    if abs(delta) <= max_residual:
        return TimingNormalizationResult(
            False,
            code,
            estimated_before=estimated,
            estimated_after=estimated,
            residual_delta=delta,
            reason="already within tolerance",
        )

    matches = list(_WAIT_CALL_RE.finditer(code))
    if delta > 0:
        if matches:
            last_match = matches[-1]
            current_wait = float(last_match.group("value") or 1.0)
            updated_wait = max(0.0, current_wait + delta)
            new_code = (
                code[: last_match.start()]
                + f"{last_match.group('prefix')}{updated_wait:.3f}{last_match.group('suffix')}"
                + code[last_match.end() :]
            )
            estimated_after = _estimate_scene_duration(new_code)
            residual = None if estimated_after is None else audio_duration - estimated_after
            return TimingNormalizationResult(
                True,
                new_code,
                estimated_before=estimated,
                estimated_after=estimated_after,
                residual_delta=residual,
                mode="extend_final_wait",
            )

        indent = "        "
        for line in reversed(code.splitlines()):
            if line.strip():
                leading = line[: len(line) - len(line.lstrip())]
                if leading:
                    indent = leading
                    break
        suffix = "" if code.endswith("\n") else "\n"
        new_code = f"{code}{suffix}{indent}self.wait({delta:.3f})\n"
        estimated_after = _estimate_scene_duration(new_code)
        residual = None if estimated_after is None else audio_duration - estimated_after
        return TimingNormalizationResult(
            True,
            new_code,
            estimated_before=estimated,
            estimated_after=estimated_after,
            residual_delta=residual,
            mode="append_wait",
        )

    wait_values = [float(match.group("value") or 1.0) for match in matches]
    total_wait = sum(wait_values)
    if total_wait <= 0:
        return TimingNormalizationResult(
            False,
            code,
            estimated_before=estimated,
            residual_delta=delta,
            reason="no explicit waits available to shrink",
        )

    target_wait_total = max(0.0, total_wait + delta)
    scale = target_wait_total / total_wait if total_wait else 0.0
    updated_waits = [max(0.0, wait_value * scale) for wait_value in wait_values]
    wait_iter = iter(updated_waits)

    def _replace_wait(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}{next(wait_iter):.3f}{match.group('suffix')}"

    new_code = _WAIT_CALL_RE.sub(_replace_wait, code)
    estimated_after = _estimate_scene_duration(new_code)
    residual = None if estimated_after is None else audio_duration - estimated_after
    return TimingNormalizationResult(
        True,
        new_code,
        estimated_before=estimated,
        estimated_after=estimated_after,
        residual_delta=residual,
        mode="shrink_waits",
    )


# ── Single-segment verification ────────────────────────────────────

def verify_segment_code(
    segment_id: int,
    code: str,
    segment_context: str = "",
    audio_duration: float = 0.0,
    token_counter: dict | None = None,
    quality_mode: str = "balanced",
    render_risk: str = "medium",
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

    static_report = static_quality_check(code, render_risk=render_risk)
    static_issues = list(static_report.issues)
    timing_issue = _timing_issue(code, audio_duration)
    if timing_issue:
        static_issues.append(timing_issue)
        static_report.risk_score += 2
        static_report.quality_risk = _risk_label(static_report.risk_score)

    should_run_llm = bool(static_issues)
    if quality_mode == "polished" and static_report.quality_risk in {"medium", "high"}:
        should_run_llm = True
    if render_risk == "high":
        should_run_llm = True

    combined_issues = static_issues + list(static_report.warnings)
    if not should_run_llm:
        return VerifyResult(
            segment_id=segment_id,
            passed=not static_issues,
            issues=combined_issues,
            suggestions=[],
            static_issues=static_issues,
            verification_tier="static",
            quality_risk=static_report.quality_risk,
            expensive_features=static_report.expensive_features,
            llm_invoked=False,
        )

    try:
        result = run_text_completion(
            primary=resolve_stage_model("verify"),
            fallback=resolve_fallback_stage_model("verify"),
            system_sections=[_VERIFY_SYSTEM],
            user_content=prompt,
            max_output_tokens=1024,
            token_counter=token_counter,
            cache_key_parts=("verify",),
        )
        raw = result.text or ""
        data = _parse_json_response(raw)
        combined_issues = list(combined_issues)
        combined_issues.extend(data.get("issues", []))
        passed = data.get("passed", True) and not static_issues

        return VerifyResult(
            segment_id=segment_id,
            passed=passed,
            issues=combined_issues,
            suggestions=data.get("suggestions", []),
            static_issues=static_issues,
            verification_tier="llm",
            quality_risk=static_report.quality_risk,
            expensive_features=static_report.expensive_features,
            llm_invoked=True,
        )
    except Exception as e:
        # If verification fails, pass by default (don't block the pipeline)
        return VerifyResult(
            segment_id=segment_id,
            passed=True,
            issues=combined_issues + [f"Code verifier error: {str(e)}"],
            static_issues=static_issues,
            verification_tier="llm_error",
            quality_risk=static_report.quality_risk,
            expensive_features=static_report.expensive_features,
            llm_invoked=True,
        )


# ── Cross-segment transition verification ──────────────────────────

def verify_code_transitions(
    segment_codes: dict[int, str],
    segment_specs: dict[int, dict] | None = None,
    quality_mode: str = "balanced",
    token_counter: dict | None = None,
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

    for i in range(len(sorted_ids) - 1):
        id_a, id_b = sorted_ids[i], sorted_ids[i + 1]
        code_a, code_b = segment_codes[id_a], segment_codes[id_b]
        spec_b = (segment_specs or {}).get(id_b, {})
        carry_over = str(spec_b.get("carry_over_from_previous", "clean reset")).lower()

        tail_a = _get_code_tail(code_a)
        head_b = _get_code_head(code_b)
        static_issues: list[str] = []

        if "clean reset" not in carry_over and "carry_anchor" not in str(spec_b.get("scene_strategy", "")).lower():
            static_issues.append("Segment metadata suggests carry-over, but the scene strategy does not preserve an anchor explicitly.")
        if "clean reset" in carry_over and "FadeOut(" not in tail_a and quality_mode == "polished":
            static_issues.append("Segment A does not visibly clear the outgoing state before a clean reset.")

        should_run_llm = bool(static_issues) or ("clean reset" not in carry_over)
        if not should_run_llm:
            results.append(TransitionVerifyResult(
                segment_a_id=id_a,
                segment_b_id=id_b,
                smooth=True,
                issues=[],
                verification_tier="static",
            ))
            continue

        prompt = (
            f"Reviewing transition from Segment {id_a} to Segment {id_b}.\n\n"
            f"END of Segment {id_a}:\n```python\n{tail_a}\n```\n\n"
            f"START of Segment {id_b}:\n```python\n{head_b}\n```"
        )

        try:
            result = run_text_completion(
                primary=resolve_stage_model("verify"),
                fallback=resolve_fallback_stage_model("verify"),
                system_sections=[_TRANSITION_SYSTEM],
                user_content=prompt,
                max_output_tokens=512,
                token_counter=token_counter,
                cache_key_parts=("verify-transition",),
            )
            raw = result.text or ""
            data = _parse_json_response(raw)

            results.append(TransitionVerifyResult(
                segment_a_id=id_a,
                segment_b_id=id_b,
                smooth=data.get("smooth", True),
                issues=static_issues + data.get("issues", []),
                verification_tier="llm",
            ))
        except Exception as e:
            results.append(TransitionVerifyResult(
                segment_a_id=id_a,
                segment_b_id=id_b,
                smooth=True,
                issues=static_issues + [f"Transition check error: {str(e)}"],
                verification_tier="llm_error",
            ))

    return results
