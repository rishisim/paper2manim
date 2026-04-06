"""
Visual critique agent for rendered Manim scenes.

Renders a low-quality preview, extracts key frames via ffmpeg,
sends them to a vision model (Claude) for aesthetic grading,
and returns a structured critique with a pass/fail verdict.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field

from agents.config import StageModelConfig, infer_provider, resolve_fallback_stage_model, resolve_stage_model
from utils.llm_provider import run_text_completion


@dataclass
class CritiqueResult:
    """Result of a visual critique pass."""

    passed: bool
    score: float  # 0.0 – 1.0
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    sub_scores: dict[str, float] = field(default_factory=dict)
    raw_feedback: str = ""


# ── Frame extraction ────────────────────────────────────────────────

def _extract_key_frames(video_path: str, num_frames: int = 4, output_dir: str | None = None) -> list[str]:
    """Extract evenly-spaced key frames from a video using ffmpeg.

    Returns list of PNG file paths.
    """
    if not os.path.isfile(video_path):
        return []

    out_dir = output_dir or tempfile.mkdtemp(prefix="critique_frames_")
    os.makedirs(out_dir, exist_ok=True)

    # Get video duration
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        duration_str = subprocess.run(
            probe_cmd, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        duration = float(duration_str)
    except Exception:
        duration = 30.0  # fallback

    if duration <= 0:
        duration = 30.0

    # Calculate timestamps for evenly-spaced frames (skip first/last 5%)
    margin = duration * 0.05
    usable = duration - 2 * margin
    if duration >= 45:
        num_frames = max(num_frames, 6)
    elif duration >= 20:
        num_frames = max(num_frames, 5)

    timestamps = [margin + usable * i / max(num_frames - 1, 1) for i in range(num_frames)]

    frame_paths: list[str] = []
    for i, ts in enumerate(timestamps):
        out_path = os.path.join(out_dir, f"frame_{i:02d}.png")
        cmd = [
            "ffmpeg", "-y", "-ss", f"{ts:.2f}",
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",
            out_path,
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=15)
            if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                frame_paths.append(out_path)
        except Exception:
            continue

    return frame_paths


def _analyze_frame_image(path: str) -> dict[str, float]:
    """Return basic brightness/coverage heuristics for a PNG frame."""
    try:
        from PIL import Image, ImageStat
    except Exception:
        return {"mean_brightness": 0.5, "non_dark_ratio": 0.5, "stddev": 0.2}

    with Image.open(path) as img:
        gray = img.convert("L")
        stat = ImageStat.Stat(gray)
        pixels = list(gray.getdata())
        total = max(len(pixels), 1)
        non_dark = sum(1 for px in pixels if px > 24)
        return {
            "mean_brightness": (stat.mean[0] if stat.mean else 0.0) / 255.0,
            "non_dark_ratio": non_dark / total,
            "stddev": (stat.stddev[0] if stat.stddev else 0.0) / 255.0,
        }


def _heuristic_frame_issues(frame_paths: list[str]) -> tuple[list[str], dict[str, float]]:
    analyses = [_analyze_frame_image(path) for path in frame_paths]
    if not analyses:
        return (["No frames available for heuristic analysis."], {})

    mean_brightness = sum(a["mean_brightness"] for a in analyses) / len(analyses)
    non_dark_ratio = sum(a["non_dark_ratio"] for a in analyses) / len(analyses)
    detail_stddev = sum(a["stddev"] for a in analyses) / len(analyses)
    last_frame = analyses[-1]

    issues: list[str] = []
    if non_dark_ratio < 0.08 or mean_brightness < 0.04:
        issues.append("Frames appear mostly empty or black.")
    if detail_stddev > 0.35 and non_dark_ratio > 0.75:
        issues.append("Frames appear visually overloaded or cluttered.")
    if last_frame["non_dark_ratio"] < 0.08:
        issues.append("Final frame is nearly empty instead of holding a meaningful anchor visual.")

    sub_scores = {
        "readability": max(0.0, min(1.0, 0.45 + detail_stddev)),
        "clutter": max(0.0, min(1.0, 1.0 - max(0.0, detail_stddev - 0.18) * 2.5)),
        "content_coverage": max(0.0, min(1.0, non_dark_ratio * 1.6)),
        "end_frame_quality": max(0.0, min(1.0, last_frame["non_dark_ratio"] * 1.8)),
    }
    return issues, sub_scores


def _encode_image_base64(path: str) -> str:
    """Read an image file and return base64-encoded string."""
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


# ── Vision model critique ───────────────────────────────────────────

_CRITIQUE_SYSTEM = """You are an expert visual quality reviewer for educational math animation videos (3Blue1Brown style).

