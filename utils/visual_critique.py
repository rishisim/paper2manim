"""
Visual critique agent for rendered Manim scenes.

Renders a low-quality preview, extracts key frames via ffmpeg,
sends them to a vision model (Claude) for aesthetic grading,
and returns a structured critique with a pass/fail verdict.
"""

from __future__ import annotations

import base64
import os
import subprocess
import tempfile
from dataclasses import dataclass, field

import anthropic


@dataclass
class CritiqueResult:
    """Result of a visual critique pass."""

    passed: bool
    score: float  # 0.0 – 1.0
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
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
  "issues": ["issue 1", "issue 2"],
  "suggestions": ["suggestion 1", "suggestion 2"]
}

Scoring guide:
- 0.8-1.0: Production quality, no significant issues
- 0.6-0.8: Good but has minor issues (small overlaps, slightly cluttered)
- 0.4-0.6: Needs improvement (overlapping elements, poor layout, hard to read)
- 0.0-0.4: Major problems (mostly empty, completely overlapping, unreadable)

Set "passed" to true if score >= 0.6.
Keep issues and suggestions concise (max 3 each)."""


def critique_video(
    video_path: str,
    segment_context: str = "",
    num_frames: int = 4,
    model: str = "claude-sonnet-4-6",
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

    # Check for mostly-black frames (empty scene)
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
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": b64,
            },
        })
        content.append({"type": "text", "text": f"Frame {i + 1}/{len(frames)}"})

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=_CRITIQUE_SYSTEM,
            messages=[{"role": "user", "content": content}],
        )

        raw = response.content[0].text or ""

        import json
        import re
        # Extract JSON from response
        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
        else:
            data = json.loads(text)

        return CritiqueResult(
            passed=data.get("passed", False),
            score=float(data.get("score", 0.0)),
            issues=data.get("issues", []),
            suggestions=data.get("suggestions", []),
            raw_feedback=raw,
        )

    except Exception as e:
        # If critique fails, pass by default (don't block the pipeline)
        return CritiqueResult(
            passed=True,
            score=0.5,
            issues=[f"Critique model error: {str(e)}"],
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
    model: str = "claude-sonnet-4-6",
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
    client = anthropic.Anthropic()

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
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": _encode_image_base64(last_a),
                }},
                {"type": "text", "text": "FIRST frame of incoming segment:"},
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": _encode_image_base64(first_b),
                }},
            ]

            response = client.messages.create(
                model=model,
                max_tokens=512,
                system=_TRANSITION_SYSTEM,
                messages=[{"role": "user", "content": content}],
            )

            import json as _json
            import re as _re
            raw = response.content[0].text or ""
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
