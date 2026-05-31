"""
Segmented video pipeline orchestrator.

Coordinates the full pipelined-parallel pipeline:
  1. Planner  → segmented storyboard
  2. Per-segment pipeline (all segments concurrent):
       TTS → Code → HD Render → Stitch
  3. Retry    → failed segments with few-shot + escalation
  4. Concat   → final output video      (ffmpeg concat)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from queue import Empty, Queue
from typing import Any, Iterator

from agents.coder import run_code_patch_agent, run_coder_agent
from agents.config import (
    estimate_cache_savings,
    estimate_cost,
    merge_token_usage,
    model_profile_summary,
    new_token_counter,
    resolve_stage_model,
)
from agents.planner import plan_segmented_storyboard_lite
from agents.planner_math2manim import run_math2manim_planner
from utils.media_assembler import concatenate_segments, mux_subtitles, stitch_video_and_audio
from utils.subtitle_generator import generate_combined_srt, write_srt
from utils.parallel_renderer import RenderJob, submit_render_job
from utils.project_state import (
    create_project,
    is_segment_stage_done,
    is_stage_done,
    load_project,
    mark_project_complete,
    mark_segment_stage,
    mark_stage_done,
    save_project,
)
from utils.code_verifier import normalize_scene_timing, verify_code_transitions, verify_segment_code
from utils.tts_engine import generate_voiceover_async
from utils.visual_critique import critique_project_consistency, critique_video


def _format_duration(seconds: float) -> str:
    """Format seconds as '12.3s' or '477.1s [7m 57s]' for >=60s."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{seconds:.1f}s [{m}m {s:02d}s]"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s-]+", "_", slug).strip("_")[:60]


def _has_valid_code(result: dict) -> bool:
    return bool(result.get("video_path")) or result.get("code_validated", False)


def _normalize_code_for_fingerprint(code: str) -> str:
    lines = [line.rstrip() for line in (code or "").splitlines() if line.strip()]
    return "\n".join(lines)


def _hash_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _build_verify_fingerprint(code: str, audio_duration: float, quality_mode: str, render_risk: str) -> str:
    payload = f"{_normalize_code_for_fingerprint(code)}\n|audio={audio_duration:.2f}|mode={quality_mode}|risk={render_risk}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_critique_fingerprint(code: str, render_quality: str, audio_duration: float) -> str:
    payload = f"{_normalize_code_for_fingerprint(code)}\n|render={render_quality}|audio={audio_duration:.2f}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _get_segment_stage_entry(state: dict[str, Any] | None, segment_id: int, stage: str) -> dict[str, Any]:
    return (state or {}).get("segments", {}).get(str(segment_id), {}).get(stage, {}) or {}


def _risk_rank(value: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get((value or "medium").lower(), 1)


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return max(minimum, default)
    try:
        return max(minimum, int(raw))
    except ValueError:
        return max(minimum, default)


def _env_truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _segment_concurrency(num_segments: int) -> int:
    return max(1, min(num_segments, _env_int("PAPER2MANIM_SEGMENT_CONCURRENCY", 5)))


def _verify_concurrency() -> int:
    return _env_int("PAPER2MANIM_VERIFY_CONCURRENCY", 2)


def _should_run_project_consistency_check(quality_mode: str) -> bool:
    return quality_mode == "polished" or _env_truthy("PAPER2MANIM_ENABLE_PROJECT_CONSISTENCY_CHECK")


def _quality_mode_settings(questionnaire_answers: dict | None) -> dict[str, Any]:
    mode = (questionnaire_answers or {}).get("quality_mode", "balanced")
    settings = {
        "quality_mode": mode,
        "allow_repair": mode != "fast",
        "critique_threshold": 0.78 if mode == "polished" else 0.7,
        "base_render_quality": "-qm" if mode == "fast" else "-qh",
        "repair_render_quality": "-qp" if mode == "polished" else "-qh",
    }
    return settings


def _build_repair_feedback(
    *,
    verify_issues: list[str] | None = None,
    critique_issues: list[str] | None = None,
    transition_issues: list[str] | None = None,
) -> str:
    parts: list[str] = []
    if verify_issues:
        parts.append("Verifier issues:\n- " + "\n- ".join(verify_issues[:4]))
    if critique_issues:
        parts.append("Visual critique issues:\n- " + "\n- ".join(critique_issues[:4]))
    if transition_issues:
        parts.append("Transition issues to fix in this segment:\n- " + "\n- ".join(transition_issues[:4]))
    return "\n\n".join(parts)


def _find_existing_project(output_base: str, slug: str) -> str | None:
    """Find an existing incomplete project directory for the given concept slug.

    Scans ``output_base`` for directories whose name starts with ``slug_`` and
    contain a valid ``project_state.json`` that is NOT already completed.
    Returns the most recently updated directory, or None.
    """
    if not os.path.isdir(output_base):
        return None

    candidates: list[tuple[str, str]] = []  # (dir_path, updated_at)
    prefix = f"{slug}_"
    for entry in os.listdir(output_base):
        if not entry.startswith(prefix):
            continue
        full_path = os.path.join(output_base, entry)
        if not os.path.isdir(full_path):
            continue
        state = load_project(full_path)
        if state and state.get("status") != "completed":
            candidates.append((full_path, state.get("updated_at", "")))

    if not candidates:
        return None
    # Return the most recently updated project
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]