You are given key frames extracted from a rendered Manim scene. Evaluate the visual quality on these criteria:

1. **Readability**: Is text legible? Are equations clear? Are labels readable?
2. **Layout**: Are elements well-spaced? Is the screen cluttered? Are there overlapping elements?
3. **Aesthetics**: Does it look professional? Good color contrast on dark background? Consistent styling?
4. **Content Coverage**: Do the frames show meaningful mathematical content (not just empty/black frames)?
5. **Transitions**: Do frames suggest smooth visual flow between concepts?

Output ONLY valid JSON:
{
  "score": 0.0-1.0,
  "passed": true/false,
  "sub_scores": {
    "readability": 0.0-1.0,
    "clutter": 0.0-1.0,
    "content_coverage": 0.0-1.0,
    "end_frame_quality": 0.0-1.0
  },
  "issues": ["issue 1", "issue 2"],
  "suggestions": ["suggestion 1", "suggestion 2"]
}

Scoring guide:
- 0.8-1.0: Production quality, no significant issues
- 0.6-0.8: Good but has minor issues (small overlaps, slightly cluttered)
- 0.4-0.6: Needs improvement (overlapping elements, poor layout, hard to read)
- 0.0-0.4: Major problems (mostly empty, completely overlapping, unreadable)

Set "passed" to true if score >= 0.7.
Keep issues and suggestions concise (max 3 each)."""


def critique_video(
    video_path: str,
    segment_context: str = "",
    num_frames: int = 4,
    model: str | None = None,
    token_counter: dict | None = None,
) -> CritiqueResult:
    """Run visual critique on a rendered video.

    Args:
        video_path: Path to the rendered .mp4 file.
        segment_context: Optional description of what the segment should show.
        num_frames: Number of key frames to extract for review.
        model: Vision model to use (default: Sonnet for speed/cost).

    Returns:
        CritiqueResult with pass/fail, score, issues, and suggestions.
    """
    frames = _extract_key_frames(video_path, num_frames=num_frames)

    if not frames:
        return CritiqueResult(
            passed=False,
            score=0.0,
            issues=["Could not extract any frames from the video"],
            raw_feedback="Frame extraction failed",
        )

    heuristic_issues, heuristic_sub_scores = _heuristic_frame_issues(frames)
    if any("mostly empty or black" in issue.lower() or "visually overloaded" in issue.lower() for issue in heuristic_issues):
        return CritiqueResult(
            passed=False,
            score=min(heuristic_sub_scores.values()) if heuristic_sub_scores else 0.0,
            issues=heuristic_issues,
            suggestions=["Reduce clutter and preserve a clearer, meaningful composition."],
            sub_scores=heuristic_sub_scores,
            raw_feedback="Heuristic visual failure",
        )

    # Build vision API request
    content: list[dict] = []

    context_text = "Review these key frames from a Manim-rendered educational math video."
    if segment_context:
        context_text += f"\n\nThis segment is supposed to show: {segment_context}"
    context_text += f"\n\nFrames are in chronological order ({len(frames)} frames extracted)."

    content.append({"type": "text", "text": context_text})

    for i, frame_path in enumerate(frames):
        b64 = _encode_image_base64(frame_path)
        content.append({
            "type": "image_base64",
            "media_type": "image/png",
            "data": b64,
        })
        content.append({"type": "text", "text": f"Frame {i + 1}/{len(frames)}"})

    try:
        primary = resolve_stage_model("vision")
        if model:
            primary = StageModelConfig(
                provider=infer_provider(model),
                model=model,
                reasoning_effort=primary.reasoning_effort,
                cache_retention=primary.cache_retention,
                cache_key_prefix=primary.cache_key_prefix,
            )
        result = run_text_completion(
            primary=primary,
            fallback=resolve_fallback_stage_model("vision"),
            system_sections=[_CRITIQUE_SYSTEM],
            user_content=content,
            max_output_tokens=1024,
            token_counter=token_counter,
            cache_key_parts=("critique",),
        )
        raw = result.text or ""

        # Extract JSON from response
        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
        else:
            data = json.loads(text)

        sub_scores = data.get("sub_scores") or {}
        merged_sub_scores = dict(heuristic_sub_scores)
        for key, value in sub_scores.items():
            try:
                merged_sub_scores[key] = float(value)
            except Exception:
                continue
        issues = heuristic_issues + data.get("issues", [])
        score = float(data.get("score", 0.0))
        passed = bool(data.get("passed", False)) and score >= 0.7 and not heuristic_issues

        return CritiqueResult(
            passed=passed,
            score=score,
            issues=issues,
            suggestions=data.get("suggestions", []),
            sub_scores=merged_sub_scores,
            raw_feedback=raw,
        )

    except Exception as e:
        # If critique fails, pass by default (don't block the pipeline)
        return CritiqueResult(
            passed=True,
            score=0.5,
            issues=[f"Critique model error: {str(e)}"],
            sub_scores=heuristic_sub_scores,
            raw_feedback=str(e),
        )
    finally:
        # Clean up extracted frames
        for fp in frames:
            try:
                os.remove(fp)
            except OSError:
                pass


def _extract_boundary_frames(video_path: str, output_dir: str | None = None) -> tuple[str | None, str | None]:
    """Extract the first and last frames of a video.

    Returns (first_frame_path, last_frame_path).
    """
    out_dir = output_dir or tempfile.mkdtemp(prefix="boundary_frames_")
    os.makedirs(out_dir, exist_ok=True)

    first_path = os.path.join(out_dir, "first_frame.png")
    last_path = os.path.join(out_dir, "last_frame.png")

    # First frame
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-frames:v", "1", "-q:v", "2", first_path],
            capture_output=True, timeout=10,
        )
    except Exception:
        first_path = None

    # Last frame — seek to near end
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=10,
        )
        duration = float(probe.stdout.strip())
        seek_ts = max(0, duration - 0.1)
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{seek_ts:.2f}", "-i", video_path,
             "-frames:v", "1", "-q:v", "2", last_path],
            capture_output=True, timeout=10,
        )
    except Exception:
        last_path = None

    first_ok = first_path and os.path.isfile(first_path) and os.path.getsize(first_path) > 0
    last_ok = last_path and os.path.isfile(last_path) and os.path.getsize(last_path) > 0

    return (first_path if first_ok else None, last_path if last_ok else None)


@dataclass
class TransitionResult:
    """Result of a cross-segment transition check."""

    segment_a_id: int
    segment_b_id: int
    smooth: bool
    issues: list[str] = field(default_factory=list)


_TRANSITION_SYSTEM = """You are a video editor reviewing the transition between two consecutive segments of an educational math animation.

You are given two frames:
1. The LAST frame of the outgoing segment
2. The FIRST frame of the incoming segment

Evaluate whether the transition is visually smooth:
- Is the outgoing segment properly cleaned up (elements faded out)?
- Does the incoming segment start cleanly (not cluttered with leftovers)?
- Is the color palette consistent between segments?
- Is the visual style consistent (font sizes, element styling)?

Output ONLY valid JSON:
{
  "smooth": true/false,
  "issues": ["issue 1", "issue 2"]
}

Set "smooth" to true if the transition looks natural. Keep issues concise (max 2)."""


def verify_transitions(
    segment_video_paths: dict[int, str],
    model: str | None = None,
    token_counter: dict | None = None,
) -> list[TransitionResult]:
    """Check visual continuity between consecutive segment pairs.

    Args:
        segment_video_paths: Mapping of segment_id → video file path, in order.

    Returns:
        List of TransitionResult for each adjacent pair.
    """
    sorted_ids = sorted(segment_video_paths.keys())
    if len(sorted_ids) < 2:
        return []

    results: list[TransitionResult] = []

    for i in range(len(sorted_ids) - 1):
        id_a, id_b = sorted_ids[i], sorted_ids[i + 1]
        path_a, path_b = segment_video_paths[id_a], segment_video_paths[id_b]

        _, last_a = _extract_boundary_frames(path_a)
        first_b, _ = _extract_boundary_frames(path_b)

        if not last_a or not first_b:
            results.append(TransitionResult(
                segment_a_id=id_a, segment_b_id=id_b, smooth=True,
                issues=["Could not extract boundary frames"],
            ))
            continue

        try:
            content: list[dict] = [
                {"type": "text", "text": f"Reviewing transition from Segment {id_a} to Segment {id_b}."},
                {"type": "text", "text": "LAST frame of outgoing segment:"},
                {"type": "image_base64", "media_type": "image/png", "data": _encode_image_base64(last_a)},
                {"type": "text", "text": "FIRST frame of incoming segment:"},
                {"type": "image_base64", "media_type": "image/png", "data": _encode_image_base64(first_b)},
            ]
            primary = resolve_stage_model("vision")
            if model:
                primary = StageModelConfig(
                    provider=infer_provider(model),
                    model=model,
                    reasoning_effort=primary.reasoning_effort,
                    cache_retention=primary.cache_retention,
                    cache_key_prefix=primary.cache_key_prefix,
                )
            result = run_text_completion(
                primary=primary,
                fallback=resolve_fallback_stage_model("vision"),
                system_sections=[_TRANSITION_SYSTEM],
                user_content=content,
                max_output_tokens=512,
                token_counter=token_counter,
                cache_key_parts=("critique-transition",),
            )

            import json as _json
            import re as _re
            raw = result.text or ""
            text = raw.strip()
            text = _re.sub(r"^```(?:json)?\s*", "", text)
            text = _re.sub(r"\s*```$", "", text)
            match = _re.search(r"\{.*\}", text, _re.DOTALL)
            data = _json.loads(match.group(0)) if match else _json.loads(text)

            results.append(TransitionResult(
                segment_a_id=id_a,
                segment_b_id=id_b,
                smooth=data.get("smooth", True),
                issues=data.get("issues", []),
            ))
        except Exception as e:
            results.append(TransitionResult(
                segment_a_id=id_a, segment_b_id=id_b, smooth=True,
                issues=[f"Transition check error: {str(e)}"],
            ))
        finally:
            for fp in [last_a, first_b]:
                if fp:
                    try:
                        os.remove(fp)
                    except OSError:
                        pass

    return results


@dataclass
class ProjectConsistencyResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    transition_results: list[TransitionResult] = field(default_factory=list)


def critique_project_consistency(
    segment_video_paths: dict[int, str],
    token_counter: dict | None = None,
) -> ProjectConsistencyResult:
    """Project-level visual continuity check before concat."""
    transition_results = verify_transitions(segment_video_paths, token_counter=token_counter)
    issues: list[str] = []
    for result in transition_results:
        if not result.smooth:
            issues.extend(
                f"Segments {result.segment_a_id}->{result.segment_b_id}: {issue}"
                for issue in result.issues
            )
    return ProjectConsistencyResult(
        passed=not issues,
        issues=issues,
        transition_results=transition_results,
    )