def _save_storyboard(project_dir: str, storyboard: dict) -> None:
    """Persist the storyboard to ``project_dir/storyboard.json``."""
    path = os.path.join(project_dir, "storyboard.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(storyboard, f, indent=2)


def _load_storyboard(project_dir: str) -> dict | None:
    """Load a previously saved storyboard, or None if missing/corrupt."""
    path = os.path.join(project_dir, "storyboard.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _drain_status_queue(q: Queue) -> Iterator[dict]:
    """Drain all pending messages from the shared status queue.

    Workers put pre-formatted dicts with ``stage``, ``segment_id``,
    ``status``, etc.  We yield them as-is for the caller to forward.
    """
    while True:
        try:
            msg = q.get_nowait()
        except Empty:
            break
        if msg.get("segment_id") is not None and msg.get("status"):
            yield msg


def _iter_completed_futures(
    futures_map: dict[Any, Any],
    status_queue: Queue,
    poll_interval: float = 0.1,
) -> Iterator[tuple[Any, Any]]:
    """Yield futures as they complete while continuously draining worker status.

    This keeps the CLI responsive during long-running segment work instead of
    buffering all status updates until a whole segment finishes.
    """
    pending = set(futures_map)
    while pending:
        done, pending = wait(pending, timeout=poll_interval, return_when=FIRST_COMPLETED)
        yield from ((None, msg) for msg in _drain_status_queue(status_queue))
        for fut in done:
            yield fut, futures_map[fut]


def _save_pipeline_summary(
    timings: list[tuple[str, str, float]],
    project_dir: str,
    concept: str = "",
    tool_call_counts: dict[str, int] | None = None,
    token_summary: dict | None = None,
    runtime_metrics: dict[str, Any] | None = None,
    total_elapsed_seconds: float | None = None,
) -> str:
    """Write a plain-text pipeline summary to ``project_dir/pipeline_summary.txt``."""
    import time as _time

    total = total_elapsed_seconds if total_elapsed_seconds is not None else sum(e for _, _, e in timings)
    lines: list[str] = []
    lines.append("Pipeline Summary")
    lines.append("=" * 50)
    if concept:
        lines.append(f"Concept : {concept}")
    lines.append(f"Date    : {_time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append(f"{'Status':<8} {'Stage':<25} {'Time':>16}")
    lines.append("-" * 58)
    for name, status, elapsed in timings:
        tag = {"ok": "OK", "skipped": "SKIP", "partial": "WARN"}.get(status, "ERR")
        lines.append(f"{tag:<8} {name:<25} {_format_duration(elapsed):>16}")
    lines.append("-" * 58)
    lines.append(f"{'':8} {'Total':<25} {_format_duration(total):>16}")
    lines.append("")

    lines.append("Tool Calls")
    lines.append("=" * 50)
    tool_call_counts = tool_call_counts or {}
    total_tool_calls = sum(tool_call_counts.values())
    lines.append(f"Total  : {total_tool_calls}")
    lines.append("")
    if tool_call_counts:
        for tool_name, count in sorted(tool_call_counts.items()):
            lines.append(f"- {tool_name}")
            lines.append(f"  Calls : {count}")
            lines.append("")
    else:
        lines.append("No tool calls recorded.")
        lines.append("")

    if runtime_metrics:
        lines.append("Runtime Metrics")
        lines.append("=" * 50)
        lines.append(f"Planner API calls      : {runtime_metrics.get('planner_api_calls', 0)}")
        lines.append(f"Segment repairs        : {runtime_metrics.get('segment_repairs', 0)}")
        lines.append(f"Code patch repairs     : {runtime_metrics.get('code_patch_repairs', 0)}")
        lines.append(f"Full regen repairs     : {runtime_metrics.get('full_regen_repairs', 0)}")
        lines.append(f"Same-run cache hits    : {runtime_metrics.get('same_run_cache_hits', 0)}")
        lines.append(f"Stitch re-encodes      : {runtime_metrics.get('stitch_reencode_count', 0)}")
        lines.append(f"Copy-trim fast paths   : {runtime_metrics.get('copy_trim_fast_paths', 0)}")
        stitch_modes = runtime_metrics.get("stitch_mode_by_segment") or {}
        if stitch_modes:
            lines.append("")
            for seg_id, mode in sorted(stitch_modes.items(), key=lambda item: int(item[0])):
                lines.append(f"  Segment {seg_id:<2} stitch : {mode}")
        lines.append("")

    if token_summary:
        lines.append("Token Usage & Cost")
        lines.append("=" * 50)
        lines.append(f"Total input tokens  : {token_summary.get('total_input_tokens', 0):,}")
        lines.append(f"Total output tokens : {token_summary.get('total_output_tokens', 0):,}")
        lines.append(f"Cached input tokens : {token_summary.get('cached_input_tokens', 0):,}")
        lines.append(f"Total API calls     : {token_summary.get('total_api_calls', 0)}")
        lines.append(f"TTS API calls       : {token_summary.get('tts_api_calls', 0)}")
        lines.append(f"Estimated cost      : ${token_summary.get('estimated_cost_usd', 0):.4f}")
        lines.append(f"Estimated savings   : ${token_summary.get('estimated_cache_savings_usd', 0):.4f}")
        if token_summary.get("fallback_invocations", 0):
            lines.append(f"Provider fallbacks  : {token_summary.get('fallback_invocations', 0)}")
        lines.append("")
        if token_summary.get("model_profile"):
            lines.append("Models")
            lines.append("=" * 50)
            for stage_name, stage_model in token_summary["model_profile"].items():
                lines.append(f"{stage_name:<12}: {stage_model}")
            lines.append("")
        breakdown = token_summary.get("breakdown", {})
        for stage_name, stage_data in breakdown.items():
            lines.append(f"  {stage_name.capitalize()}:")
            lines.append(f"    Input tokens  : {stage_data.get('input_tokens', 0):,}")
            lines.append(f"    Output tokens : {stage_data.get('output_tokens', 0):,}")
            if stage_data.get("cached_input_tokens", 0):
                lines.append(f"    Cached input  : {stage_data.get('cached_input_tokens', 0):,}")
            lines.append(f"    API calls     : {stage_data.get('api_calls', 0)}")
            lines.append(f"    Cost          : ${stage_data.get('cost_usd', 0):.4f}")
            lines.append("")

    os.makedirs(project_dir, exist_ok=True)
    summary_path = os.path.join(project_dir, "pipeline_summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return summary_path


# ── Token summary builder ────────────────────────────────────────────

def _build_token_summary(pipeline_tokens, planning_tokens, coding_tokens, verification_tokens, tts_api_calls=0):
    """Build a summary dict of token usage and estimated cost across stages."""
    planning_model = resolve_stage_model("plan").model
    coding_model = resolve_stage_model("code").model
    verify_model = resolve_stage_model("verify").model
    total_in = pipeline_tokens["input_tokens"]
    total_out = pipeline_tokens["output_tokens"]
    total_calls = pipeline_tokens["api_calls"]
    planning_cost = estimate_cost(
        planning_tokens["input_tokens"], planning_tokens["output_tokens"], model=planning_model,
        cached_input_tokens=planning_tokens.get("cached_input_tokens", 0),
        cache_creation_tokens=planning_tokens.get("cache_creation_input_tokens", 0),
        cache_read_tokens=planning_tokens.get("cache_read_input_tokens", 0),
    )
    coding_cost = estimate_cost(
        coding_tokens["input_tokens"], coding_tokens["output_tokens"], model=coding_model,
        cached_input_tokens=coding_tokens.get("cached_input_tokens", 0),
        cache_creation_tokens=coding_tokens.get("cache_creation_input_tokens", 0),
        cache_read_tokens=coding_tokens.get("cache_read_input_tokens", 0),
    )
    total_cost = planning_cost + coding_cost
    verification_cost = estimate_cost(
        verification_tokens["input_tokens"], verification_tokens["output_tokens"], model=verify_model,
        cached_input_tokens=verification_tokens.get("cached_input_tokens", 0),
        cache_creation_tokens=verification_tokens.get("cache_creation_input_tokens", 0),
        cache_read_tokens=verification_tokens.get("cache_read_input_tokens", 0),
    )
    total_cost += verification_cost
    total_cached_input = pipeline_tokens.get("cached_input_tokens", 0)
    total_cache_savings = (
        estimate_cache_savings(planning_model, cached_input_tokens=planning_tokens.get("cached_input_tokens", 0), cache_read_tokens=planning_tokens.get("cache_read_input_tokens", 0))
        + estimate_cache_savings(coding_model, cached_input_tokens=coding_tokens.get("cached_input_tokens", 0), cache_read_tokens=coding_tokens.get("cache_read_input_tokens", 0))
        + estimate_cache_savings(verify_model, cached_input_tokens=verification_tokens.get("cached_input_tokens", 0), cache_read_tokens=verification_tokens.get("cache_read_input_tokens", 0))
    )
    return {
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "cached_input_tokens": total_cached_input,
        "total_api_calls": total_calls,
        "tts_api_calls": tts_api_calls,
        "cache_creation_input_tokens": pipeline_tokens.get("cache_creation_input_tokens", 0),
        "cache_read_input_tokens": pipeline_tokens.get("cache_read_input_tokens", 0),
        "fallback_invocations": pipeline_tokens.get("fallback_invocations", 0),
        "estimated_cost_usd": round(total_cost, 4),
        "estimated_cache_savings_usd": round(total_cache_savings, 4),
        "model_profile": model_profile_summary(),
        "breakdown": {
            "planning": {
                "model": planning_model,
                "input_tokens": planning_tokens["input_tokens"],
                "output_tokens": planning_tokens["output_tokens"],
                "cached_input_tokens": planning_tokens.get("cached_input_tokens", 0),
                "api_calls": planning_tokens["api_calls"],
                "cost_usd": round(planning_cost, 4),
            },
            "coding": {
                "model": coding_model,
                "input_tokens": coding_tokens["input_tokens"],
                "output_tokens": coding_tokens["output_tokens"],
                "cached_input_tokens": coding_tokens.get("cached_input_tokens", 0),
                "api_calls": coding_tokens["api_calls"],
                "cache_creation_input_tokens": coding_tokens.get("cache_creation_input_tokens", 0),
                "cache_read_input_tokens": coding_tokens.get("cache_read_input_tokens", 0),
                "cost_usd": round(coding_cost, 4),
            },
            "verification": {
                "model": verify_model,
                "input_tokens": verification_tokens["input_tokens"],
                "output_tokens": verification_tokens["output_tokens"],
                "cached_input_tokens": verification_tokens.get("cached_input_tokens", 0),
                "api_calls": verification_tokens["api_calls"],
                "cost_usd": round(verification_cost, 4),
            },
        },
    }


# ── Main segmented pipeline (synchronous generator for Streamlit) ────

def run_segmented_pipeline(
    concept: str,
    output_base: str = "output",
    max_retries: int = 3,
    previous_storyboard: dict | None = None,
    feedback: str | None = None,
    is_lite: bool = False,
    questionnaire_answers: dict | None = None,
    skip_audio: bool = False,
    render_timeout_seconds: int = 0,
    tts_timeout_seconds: int = 0,
    resume_dir: str | None = None,
    force_restart: bool = False,
) -> Iterator[dict]:
    """Run the full segmented pipeline, yielding progress updates.

    Each yielded dict has at least ``{"stage", "status"}``.
    The final yield has ``{"stage": "done", "final": True, ...}``.

    When *force_restart* is False (the default), the pipeline checks for an
    existing incomplete project for the same concept and resumes from where it
    left off, skipping stages that already completed successfully.
    """

    slug = _slugify(concept)
    quality_settings = _quality_mode_settings(questionnaire_answers)

    # ── Token tracking accumulators ──────────────────────────────────
    pipeline_tokens = new_token_counter()
    planning_tokens = new_token_counter()
    coding_tokens = new_token_counter()
    verification_tokens = new_token_counter()
    tts_api_calls = 0
    overall_start = time.perf_counter()
    runtime_metrics: dict[str, Any] = {
        "planner_api_calls": 0,
        "segment_repairs": 0,
        "code_patch_repairs": 0,
        "full_regen_repairs": 0,
        "same_run_cache_hits": 0,
        "stitch_reencode_count": 0,
        "copy_trim_fast_paths": 0,
        "stitch_mode_by_segment": {},
    }

    # ── Resumability: look for an existing incomplete project ─────────
    resumed = False
    project_dir: str | None = None
    state: dict | None = None

    def _flush_state() -> None:
        if project_dir and state is not None:
            save_project(project_dir, state)

    def _record_stage_done(stage_name: str, artifacts: list[str] | None = None) -> None:
        if project_dir is None:
            return
        mark_stage_done(project_dir, stage_name, artifacts=artifacts, state=state, persist=False)
        _flush_state()

    def _record_segment_stage(
        segment_id: int,
        stage_name: str,
        *,
        done: bool = True,
        artifacts: list[str] | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
        flush: bool = True,
    ) -> None:
        if project_dir is None:
            return
        mark_segment_stage(
            project_dir,
            segment_id,
            stage_name,
            done=done,
            artifacts=artifacts,
            error=error,
            metadata=metadata,
            state=state,
            persist=False,
        )
        if flush:
            _flush_state()

    def _record_project_complete() -> None:
        if project_dir is None:
            return
        mark_project_complete(project_dir, state=state, persist=False)
        _flush_state()

    if not force_restart:
        if resume_dir:
            state = load_project(resume_dir)
            if state:
                project_dir = resume_dir
                resumed = True
                yield {
                    "stage": "plan",
                    "status": f"Resuming from selected project ({os.path.basename(resume_dir)})...",
                    "resumed": True,
                }
        else:
            existing_dir = _find_existing_project(output_base, slug)
            if existing_dir:
                state = load_project(existing_dir)
                if state:
                    project_dir = existing_dir
                    resumed = True
                    yield {
                        "stage": "plan",
                        "status": f"Resuming from previous run ({os.path.basename(existing_dir)})...",
                        "resumed": True,
                    }

    # ── Step 1: Planning + streaming segment execution ────────────────

    storyboard = None
    partial_storyboard: dict[str, Any] | None = None
    segments: list[dict[str, Any]] = []
    num_segments = 0
    timings: list[tuple[str, str, float]] = []
    tts_results: dict[int, dict] = {}
    code_results: dict[int, dict] = {}
    tool_call_counts: dict[str, int] = {}
    stitch_errors: list[str] = []
    segment_results: dict[int, dict] = {}
    status_queue: Queue[dict] = Queue()
    _state_lock = threading.Lock()
    expensive_llm_gate = threading.Semaphore(_verify_concurrency())
    theme_name = ""
    color_palette: dict[str, str] = {}
    plan_start = time.perf_counter()
    pipeline_start: float | None = None
    pipeline_executor: ThreadPoolExecutor | None = None
    segment_futures: dict[Any, dict[str, Any]] = {}
    scheduled_segment_ids: set[int] = set()
    segments_done = 0
    pipeline_announced = False

    _3D_KEYWORDS = {"threedscene", "3d", "surface", "camera_rotation", "set_camera_orientation"}
    _UPDATER_KEYWORDS = {"always_redraw", "valuetracker", "updater", "add_updater"}

    def _merge_tool_calls(counts: dict[str, int] | None) -> None:
        if not counts:
            return
        for tool_name, count in counts.items():
            if not isinstance(count, int):
                continue
            tool_call_counts[tool_name] = tool_call_counts.get(tool_name, 0) + count

    def _prepare_segment(seg: dict[str, Any]) -> dict[str, Any]:
        seg.setdefault("scene_strategy", "clean_reset")
        seg.setdefault("render_risk", "medium")
        seg.setdefault("expensive_features_allowed", False)
        seg.setdefault("final_anchor_required", seg.get("end_state", "Keep a meaningful anchor visible at the end."))
        if seg.get("complexity") == "complex":
            vis = (seg.get("visual_instructions") or "").lower()
            eqs = seg.get("equations_latex", [])
            anims = seg.get("animations", [])
            has_3d = any(kw in vis for kw in _3D_KEYWORDS)
            has_updaters = any(kw in vis for kw in _UPDATER_KEYWORDS)
            if not has_3d and not has_updaters and len(eqs) <= 2 and len(anims) <= 5:
                seg["complexity"] = "medium"
        return seg

    def _ensure_project_dir(total_segments: int, *, theme_override: str = "", palette_override: dict[str, str] | None = None) -> None:
        nonlocal project_dir, state, partial_storyboard, theme_name, color_palette
        if theme_override:
            theme_name = theme_override
        if palette_override:
            color_palette = palette_override
        if partial_storyboard is None:
            partial_storyboard = {
                "theme_name": theme_name,
                "color_palette": color_palette,
                "segments": [],
            }
        if project_dir is None:
            project_seed = partial_storyboard if partial_storyboard else {"concept": concept, "segments": total_segments}
            project_dir = os.path.join(output_base, f"{slug}_{id(project_seed) % 10000:04d}")
            state = create_project(project_dir, concept, slug, total_segments=total_segments)

    def _record_partial_segment(seg: dict[str, Any]) -> None:
        nonlocal partial_storyboard
        if partial_storyboard is None:
            return
        existing_segments = [s for s in partial_storyboard["segments"] if s.get("id") != seg["id"]]
        existing_segments.append(seg)
        existing_segments.sort(key=lambda item: item.get("id", 0))
        partial_storyboard["segments"] = existing_segments

    def _ensure_pipeline_executor(total_segments: int) -> bool:
        nonlocal pipeline_executor, pipeline_start
        if pipeline_executor is not None:
            return False
        pipeline_executor = ThreadPoolExecutor(max_workers=_segment_concurrency(total_segments))
        pipeline_start = time.perf_counter()
        return True

    def _consume_segment_future(fut: Any, seg: dict[str, Any]) -> Iterator[dict]:
        nonlocal segments_done
        seg_id = seg["id"]
        try:
            seg_result = fut.result()
        except Exception as exc:
            seg_result = {
                "segment_id": seg_id,
                "tts_result": {"success": False},
                "code_result": {"success": False, "error": str(exc)},
                "stitch_path": None,
                "stitch_error": str(exc),
                "token_usage": None,
                "tool_call_counts": None,
                "tts_api_call": False,
            }

        segment_results[seg_id] = seg_result
        segments_done += 1

        has_code = _has_valid_code(seg_result["code_result"])
        yield {
            "stage": "code",
            "segment_id": seg_id,
            "status": (
                f"Segment {seg_id}: complete ({segments_done}/{max(num_segments, len(scheduled_segment_ids))})"
                if has_code
                else f"Segment {seg_id}: failed ({segments_done}/{max(num_segments, len(scheduled_segment_ids))})"
            ),
            "segment_phase": "done" if has_code else "failed",
            "segment_final": True,
        }

    def _drain_segment_activity(*, wait_for_completion: bool = False, poll_interval: float = 0.1) -> Iterator[dict]:
        while True:
            yielded = False
            pending = set(segment_futures)
            done = {fut for fut in pending if fut.done()}
            if wait_for_completion and pending and not done:
                done, _ = wait(pending, timeout=poll_interval, return_when=FIRST_COMPLETED)
            status_updates = list(_drain_status_queue(status_queue))
            if status_updates:
                yielded = True
                for msg in status_updates:
                    yield msg
            if done:
                yielded = True
                for fut in list(done):
                    seg = segment_futures.pop(fut)
                    yield from _consume_segment_future(fut, seg)
            if not wait_for_completion or not segment_futures:
                if not yielded:
                    break
                if not wait_for_completion:
                    break

    def _schedule_segment(seg: dict[str, Any]) -> bool:
        nonlocal pipeline_announced, num_segments
        seg_id = seg["id"]
        if seg_id in scheduled_segment_ids:
            return False
        _prepare_segment(seg)
        executor_created = _ensure_pipeline_executor(max(num_segments, len(scheduled_segment_ids) + 1))
        if executor_created and not pipeline_announced:
            pipeline_announced = True
        scheduled_segment_ids.add(seg_id)
        segment_futures[pipeline_executor.submit(_run_segment_pipeline, seg)] = seg  # type: ignore[union-attr]
        return executor_created

    # ── Per-segment pipeline worker ──────────────────────────────────

    def _run_segment_pipeline(
        seg: dict,
        few_shot_example: str = "",
        repair_feedback: str = "",
        existing_code: str = "",
        existing_video_path: str | None = None,
        rerun_mode: str = "full",
    ) -> dict:
        """Run the full pipeline for one segment: TTS → Code → HD Render → Stitch.

        Returns a result dict with tts_result, code_result, stitch_path, etc.
        Communicates progress via the shared *status_queue*.
        """
        seg_id = seg["id"]
        seg_output_dir = os.path.join(project_dir, f"segment_{seg_id}")
        os.makedirs(seg_output_dir, exist_ok=True)

        result: dict[str, Any] = {
            "segment_id": seg_id,
            "tts_result": {"success": False, "audio_path": None, "duration": 0.0},
            "code_result": {"success": False},
            "verify_result": None,
            "critique_result": None,
            "stitch_path": None,
            "stitch_error": None,
            "token_usage": None,
            "verify_token_usage": None,
            "tool_call_counts": None,
            "tts_api_call": False,
            "repair_attempted": False,
            "final_accepted_critique_score": None,
            "verification_tier": "unverified",
            "quality_risk": seg.get("render_risk", "medium"),
            "critique_skipped": False,
            "expensive_features": [],
            "stitch_mode": None,
            "timing_normalization": None,
        }

        # ── Phase 1: TTS ──────────────────────────────────────────
        if not skip_audio:
            audio_path = os.path.join(project_dir, f"segment_{seg_id}_audio.wav")
            audio_script_hash = _hash_text(seg.get("audio_script", ""))

            # Check per-segment TTS cache
            cached_tts = False
            existing_tts = tts_results.get(seg_id, {})
            existing_hash = existing_tts.get("audio_script_hash")
            same_script = existing_hash in {None, audio_script_hash}
            if existing_tts.get("success") and existing_tts.get("audio_path") and same_script:
                result["tts_result"] = {
                    "success": True,
                    "audio_path": existing_tts.get("audio_path"),
                    "duration": existing_tts.get("duration", 0.0),
                    "audio_script_hash": existing_hash or audio_script_hash,
                }
                cached_tts = True
            elif state and is_segment_stage_done(state, seg_id, "tts"):
                seg_info = state.get("segments", {}).get(str(seg_id), {}).get("tts", {})
                cached_hash = seg_info.get("audio_script_hash")
                cached_duration = seg_info.get("duration", 0.0)
                hash_matches = cached_hash in {None, audio_script_hash}
                if hash_matches and os.path.isfile(audio_path):
                    result["tts_result"] = {
                        "success": True,
                        "audio_path": audio_path,
                        "duration": cached_duration,
                        "audio_script_hash": cached_hash or audio_script_hash,
                    }
                    cached_tts = True
                elif hash_matches:
                    found = next((a for a in seg_info.get("artifacts", []) if a and os.path.isfile(a)), None)
                    if found:
                        result["tts_result"] = {
                            "success": True,
                            "audio_path": found,
                            "duration": cached_duration,
                            "audio_script_hash": cached_hash or audio_script_hash,
                        }
                        cached_tts = True

            if cached_tts:
                if not resumed:
                    runtime_metrics["same_run_cache_hits"] += 1
                status_queue.put({
                    "stage": "tts", "segment_id": seg_id,
                    "status": f"Segment {seg_id}: TTS cached",
                    "segment_phase": "done", "segment_final": True,
                    "skipped": True,
                })
            else:
                status_queue.put({
                    "stage": "tts", "segment_id": seg_id,
                    "status": f"Segment {seg_id}: generating voiceover...",
                    "segment_phase": "running", "segment_final": False,
                })
                loop = asyncio.new_event_loop()
                try:
                    coro = generate_voiceover_async(seg["audio_script"], audio_path)
                    if tts_timeout_seconds > 0:
                        coro = asyncio.wait_for(coro, timeout=tts_timeout_seconds)
                    tts_r = loop.run_until_complete(coro)
                    result["tts_result"] = tts_r
                    if tts_r.get("success"):
                        result["tts_result"]["audio_script_hash"] = audio_script_hash
                        result["tts_api_call"] = True
                        with _state_lock:
                            _record_segment_stage(
                                seg_id,
                                "tts",
                                done=True,
                                artifacts=[tts_r.get("audio_path", "")],
                                metadata={
                                    "duration": tts_r.get("duration", 0.0),
                                    "audio_script_hash": audio_script_hash,
                                },
                            )
                        status_queue.put({
                            "stage": "tts", "segment_id": seg_id,
                            "status": f"Segment {seg_id}: TTS done",
                            "segment_phase": "done", "segment_final": True,
                        })
                    else:
                        with _state_lock:
                            _record_segment_stage(seg_id, "tts", done=False, error=tts_r.get("error", ""))
                        status_queue.put({
                            "stage": "tts", "segment_id": seg_id,
                            "status": f"Segment {seg_id}: TTS failed",
                            "segment_phase": "failed", "segment_final": True,
                        })
                except Exception as e:
                    result["tts_result"] = {"success": False, "error": str(e), "audio_path": None, "duration": 0}
                    with _state_lock:
                        _record_segment_stage(seg_id, "tts", done=False, error=str(e))
                    status_queue.put({
                        "stage": "tts", "segment_id": seg_id,
                        "status": f"Segment {seg_id}: TTS error",
                        "segment_phase": "failed", "segment_final": True,
                    })
                finally:
                    loop.close()

        def _run_codegen(extra_repair_feedback: str = "") -> dict:
            tts_r = result["tts_result"]
            coder_instructions = seg["visual_instructions"] if is_lite else seg
            last_update: dict = {}
            for update in run_coder_agent(
                instructions=coder_instructions,
                max_retries=max_retries,
                audio_script=seg.get("audio_script", ""),
                audio_duration=tts_r.get("duration", 0.0) or 0.0,
                complexity=seg.get("complexity", "complex"),
                scene_class_name=f"Segment{seg_id}Scene",
                output_dir=seg_output_dir,
                theme_name=theme_name,
                color_palette=color_palette,
                segment_id=seg_id,
                few_shot_example=few_shot_example,
                repair_feedback="\n\n".join(part for part in [repair_feedback, extra_repair_feedback] if part),
                quality_mode=quality_settings["quality_mode"],
            ):
                last_update = update
                status_queue.put({
                    "stage": "code", "segment_id": seg_id,
                    "status": update.get("status", ""),
                    "segment_phase": update.get("phase", "running"),
                    "segment_final": bool(update.get("final")),
                    "code": update.get("code"),
                    "thinking": update.get("thinking"),
                    "stream_event": update.get("stream_event"),
                    "tool_call": (
                        {
                            "name": update.get("tool_call", {}).get("name"),
                            "params": update.get("tool_call", {}).get("input", {}),
                        }
                        if update.get("tool_call")
                        else None
                    ),
                    "tool_result": (
                        {
                            "name": update.get("tool_result", {}).get("name"),
                            "output": update.get("tool_result", {}).get("output", ""),
                        }
                        if update.get("tool_result")
                        else None
                    ),
                })
            return last_update

        def _run_code_patch(base_code: str, extra_repair_feedback: str = "") -> dict:
            original_instructions = seg["visual_instructions"] if isinstance(seg, dict) else str(seg)
            last_update: dict = {}
            for update in run_code_patch_agent(
                code=base_code,
                repair_feedback="\n\n".join(part for part in [repair_feedback, extra_repair_feedback] if part),
                complexity=seg.get("complexity", "complex"),
                scene_class_name=f"Segment{seg_id}Scene",
                segment_id=seg_id,
                original_instructions=original_instructions,
            ):
                last_update = update
                status_queue.put({
                    "stage": "code_retry", "segment_id": seg_id,
                    "status": update.get("status", ""),
                    "segment_phase": update.get("phase", "running"),
                    "segment_final": bool(update.get("final")),
                    "code": update.get("code"),
                    "thinking": update.get("thinking"),
                    "stream_event": update.get("stream_event"),
                    "tool_call": (
                        {
                            "name": update.get("tool_call", {}).get("name"),
                            "params": update.get("tool_call", {}).get("input", {}),
                        }
                        if update.get("tool_call")
                        else None
                    ),
                    "tool_result": (
                        {
                            "name": update.get("tool_result", {}).get("name"),
                            "output": update.get("tool_result", {}).get("output", ""),
                        }
                        if update.get("tool_result")
                        else None
                    ),
                })
            return last_update

        def _absorb_code_update(update: dict) -> None:
            if update.get("token_usage"):
                result["token_usage"] = update.get("token_usage")
            if update.get("tool_call_counts"):
                result["tool_call_counts"] = update.get("tool_call_counts")

        def _attempt_patch_then_regen(base_code: str, patch_feedback: str, *, allow_full_regen: bool = True) -> dict:
            runtime_metrics["code_patch_repairs"] += 1
            patched_update = _run_code_patch(base_code, patch_feedback)
            _absorb_code_update(patched_update)
            if _has_valid_code(patched_update):
                return patched_update
            if not allow_full_regen:
                return patched_update
            runtime_metrics["full_regen_repairs"] += 1
            status_queue.put({
                "stage": "code_retry", "segment_id": seg_id,
                "status": f"Segment {seg_id}: targeted patch failed, falling back to full regeneration...",
                "segment_phase": "running", "segment_final": False,
            })
            regenerated = _run_codegen(extra_repair_feedback=patch_feedback)
            _absorb_code_update(regenerated)
            return regenerated

        def _verify_and_render(code_r: dict, render_quality: str, *, repaired: bool = False) -> tuple[dict | None, dict | None]:
            verify_result = None
            critique_result = None
            if code_r.get("code"):
                normalization = normalize_scene_timing(
                    code_r["code"],
                    result["tts_result"].get("duration", 0.0) or 0.0,
                )
                if normalization.changed and normalization.code != code_r["code"]:
                    code_r["code"] = normalization.code
                    result["timing_normalization"] = {
                        "mode": normalization.mode,
                        "estimated_before": normalization.estimated_before,
                        "estimated_after": normalization.estimated_after,
                        "residual_delta": normalization.residual_delta,
                    }
                    status_queue.put({
                        "stage": "verify", "segment_id": seg_id,
                        "status": (
                            f"Segment {seg_id}: timing normalized via {normalization.mode} "
                            f"(residual {abs(normalization.residual_delta or 0.0):.2f}s)"
                        ),
                        "segment_phase": "running", "segment_final": False,
                    })
                verify_tokens = result.get("verify_token_usage") or new_token_counter()
                verify_fingerprint = _build_verify_fingerprint(
                    code_r["code"],
                    result["tts_result"].get("duration", 0.0) or 0.0,
                    quality_settings["quality_mode"],
                    seg.get("render_risk", "medium"),
                )
                with _state_lock:
                    verify_entry = _get_segment_stage_entry(state, seg_id, "verify")
                cached_verify = verify_entry.get("done") and verify_entry.get("fingerprint") == verify_fingerprint
                if cached_verify:
                    if not resumed:
                        runtime_metrics["same_run_cache_hits"] += 1
                    verify_result = type("CachedVerifyResult", (), {
                        "segment_id": seg_id,
                        "passed": verify_entry.get("passed", True),
                        "issues": verify_entry.get("issues", []),
                        "suggestions": verify_entry.get("suggestions", []),
                        "static_issues": verify_entry.get("static_issues", []),
                        "verification_tier": verify_entry.get("verification_tier", "static"),
                        "quality_risk": verify_entry.get("quality_risk", seg.get("render_risk", "medium")),
                        "expensive_features": verify_entry.get("expensive_features", []),
                    })()
                    status_queue.put({
                        "stage": "verify", "segment_id": seg_id,
                        "status": f"Segment {seg_id}: verification cached",
                        "segment_phase": "done", "segment_final": True,
                        "verification_tier": getattr(verify_result, "verification_tier", "static"),
                        "quality_risk": getattr(verify_result, "quality_risk", seg.get("render_risk", "medium")),
                        "skipped": True,
                    })
                else:
                    status_queue.put({
                        "stage": "verify", "segment_id": seg_id,
                        "status": f"Segment {seg_id}: verifying code quality...",
                        "segment_phase": "running", "segment_final": False,
                    })
                    with expensive_llm_gate:
                        verify_result = verify_segment_code(
                            seg_id,
                            code_r["code"],
                            segment_context=seg.get("visual_instructions", ""),
                            audio_duration=result["tts_result"].get("duration", 0.0) or 0.0,
                            token_counter=verify_tokens,
                            quality_mode=quality_settings["quality_mode"],
                            render_risk=seg.get("render_risk", "medium"),
                        )
                    result["verify_token_usage"] = verify_tokens
                    with _state_lock:
                        _record_segment_stage(
                            seg_id,
                            "verify",
                            done=True,
                            metadata={
                                "fingerprint": verify_fingerprint,
                                "passed": getattr(verify_result, "passed", True),
                                "issues": list(getattr(verify_result, "issues", []) or []),
                                "suggestions": list(getattr(verify_result, "suggestions", []) or []),
                                "static_issues": list(getattr(verify_result, "static_issues", []) or []),
                                "verification_tier": getattr(verify_result, "verification_tier", "static"),
                                "quality_risk": getattr(verify_result, "quality_risk", seg.get("render_risk", "medium")),
                                "expensive_features": list(getattr(verify_result, "expensive_features", []) or []),
                            },
                        )
                status_queue.put({
                    "stage": "verify", "segment_id": seg_id,
                    "status": (
                        f"Segment {seg_id}: verification passed"
                        if verify_result.passed
                        else f"Segment {seg_id}: verification warnings - {'; '.join(verify_result.issues[:2])}"
                    ),
                    "segment_phase": "done" if verify_result.passed else "failed",
                    "segment_final": True,
                    "verification_tier": getattr(verify_result, "verification_tier", "static"),
                    "quality_risk": getattr(verify_result, "quality_risk", seg.get("render_risk", "medium")),
                })
                result["verification_tier"] = getattr(verify_result, "verification_tier", "static")
                result["quality_risk"] = getattr(verify_result, "quality_risk", seg.get("render_risk", "medium"))
                result["expensive_features"] = list(getattr(verify_result, "expensive_features", []) or [])

            if _has_valid_code(code_r) and code_r.get("code"):
                status_queue.put({
                    "stage": "render", "segment_id": seg_id,
                    "status": f"Segment {seg_id}: HD rendering...",
                    "segment_phase": "running", "segment_final": False,
                })
                hd_job = RenderJob(
                    segment_id=seg_id,
                    code=code_r["code"],
                    quality_flag=render_quality,
                    timeout_seconds=render_timeout_seconds or 300,
                    output_dir=seg_output_dir,
                )
                try:
                    hd_result = submit_render_job(hd_job).result()
                except Exception as exc:
                    hd_result = type("RenderFailure", (), {"success": False, "video_path": None, "error": str(exc)})()
                if hd_result and hd_result.success and hd_result.video_path:
                    code_r["video_path"] = hd_result.video_path
                    with _state_lock:
                        _record_segment_stage(
                            seg_id,
                            "hd_render",
                            done=True,
                            artifacts=[hd_result.video_path],
                            metadata={
                                "quality_risk": result["quality_risk"],
                                "verification_tier": result["verification_tier"],
                            },
                        )
                    status_queue.put({
                        "stage": "render", "segment_id": seg_id,
                        "status": f"Segment {seg_id}: HD render done",
                        "segment_phase": "done", "segment_final": True,
                    })
                    critique_needed = bool(
                        repaired
                        or (verify_result and not getattr(verify_result, "passed", True))
                        or seg.get("render_risk", "medium") == "high"
                        or result["expensive_features"]
                    )
                    critique_fingerprint = _build_critique_fingerprint(
                        code_r["code"],
                        render_quality,
                        result["tts_result"].get("duration", 0.0) or 0.0,
                    )
                    with _state_lock:
                        critique_entry = _get_segment_stage_entry(state, seg_id, "critique")
                    cached_critique = critique_entry.get("done") and critique_entry.get("fingerprint") == critique_fingerprint
                    if cached_critique:
                        if not resumed:
                            runtime_metrics["same_run_cache_hits"] += 1
                        critique_result = type("CachedCritiqueResult", (), {
                            "passed": critique_entry.get("passed", True),
                            "score": critique_entry.get("score", 0.0),
                            "issues": critique_entry.get("issues", []),
                            "suggestions": critique_entry.get("suggestions", []),
                            "sub_scores": critique_entry.get("sub_scores", {}),
                        })()
                        result["critique_skipped"] = critique_entry.get("critique_skipped", False)
                    elif critique_needed:
                        critique_tokens = result.get("verify_token_usage") or new_token_counter()
                        with expensive_llm_gate:
                            critique_result = critique_video(
                                hd_result.video_path,
                                segment_context=seg.get("visual_instructions", ""),
                                token_counter=critique_tokens,
                                use_vision_model=bool(
                                    repaired
                                    or seg.get("render_risk", "medium") == "high"
                                    or not verify_result
                                    or not getattr(verify_result, "passed", True)
                                ),
                            )
                        result["verify_token_usage"] = critique_tokens
                        with _state_lock:
                            _record_segment_stage(
                                seg_id,
                                "critique",
                                done=True,
                                metadata={
                                    "fingerprint": critique_fingerprint,
                                    "passed": getattr(critique_result, "passed", True),
                                    "score": getattr(critique_result, "score", 0.0),
                                    "issues": list(getattr(critique_result, "issues", []) or []),
                                    "suggestions": list(getattr(critique_result, "suggestions", []) or []),
                                    "sub_scores": dict(getattr(critique_result, "sub_scores", {}) or {}),
                                    "critique_skipped": False,
                                },
                            )
                    else:
                        result["critique_skipped"] = True
                        critique_result = None
                        with _state_lock:
                            _record_segment_stage(
                                seg_id,
                                "critique",
                                done=True,
                                metadata={
                                    "fingerprint": critique_fingerprint,
                                    "passed": True,
                                    "score": None,
                                    "issues": [],
                                    "suggestions": [],
                                    "sub_scores": {},
                                    "critique_skipped": True,
                                },
                            )
                        status_queue.put({
                            "stage": "verify", "segment_id": seg_id,
                            "status": f"Segment {seg_id}: visual critique skipped (low risk)",
                            "segment_phase": "done", "segment_final": True,
                            "critique_skipped": True,
                        })
                    if critique_result is not None:
                        result["final_accepted_critique_score"] = getattr(critique_result, "score", None)
                        status_queue.put({
                            "stage": "verify", "segment_id": seg_id,
                            "status": (
                                f"Segment {seg_id}: visual critique passed"
                                if critique_result.passed
                                else f"Segment {seg_id}: visual critique warnings - {'; '.join(critique_result.issues[:2])}"
                            ),
                            "segment_phase": "done" if critique_result.passed else "failed",
                            "segment_final": True,
                            "critique_skipped": False,
                        })
                else:
                    err = hd_result.error if hd_result else "Unknown"
                    with _state_lock:
                        _record_segment_stage(seg_id, "hd_render", done=False, error=err or "Unknown")
                    status_queue.put({
                        "stage": "render", "segment_id": seg_id,
                        "status": f"Segment {seg_id}: HD render failed, using preview",
                        "segment_phase": "failed", "segment_final": True,
                    })
            return verify_result, critique_result

        # ── Phase 2-3: Code generation, verification, render, repair ──
        code_cached = False
        code_r = result["code_result"]
        allow_cached_codegen = (
            not repair_feedback
            and not few_shot_example
            and not existing_code
            and rerun_mode == "full"
        )
        if allow_cached_codegen and state and is_segment_stage_done(state, seg_id, "code"):
            code_entry = state.get("segments", {}).get(str(seg_id), {}).get("code", {})
            seg_artifacts = code_entry.get("artifacts", [])
            video_found = None
            for art in seg_artifacts:
                if art and os.path.isfile(art):
                    video_found = art
                    break
            if not video_found and os.path.isdir(seg_output_dir):
                for f_name in os.listdir(seg_output_dir):
                    if f_name.endswith(".mp4"):
                        video_found = os.path.join(seg_output_dir, f_name)
                        break
            if video_found:
                if not resumed:
                    runtime_metrics["same_run_cache_hits"] += 1
                result["code_result"] = {
                    "success": True,
                    "video_path": video_found,
                    "code_validated": True,
                    "code": "",
                }
                code_cached = True
                result["quality_risk"] = code_entry.get("quality_risk", result["quality_risk"])
                result["verification_tier"] = code_entry.get("verification_tier", result["verification_tier"])
                result["repair_attempted"] = code_entry.get("repair_attempted", False)
                critique_entry = state.get("segments", {}).get(str(seg_id), {}).get("critique", {})
                result["critique_skipped"] = critique_entry.get("critique_skipped", False)
                result["final_accepted_critique_score"] = critique_entry.get("score")
                status_queue.put({
                    "stage": "code", "segment_id": seg_id,
                    "status": f"Segment {seg_id}: code cached",
                    "segment_phase": "done", "segment_final": True,
                    "skipped": True,
                })

        if rerun_mode == "stitch_only":
            result["code_result"] = {
                "success": True,
                "video_path": existing_video_path,
                "code_validated": bool(existing_video_path or existing_code),
                "code": existing_code,
            }
            code_r = result["code_result"]
        elif rerun_mode == "render_only" and existing_code:
            result["code_result"] = {
                "success": True,
                "video_path": existing_video_path,
                "code_validated": True,
                "code": existing_code,
            }
            code_r = result["code_result"]
            status_queue.put({
                "stage": "code", "segment_id": seg_id,
                "status": f"Segment {seg_id}: reusing validated code for render retry",
                "segment_phase": "done", "segment_final": True,
                "skipped": True,
            })
            verify_result, critique_result = _verify_and_render(code_r, quality_settings["base_render_quality"])
            result["verify_result"] = verify_result
            result["critique_result"] = critique_result
        elif rerun_mode == "patch" and existing_code:
            result["repair_attempted"] = True
            status_queue.put({
                "stage": "code_retry", "segment_id": seg_id,
                "status": f"Segment {seg_id}: repairing existing code...",
                "segment_phase": "running", "segment_final": False,
            })
            repaired_update = _attempt_patch_then_regen(existing_code, repair_feedback, allow_full_regen=True)
            result["code_result"] = repaired_update
            code_r = result["code_result"]
            with _state_lock:
                if _has_valid_code(code_r):
                    _record_segment_stage(
                        seg_id,
                        "code",
                        done=True,
                        artifacts=[code_r.get("video_path", "")],
                        metadata={
                            "quality_risk": result["quality_risk"],
                            "verification_tier": result["verification_tier"],
                            "repair_attempted": True,
                        },
                    )
                else:
                    _record_segment_stage(seg_id, "code", done=False, error=code_r.get("error", "Code repair failed"))
            repaired_verify, repaired_critique = _verify_and_render(
                code_r,
                quality_settings["repair_render_quality"],
                repaired=True,
            )
            result["verify_result"] = repaired_verify
            result["critique_result"] = repaired_critique
            status_queue.put({
                "stage": "code_retry", "segment_id": seg_id,
                "status": (
                    f"Segment {seg_id}: repair complete"
                    if _has_valid_code(code_r)
                    else f"Segment {seg_id}: repair failed"
                ),
                "segment_phase": "done" if _has_valid_code(code_r) else "failed",
                "segment_final": True,
            })
        elif not code_cached:
            initial_update = _run_codegen()
            result["code_result"] = initial_update
            _absorb_code_update(initial_update)

            has_code = _has_valid_code(initial_update)
            with _state_lock:
                if has_code:
                    _record_segment_stage(
                        seg_id,
                        "code",
                        done=True,
                        artifacts=[initial_update.get("video_path", "")],
                        metadata={
                            "quality_risk": seg.get("render_risk", "medium"),
                            "verification_tier": "pending",
                            "repair_attempted": False,
                        },
                    )
                else:
                    _record_segment_stage(seg_id, "code", done=False, error=initial_update.get("error", "Code generation failed"))

            code_r = result["code_result"]
            verify_result, critique_result = _verify_and_render(code_r, quality_settings["base_render_quality"])
            result["verify_result"] = verify_result
            result["critique_result"] = critique_result

            critique_needs_repair = bool(
                critique_result
                and (
                    not critique_result.passed
                    or (
                        getattr(critique_result, "score", None) is not None
                        and critique_result.score < quality_settings["critique_threshold"]
                    )
                )
            )
            verify_needs_repair = bool(verify_result and not verify_result.passed)

            if quality_settings["allow_repair"] and _has_valid_code(code_r) and (verify_needs_repair or critique_needs_repair):
                result["repair_attempted"] = True
                runtime_metrics["segment_repairs"] += 1
                repair_feedback = _build_repair_feedback(
                    verify_issues=(verify_result.issues if verify_result else []),
                    critique_issues=(critique_result.issues if critique_result else []),
                )
                status_queue.put({
                    "stage": "code_retry", "segment_id": seg_id,
                    "status": f"Segment {seg_id}: repairing quality issues...",
                    "segment_phase": "running", "segment_final": False,
                })
                repaired_update = _attempt_patch_then_regen(code_r.get("code", ""), repair_feedback, allow_full_regen=True)
                result["code_result"] = repaired_update
                code_r = result["code_result"]
                repaired_verify, repaired_critique = _verify_and_render(
                    code_r,
                    quality_settings["repair_render_quality"],
                    repaired=True,
                )
                result["verify_result"] = repaired_verify or verify_result
                result["critique_result"] = repaired_critique or critique_result
                with _state_lock:
                    if _has_valid_code(code_r):
                        _record_segment_stage(
                            seg_id,
                            "code",
                            done=True,
                            artifacts=[code_r.get("video_path", "")],
                            metadata={
                                "quality_risk": result["quality_risk"],
                                "verification_tier": result["verification_tier"],
                                "repair_attempted": True,
                            },
                        )
                    else:
                        _record_segment_stage(seg_id, "code", done=False, error=code_r.get("error", "Code repair failed"))
                status_queue.put({
                    "stage": "code_retry", "segment_id": seg_id,
                    "status": (
                        f"Segment {seg_id}: repair complete"
                        if _has_valid_code(code_r)
                        else f"Segment {seg_id}: repair failed"
                    ),
                    "segment_phase": "done" if _has_valid_code(code_r) else "failed",
                    "segment_final": True,
                })
        else:
            code_r = result["code_result"]

        # ── Phase 4: Stitch ───────────────────────────────────────
        if not skip_audio:
            stitch_cached = False
            allow_cached_stitch = not repair_feedback and not few_shot_example and rerun_mode == "full"
            if allow_cached_stitch and state and is_segment_stage_done(state, seg_id, "stitch"):
                stitched_path = os.path.join(project_dir, f"segment_{seg_id}_stitched.mp4")
                seg_stitch_info = state.get("segments", {}).get(str(seg_id), {}).get("stitch", {})
                if os.path.isfile(stitched_path):
                    result["stitch_path"] = stitched_path
                    result["stitch_mode"] = seg_stitch_info.get("stitch_mode")
                    stitch_cached = True
                else:
                    found_art = next((a for a in seg_stitch_info.get("artifacts", [])
                                      if a and os.path.isfile(a)), None)
                    if found_art:
                        result["stitch_path"] = found_art
                        result["stitch_mode"] = seg_stitch_info.get("stitch_mode")
                        stitch_cached = True

            if stitch_cached:
                if not resumed:
                    runtime_metrics["same_run_cache_hits"] += 1
                if result.get("stitch_mode"):
                    runtime_metrics["stitch_mode_by_segment"][str(seg_id)] = result["stitch_mode"]
                status_queue.put({
                    "stage": "stitch", "segment_id": seg_id,
                    "status": f"Segment {seg_id}: stitch cached",
                    "playable_segment": result["stitch_path"],
                    "segment_phase": "done", "segment_final": True,
                    "skipped": True,
                })
            else:
                video_path = existing_video_path or code_r.get("video_path")
                audio_path = result["tts_result"].get("audio_path")
                tts_success = result["tts_result"].get("success", False)

                if not video_path:
                    result["stitch_error"] = f"Segment {seg_id}: no video to stitch"
                elif not audio_path or not tts_success:
                    # No audio — use raw video
                    result["stitch_path"] = video_path
                    result["stitch_mode"] = "raw"
                    runtime_metrics["stitch_mode_by_segment"][str(seg_id)] = "raw"
                    with _state_lock:
                        _record_segment_stage(
                            seg_id,
                            "stitch",
                            done=True,
                            artifacts=[video_path],
                            metadata={"stitch_mode": "raw"},
                        )
                else:
                    stitched_output = os.path.join(project_dir, f"segment_{seg_id}_stitched.mp4")
                    stitch_r = None
                    for update in stitch_video_and_audio(video_path, audio_path, stitched_output):
                        if update.get("final"):
                            stitch_r = update

                    if stitch_r and stitch_r.get("success"):
                        result["stitch_path"] = stitch_r["output_path"]
                        result["stitch_mode"] = stitch_r.get("stitch_mode")
                        runtime_metrics["stitch_mode_by_segment"][str(seg_id)] = stitch_r.get("stitch_mode")
                        if stitch_r.get("copy_trim_fast_path"):
                            runtime_metrics["copy_trim_fast_paths"] += 1
                        if stitch_r.get("stitch_mode") in {"pad", "trim"}:
                            runtime_metrics["stitch_reencode_count"] += 1
                        with _state_lock:
                            _record_segment_stage(
                                seg_id,
                                "stitch",
                                done=True,
                                artifacts=[stitch_r["output_path"]],
                                metadata={"stitch_mode": stitch_r.get("stitch_mode")},
                            )
                        status_queue.put({
                            "stage": "stitch", "segment_id": seg_id,
                            "status": f"Segment {seg_id}: stitched",
                            "playable_segment": stitch_r["output_path"],
                            "segment_phase": "done", "segment_final": True,
                        })
                    else:
                        err = stitch_r.get("error", "unknown") if stitch_r else "unknown"
                        result["stitch_error"] = f"Segment {seg_id}: stitch failed ({err}), using raw video"
                        result["stitch_path"] = video_path
                        with _state_lock:
                            _record_segment_stage(seg_id, "stitch", done=False, error=err)
        else:
            # skip_audio: use video directly
            result["stitch_path"] = code_r.get("video_path")
            result["stitch_mode"] = "raw"
            runtime_metrics["stitch_mode_by_segment"][str(seg_id)] = "raw"

        return result

    if resumed and state and is_stage_done(state, "plan"):
        cached_sb = _load_storyboard(project_dir)
        if cached_sb and "segments" in cached_sb:
            storyboard = cached_sb
            segments = storyboard["segments"]
            num_segments = len(segments)
            theme_name = storyboard.get("theme_name", "")
            color_palette = storyboard.get("color_palette", {})
            timings.append(("Plan", "skipped", 0.0))
            yield {
                "stage": "plan",
                "status": f"Skipping (already completed) — {num_segments} segments",
                "skipped": True,
                "storyboard": storyboard,
                "num_segments": num_segments,
            }
            _ensure_project_dir(num_segments, theme_override=theme_name, palette_override=color_palette)
        else:
            resumed = False
            state = None

    if storyboard is None:
        yield {"stage": "plan", "status": "Starting segmented storyboard planning..."}

        planner_func = plan_segmented_storyboard_lite if is_lite else run_math2manim_planner
        planner_kwargs: dict = dict(
            max_retries=max_retries,
            previous_storyboard=previous_storyboard,
            feedback=feedback,
        )
        if questionnaire_answers:
            planner_kwargs["questionnaire_answers"] = questionnaire_answers

        for update in planner_func(concept, **planner_kwargs):
            partial_segment = update.get("segment_storyboard")
            if partial_segment:
                num_segments = max(num_segments, int(update.get("num_segments") or 0) or len(scheduled_segment_ids) + 1)
                theme_name = update.get("theme_name", theme_name)
                color_palette = update.get("color_palette", color_palette) or color_palette
                _ensure_project_dir(num_segments, theme_override=theme_name, palette_override=color_palette)
                _record_partial_segment(partial_segment)
                created_executor = _schedule_segment(partial_segment)
                if created_executor:
                    yield {
                        "stage": "pipeline",
                        "status": f"Processing {num_segments} segments as storyboard segments become ready...",
                        "num_segments": num_segments,
                    }

            if "status" in update:
                if pipeline_announced:
                    yield {"stage": "pipeline", "status": f"Planning: {update['status']}"}
                else:
                    yield {"stage": "plan", "status": update["status"]}

            yield from _drain_segment_activity(wait_for_completion=False)

            if update.get("final"):
                if "error" in update:
                    yield {"stage": "plan", "status": update["error"], "error": update["error"], "final": True}
                    if pipeline_executor is not None:
                        pipeline_executor.shutdown(wait=False, cancel_futures=False)
                    return
                storyboard = update["storyboard"]
                segments = storyboard["segments"]
                num_segments = len(segments)
                theme_name = storyboard.get("theme_name", theme_name)
                color_palette = storyboard.get("color_palette", color_palette) or color_palette
                try:
                    planner_tu = update.get("token_usage")
                    if planner_tu:
                        merge_token_usage(planning_tokens, planner_tu)
                        merge_token_usage(pipeline_tokens, planner_tu)
                        runtime_metrics["planner_api_calls"] = planner_tu.get("api_calls", planning_tokens["api_calls"])
                except Exception:
                    pass

        if not storyboard:
            yield {"stage": "plan", "status": "No storyboard generated.", "error": "Empty planner output.", "final": True}
            if pipeline_executor is not None:
                pipeline_executor.shutdown(wait=False, cancel_futures=False)
            return

        _ensure_project_dir(num_segments, theme_override=theme_name, palette_override=color_palette)
        prioritized_segments = sorted(segments, key=lambda s: (-_risk_rank(s.get("render_risk", "medium")), s.get("id", 0)))
        for seg in prioritized_segments:
            _prepare_segment(seg)
            if seg["id"] not in scheduled_segment_ids:
                created_executor = _schedule_segment(seg)
                if created_executor:
                    yield {
                        "stage": "pipeline",
                        "status": f"Processing {num_segments} segments as storyboard segments become ready...",
                        "num_segments": num_segments,
                    }

        plan_elapsed = time.perf_counter() - plan_start
        timings.append(("Plan", "ok", plan_elapsed))
        yield {
            "stage": "plan" if not pipeline_announced else "pipeline",
            "status": f"Storyboard planned: {num_segments} segments",
            "storyboard": storyboard,
            "num_segments": num_segments,
        }

        _record_stage_done("plan", artifacts=[])
        _save_storyboard(project_dir, storyboard)
    else:
        prioritized_segments = sorted(segments, key=lambda s: (-_risk_rank(s.get("render_risk", "medium")), s.get("id", 0)))
        for seg in prioritized_segments:
            _prepare_segment(seg)
            if seg["id"] not in scheduled_segment_ids:
                created_executor = _schedule_segment(seg)
                if created_executor:
                    yield {
                        "stage": "pipeline",
                        "status": f"Processing {num_segments} segments as storyboard segments become ready...",
                        "num_segments": num_segments,
                    }

    if pipeline_executor is None:
        pipeline_announced = True
        _ensure_pipeline_executor(max(1, num_segments))
        yield {
            "stage": "pipeline",
            "status": f"Processing {num_segments} segments in parallel (TTS \u2192 Code \u2192 Render \u2192 Stitch)...",
            "num_segments": num_segments,
        }
        prioritized_segments = sorted(segments, key=lambda s: (-_risk_rank(s.get("render_risk", "medium")), s.get("id", 0)))
        for seg in prioritized_segments:
            if seg["id"] not in scheduled_segment_ids:
                _schedule_segment(seg)

    yield from _drain_segment_activity(wait_for_completion=True)
    if pipeline_executor is not None:
        pipeline_executor.shutdown(wait=True, cancel_futures=False)

    pipeline_elapsed = 0.0 if pipeline_start is None else time.perf_counter() - pipeline_start

    # ── Aggregate results from all workers ────────────────────────────

    def _merge_segment_execution_result(seg_id: int, seg_r: dict) -> None:
        nonlocal tts_api_calls
        tts_results[seg_id] = seg_r.get("tts_result", {})
        code_results[seg_id] = seg_r.get("code_result", {})
        segment_results[seg_id] = seg_r

        seg_tu = seg_r.get("token_usage")
        if seg_tu:
            merge_token_usage(coding_tokens, seg_tu)
            merge_token_usage(pipeline_tokens, seg_tu)
        seg_verify_tu = seg_r.get("verify_token_usage")
        if seg_verify_tu:
            merge_token_usage(verification_tokens, seg_verify_tu)
            merge_token_usage(pipeline_tokens, seg_verify_tu)
        _merge_tool_calls(seg_r.get("tool_call_counts"))
        if seg_r.get("tts_api_call"):
            tts_api_calls += 1

    for seg_id, seg_r in segment_results.items():
        _merge_segment_execution_result(seg_id, seg_r)

    code_ok = sum(1 for r in code_results.values() if _has_valid_code(r))
    tts_ok = sum(1 for r in tts_results.values() if r.get("success"))

    # Mark completed stages
    if tts_ok == num_segments:
        _record_stage_done("tts", artifacts=[
            tts_results[seg["id"]].get("audio_path", "") for seg in segments
            if tts_results.get(seg["id"], {}).get("success")
        ])
    if code_ok == num_segments:
        _record_stage_done("code", artifacts=[])

    timings.append(("Parallel Pipeline", "ok" if code_ok > 0 else "failed", pipeline_elapsed))

    yield {
        "stage": "code",
        "status": f"Pipeline complete: {code_ok}/{num_segments} rendered, {tts_ok}/{num_segments} voiced",
        "code_results": code_results,
        "tts_results": tts_results,
    }

    # ── Step 3.0: Retry render-only / stitch-only failures ───────────
    render_retry_ids = [
        sid for sid, res in code_results.items()
        if res.get("code") and not res.get("video_path")
    ]
    if render_retry_ids:
        runtime_metrics["segment_repairs"] += len(render_retry_ids)
        yield {
            "stage": "render",
            "status": f"Retrying HD render for {len(render_retry_ids)} segment(s) using existing code...",
        }
        with ThreadPoolExecutor(max_workers=_segment_concurrency(len(render_retry_ids))) as retry_executor:
            retry_futures: dict[Any, dict] = {}
            for seg in sorted(
                [segment for segment in segments if segment["id"] in render_retry_ids],
                key=lambda s: (-_risk_rank(s.get("render_risk", "medium")), s.get("id", 0)),
            ):
                sid = seg["id"]
                retry_futures[retry_executor.submit(
                    _run_segment_pipeline,
                    seg,
                    "",
                    "",
                    code_results.get(sid, {}).get("code", ""),
                    None,
                    "render_only",
                )] = seg

            for fut, seg in _iter_completed_futures(retry_futures, status_queue):
                if fut is None:
                    yield seg
                    continue
                sid = seg["id"]
                try:
                    rerun_result = fut.result()
                except Exception as exc:
                    rerun_result = {
                        "segment_id": sid,
                        "tts_result": tts_results.get(sid, {}),
                        "code_result": code_results.get(sid, {}),
                        "stitch_path": segment_results.get(sid, {}).get("stitch_path"),
                        "stitch_error": str(exc),
                        "token_usage": None,
                        "tool_call_counts": None,
                        "tts_api_call": False,
                    }
                _merge_segment_execution_result(sid, rerun_result)

    stitch_retry_ids = [
        sid for sid, seg_r in segment_results.items()
        if seg_r.get("stitch_error")
        and code_results.get(sid, {}).get("video_path")
        and tts_results.get(sid, {}).get("success")
    ]
    if stitch_retry_ids:
        runtime_metrics["segment_repairs"] += len(stitch_retry_ids)
        yield {
            "stage": "stitch",
            "status": f"Retrying stitch for {len(stitch_retry_ids)} segment(s) using existing media...",
        }
        with ThreadPoolExecutor(max_workers=_segment_concurrency(len(stitch_retry_ids))) as retry_executor:
            retry_futures: dict[Any, dict] = {}
            for seg in sorted(
                [segment for segment in segments if segment["id"] in stitch_retry_ids],
                key=lambda s: (s.get("id", 0)),
            ):
                sid = seg["id"]
                retry_futures[retry_executor.submit(
                    _run_segment_pipeline,
                    seg,
                    "",
                    "",
                    code_results.get(sid, {}).get("code", ""),
                    code_results.get(sid, {}).get("video_path"),
                    "stitch_only",
                )] = seg

            for fut, seg in _iter_completed_futures(retry_futures, status_queue):
                if fut is None:
                    yield seg
                    continue
                sid = seg["id"]
                try:
                    rerun_result = fut.result()
                except Exception as exc:
                    rerun_result = {
                        "segment_id": sid,
                        "tts_result": tts_results.get(sid, {}),
                        "code_result": code_results.get(sid, {}),
                        "stitch_path": segment_results.get(sid, {}).get("stitch_path"),
                        "stitch_error": str(exc),
                        "token_usage": None,
                        "tool_call_counts": None,
                        "tts_api_call": False,
                    }
                _merge_segment_execution_result(sid, rerun_result)

    code_ok = sum(1 for r in code_results.values() if _has_valid_code(r))
    tts_ok = sum(1 for r in tts_results.values() if r.get("success"))

    # ── Step 3.1: Retry failed segments with few-shot ─────────────────

    failed_seg_ids = [sid for sid, r in code_results.items() if not _has_valid_code(r)]
    if failed_seg_ids and code_ok > 0:
        # Pick the shortest successful segment's code as a few-shot example
        successful_codes = {}
        for seg in segments:
            sid = seg["id"]
            r = code_results.get(sid, {})
            if _has_valid_code(r) and r.get("code"):
                successful_codes[sid] = r["code"]
        few_shot = min(successful_codes.values(), key=len) if successful_codes else ""

        yield {
            "stage": "code_retry",
            "status": f"Retrying {len(failed_seg_ids)} failed segment(s) with few-shot + escalation...",
        }

        failed_segs = [seg for seg in segments if seg["id"] in failed_seg_ids]
        # Escalate "medium" → "complex" (Sonnet → Opus) for failed segments
        for seg in failed_segs:
            if seg.get("complexity") == "medium":
                seg["complexity"] = "complex"

        retry_results: dict[int, dict] = {}
        retry_max_workers = _segment_concurrency(len(failed_segs))
        runtime_metrics["segment_repairs"] += len(failed_segs)
        runtime_metrics["full_regen_repairs"] += len(failed_segs)

        with ThreadPoolExecutor(max_workers=retry_max_workers) as retry_executor:
            retry_futures: dict[Any, dict] = {}
            for seg in sorted(failed_segs, key=lambda s: (-_risk_rank(s.get("render_risk", "medium")), s.get("id", 0))):
                retry_futures[retry_executor.submit(
                    _run_segment_pipeline, seg, few_shot
                )] = seg

            for fut, seg in _iter_completed_futures(retry_futures, status_queue):
                if fut is None:
                    yield seg
                    continue
                sid = seg["id"]
                try:
                    retry_r = fut.result()
                except Exception as exc:
                    retry_r = {
                        "segment_id": sid,
                        "tts_result": tts_results.get(sid, {}),
                        "code_result": {"success": False, "error": str(exc)},
                        "stitch_path": None,
                        "stitch_error": str(exc),
                        "token_usage": None,
                        "tool_call_counts": None,
                        "tts_api_call": False,
                    }

                retry_results[sid] = retry_r
                # Update aggregated results
                code_results[sid] = retry_r.get("code_result", {})
                segment_results[sid] = retry_r

                retry_tu = retry_r.get("token_usage")
                if retry_tu:
                    merge_token_usage(coding_tokens, retry_tu)
                    merge_token_usage(pipeline_tokens, retry_tu)
                retry_verify_tu = retry_r.get("verify_token_usage")
                if retry_verify_tu:
                    merge_token_usage(verification_tokens, retry_verify_tu)
                    merge_token_usage(pipeline_tokens, retry_verify_tu)
                _merge_tool_calls(retry_r.get("tool_call_counts"))

                has_code = _has_valid_code(retry_r["code_result"])
                if has_code:
                    code_ok += 1
                    yield {
                        "stage": "code_retry", "segment_id": sid,
                        "status": f"Retry Segment {sid}: recovered!",
                        "segment_phase": "done", "segment_final": True,
                    }
                else:
                    yield {
                        "stage": "code_retry", "segment_id": sid,
                        "status": f"Retry Segment {sid}: still failed",
                        "segment_phase": "failed", "segment_final": True,
                    }

            yield from _drain_status_queue(status_queue)

    # ── Step 3.2: Transition quality checks and targeted repair ──────
    final_code_map = {
        sid: res.get("code", "")
        for sid, res in code_results.items()
        if res.get("code")
    }
    if len(final_code_map) >= 2:
        yield {"stage": "verify", "status": "Checking cross-segment code transitions..."}
        transition_checks = verify_code_transitions(
            final_code_map,
            segment_specs={seg["id"]: seg for seg in segments},
            quality_mode=quality_settings["quality_mode"],
            token_counter=verification_tokens,
        )
        transition_repairs = [check for check in transition_checks if not check.smooth]

        for check in transition_checks:
            yield {
                "stage": "verify",
                "segment_id": check.segment_b_id,
                "status": (
                    f"Transition {check.segment_a_id}->{check.segment_b_id} passed"
                    if check.smooth
                    else f"Transition {check.segment_a_id}->{check.segment_b_id} warnings - {'; '.join(check.issues[:2])}"
                ),
                "segment_phase": "done" if check.smooth else "failed",
                "segment_final": True,
            }

        if quality_settings["allow_repair"]:
            for check in transition_repairs:
                target_seg = next((seg for seg in segments if seg["id"] == check.segment_b_id), None)
                if not target_seg:
                    continue
                feedback = _build_repair_feedback(transition_issues=check.issues)
                runtime_metrics["segment_repairs"] += 1
                yield {
                    "stage": "code_retry",
                    "segment_id": check.segment_b_id,
                    "status": f"Repairing Segment {check.segment_b_id} for transition continuity...",
                    "segment_phase": "running",
                    "segment_final": False,
                }
                repaired = _run_segment_pipeline(
                    target_seg,
                    repair_feedback=feedback,
                    existing_code=code_results.get(check.segment_b_id, {}).get("code", ""),
                    rerun_mode="patch",
                )
                segment_results[check.segment_b_id] = repaired
                code_results[check.segment_b_id] = repaired.get("code_result", {})
                tts_results[check.segment_b_id] = repaired.get("tts_result", {})
                repair_tu = repaired.get("token_usage")
                if repair_tu:
                    merge_token_usage(coding_tokens, repair_tu)
                    merge_token_usage(pipeline_tokens, repair_tu)
                repair_verify_tu = repaired.get("verify_token_usage")
                if repair_verify_tu:
                    merge_token_usage(verification_tokens, repair_verify_tu)
                    merge_token_usage(pipeline_tokens, repair_verify_tu)
                _merge_tool_calls(repaired.get("tool_call_counts"))
                yield {
                    "stage": "code_retry",
                    "segment_id": check.segment_b_id,
                    "status": f"Transition repair complete for Segment {check.segment_b_id}",
                    "segment_phase": "done" if _has_valid_code(repaired.get("code_result", {})) else "failed",
                    "segment_final": True,
                }

    code_ok = sum(1 for r in code_results.values() if _has_valid_code(r))
    tts_ok = sum(1 for r in tts_results.values() if r.get("success"))

    # ── Build ordered valid_paths for concat ──────────────────────────

    if skip_audio:
        valid_paths = [
            code_results[seg["id"]].get("video_path")
            for seg in segments
            if code_results.get(seg["id"], {}).get("video_path")
        ]
    else:
        # Reconstruct ordered stitch paths (retry results may have updated them)
        for seg in segments:
            seg_id = seg["id"]
            seg_r = segment_results.get(seg_id, {})
            stitch_path = seg_r.get("stitch_path")
            stitch_error = seg_r.get("stitch_error")
            if stitch_error:
                stitch_errors.append(stitch_error)
        valid_paths = [
            segment_results.get(seg["id"], {}).get("stitch_path")
            for seg in segments
            if segment_results.get(seg["id"], {}).get("stitch_path")
        ]
        if code_ok > 0 and not stitch_errors:
            _record_stage_done("stitch", artifacts=[])

    project_consistency = None
    segment_video_paths = {
        seg["id"]: segment_results.get(seg["id"], {}).get("stitch_path") or code_results.get(seg["id"], {}).get("video_path")
        for seg in segments
        if (segment_results.get(seg["id"], {}).get("stitch_path") or code_results.get(seg["id"], {}).get("video_path"))
    }
    run_project_consistency = _should_run_project_consistency_check(quality_settings["quality_mode"])
    if len(segment_video_paths) >= 2 and run_project_consistency:
        yield {"stage": "verify", "status": "Checking project-level visual consistency before concat..."}
        project_consistency = critique_project_consistency(segment_video_paths, token_counter=verification_tokens)
        if project_consistency is not None:
            yield {
                "stage": "verify",
                "status": (
                    "Project-level visual consistency passed"
                    if project_consistency.passed
                    else f"Project-level consistency warnings - {'; '.join(project_consistency.issues[:2])}"
                ),
            }
    elif len(segment_video_paths) >= 2:
        yield {
            "stage": "verify",
            "status": "Skipping project-level visual consistency check for this quality mode",
            "skipped": True,
        }

    # ── Build per-segment failure summary for error reporting ────────

    def _build_segment_failures() -> list[dict]:
        """Build a list of {id, title, stage, error} for each failed segment."""
        failures = []
        for seg in segments:
            sid = seg["id"]
            cr = code_results.get(sid, {})
            sr = segment_results.get(sid, {})
            if not _has_valid_code(cr) or sr.get("stitch_error"):
                stage = "stitch" if _has_valid_code(cr) else "code"
                err = sr.get("stitch_error") or cr.get("error") or "Unknown error"
                failures.append({
                    "id": sid,
                    "title": seg.get("title", f"Segment {sid}"),
                    "stage": stage,
                    "error": str(err)[:200],
                })
        return failures

    def _segment_quality_summary() -> dict[int, dict[str, Any]]:
        return {
            sid: {
                "repair_attempted": segment_results.get(sid, {}).get("repair_attempted", False),
                "final_accepted_critique_score": segment_results.get(sid, {}).get("final_accepted_critique_score"),
                "verification_tier": segment_results.get(sid, {}).get("verification_tier"),
                "critique_skipped": segment_results.get(sid, {}).get("critique_skipped", False),
                "quality_risk": segment_results.get(sid, {}).get("quality_risk"),
                "stitch_mode": segment_results.get(sid, {}).get("stitch_mode"),
                "timing_normalization": segment_results.get(sid, {}).get("timing_normalization"),
            }
            for sid in segment_results
        }

    # ── Step 5: Concatenate all segments ──────────────────────────────

    if not valid_paths:
        runtime_metrics["planner_api_calls"] = planning_tokens["api_calls"]
        total_elapsed_seconds = time.perf_counter() - overall_start
        token_summary = _build_token_summary(pipeline_tokens, planning_tokens, coding_tokens, verification_tokens, tts_api_calls)
        yield {
            "stage": "done",
            "status": "No segments produced a video.",
            "error": "All segments failed.",
            "final": True,
            "project_dir": project_dir,
            "num_segments": num_segments,
            "failed_segments": _build_segment_failures(),
            "timings": timings,
            "tool_call_counts": dict(sorted(tool_call_counts.items())),
            "total_tool_calls": sum(tool_call_counts.values()),
            "token_summary": token_summary,
            "runtime_metrics": runtime_metrics,
            "total_elapsed_seconds": total_elapsed_seconds,
            "project_consistency": project_consistency,
            "segment_quality": _segment_quality_summary(),
        }
        _save_pipeline_summary(
            timings,
            project_dir,
            concept,
            tool_call_counts=tool_call_counts,
            token_summary=token_summary,
            runtime_metrics=runtime_metrics,
            total_elapsed_seconds=total_elapsed_seconds,
        )
        return

    final_output = os.path.join(project_dir, f"{slug}.mp4")

    # Check if concat is already done from a previous run
    if resumed and state and is_stage_done(state, "concat") and os.path.isfile(final_output):
        timings.append(("Concat", "skipped", 0.0))
        _record_project_complete()
        runtime_metrics["planner_api_calls"] = planning_tokens["api_calls"]
        total_elapsed_seconds = time.perf_counter() - overall_start
        token_summary = _build_token_summary(pipeline_tokens, planning_tokens, coding_tokens, verification_tokens, tts_api_calls)
        _save_pipeline_summary(
            timings,
            project_dir,
            concept,
            tool_call_counts=tool_call_counts,
            token_summary=token_summary,
            runtime_metrics=runtime_metrics,
            total_elapsed_seconds=total_elapsed_seconds,
        )
        yield {
            "stage": "concat",
            "status": "Skipping (already completed) — final video exists",
            "skipped": True,
        }
        yield {
            "stage": "done",
            "status": "Pipeline complete! (resumed from cache)",
            "final": True,
            "video_path": final_output,
            "project_dir": project_dir,
            "num_segments": num_segments,
            "stitch_errors": stitch_errors,
            "timings": timings,
            "tool_call_counts": dict(sorted(tool_call_counts.items())),
            "total_tool_calls": sum(tool_call_counts.values()),
            "token_summary": token_summary,
            "runtime_metrics": runtime_metrics,
            "total_elapsed_seconds": total_elapsed_seconds,
            "project_consistency": project_consistency,
            "segment_quality": _segment_quality_summary(),
        }
        return

    yield {"stage": "concat", "status": f"Concatenating {len(valid_paths)} segments into final video..."}
    concat_start = time.perf_counter()

    concat_result = None
    for update in concatenate_segments(valid_paths, final_output):
        if "status" in update:
            yield {"stage": "concat", "status": update["status"]}
        if update.get("final"):
            concat_result = update

    concat_elapsed = time.perf_counter() - concat_start

    if concat_result and concat_result.get("success"):
        timings.append(("Concat", "ok", concat_elapsed))
        _record_stage_done("concat", artifacts=[final_output])
        _record_project_complete()

        # ── Step 5.5: Generate subtitles ──────────────────────────────
        srt_path = None
        if not skip_audio and tts_results:
            try:
                yield {"stage": "subtitles", "status": "Generating subtitles..."}
                srt_content = generate_combined_srt(segments, tts_results)
                if srt_content.strip():
                    srt_path = os.path.join(project_dir, f"{slug}.srt")
                    write_srt(srt_content, srt_path)

                    # Mux subtitles into the final video
                    subbed_output = final_output.replace(".mp4", "_subbed.mp4")
                    mux_result = None
                    for mux_update in mux_subtitles(final_output, srt_path, subbed_output):
                        if "status" in mux_update:
                            yield {"stage": "subtitles", "status": mux_update["status"]}
                        if mux_update.get("final"):
                            mux_result = mux_update

                    if mux_result and mux_result.get("success"):
                        # Replace the original with the subtitled version
                        os.replace(subbed_output, final_output)
                        yield {"stage": "subtitles", "status": "Subtitles embedded in video"}
                    else:
                        yield {"stage": "subtitles", "status": "Subtitle muxing failed — SRT file still available"}
                else:
                    yield {"stage": "subtitles", "status": "No subtitle content generated (missing transcripts)"}
            except Exception as exc:
                yield {"stage": "subtitles", "status": f"Subtitle generation failed: {exc}"}

        runtime_metrics["planner_api_calls"] = planning_tokens["api_calls"]
        total_elapsed_seconds = time.perf_counter() - overall_start
        token_summary = _build_token_summary(pipeline_tokens, planning_tokens, coding_tokens, verification_tokens, tts_api_calls)
        _save_pipeline_summary(
            timings,
            project_dir,
            concept,
            tool_call_counts=tool_call_counts,
            token_summary=token_summary,
            runtime_metrics=runtime_metrics,
            total_elapsed_seconds=total_elapsed_seconds,
        )
        yield {
            "stage": "done",
            "status": "Pipeline complete!",
            "final": True,
            "video_path": final_output,
            "srt_path": srt_path,
            "project_dir": project_dir,
            "num_segments": num_segments,
            "stitch_errors": stitch_errors,
            "timings": timings,
            "tool_call_counts": dict(sorted(tool_call_counts.items())),
            "total_tool_calls": sum(tool_call_counts.values()),
            "token_summary": token_summary,
            "runtime_metrics": runtime_metrics,
            "total_elapsed_seconds": total_elapsed_seconds,
            "project_consistency": project_consistency,
            "segment_quality": _segment_quality_summary(),
        }
    else:
        err = concat_result.get("error", "unknown") if concat_result else "unknown"
        timings.append(("Concat", "failed", concat_elapsed))
        runtime_metrics["planner_api_calls"] = planning_tokens["api_calls"]
        total_elapsed_seconds = time.perf_counter() - overall_start
        token_summary = _build_token_summary(pipeline_tokens, planning_tokens, coding_tokens, verification_tokens, tts_api_calls)
        _save_pipeline_summary(
            timings,
            project_dir,
            concept,
            tool_call_counts=tool_call_counts,
            token_summary=token_summary,
            runtime_metrics=runtime_metrics,
            total_elapsed_seconds=total_elapsed_seconds,
        )
        # If concat fails but we have segments, return the first one
        yield {
            "stage": "done",
            "status": f"Concatenation failed: {err}",
            "final": True,
            "video_path": valid_paths[0] if valid_paths else None,
            "error": err,
            "project_dir": project_dir,
            "num_segments": num_segments,
            "failed_segments": _build_segment_failures(),
            "timings": timings,
            "tool_call_counts": dict(sorted(tool_call_counts.items())),
            "total_tool_calls": sum(tool_call_counts.values()),
            "token_summary": token_summary,
            "runtime_metrics": runtime_metrics,
            "total_elapsed_seconds": total_elapsed_seconds,
            "project_consistency": project_consistency,
            "segment_quality": _segment_quality_summary(),
        }
