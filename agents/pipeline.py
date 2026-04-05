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
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Empty, Queue
from typing import Any, Iterator

from agents.coder import run_coder_agent
from agents.config import CLAUDE_OPUS, CLAUDE_SONNET, estimate_cost, merge_token_usage, new_token_counter
from agents.planner import plan_segmented_storyboard_lite
from agents.planner_math2manim import run_math2manim_planner
from utils.media_assembler import concatenate_segments, mux_subtitles, stitch_video_and_audio
from utils.subtitle_generator import generate_combined_srt, write_srt
from utils.parallel_renderer import RenderJob, render_parallel
from utils.project_state import (
    create_project,
    is_segment_stage_done,
    is_stage_done,
    load_project,
    mark_project_complete,
    mark_segment_stage,
    mark_stage_done,
)
from utils.tts_engine import generate_voiceover_async


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


def _save_pipeline_summary(
    timings: list[tuple[str, str, float]],
    project_dir: str,
    concept: str = "",
    tool_call_counts: dict[str, int] | None = None,
    token_summary: dict | None = None,
) -> str:
    """Write a plain-text pipeline summary to ``project_dir/pipeline_summary.txt``."""
    import time as _time

    total = sum(e for _, _, e in timings)
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

    if token_summary:
        lines.append("Token Usage & Cost")
        lines.append("=" * 50)
        lines.append(f"Total input tokens  : {token_summary.get('total_input_tokens', 0):,}")
        lines.append(f"Total output tokens : {token_summary.get('total_output_tokens', 0):,}")
        lines.append(f"Total API calls     : {token_summary.get('total_api_calls', 0)}")
        lines.append(f"TTS API calls       : {token_summary.get('tts_api_calls', 0)}")
        lines.append(f"Estimated cost      : ${token_summary.get('estimated_cost_usd', 0):.4f}")
        lines.append("")
        breakdown = token_summary.get("breakdown", {})
        for stage_name, stage_data in breakdown.items():
            lines.append(f"  {stage_name.capitalize()}:")
            lines.append(f"    Input tokens  : {stage_data.get('input_tokens', 0):,}")
            lines.append(f"    Output tokens : {stage_data.get('output_tokens', 0):,}")
            lines.append(f"    API calls     : {stage_data.get('api_calls', 0)}")
            lines.append(f"    Cost          : ${stage_data.get('cost_usd', 0):.4f}")
            lines.append("")

    os.makedirs(project_dir, exist_ok=True)
    summary_path = os.path.join(project_dir, "pipeline_summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return summary_path


# ── Token summary builder ────────────────────────────────────────────

def _build_token_summary(pipeline_tokens, planning_tokens, coding_tokens, tts_api_calls=0):
    """Build a summary dict of token usage and estimated cost across stages."""
    total_in = pipeline_tokens["input_tokens"]
    total_out = pipeline_tokens["output_tokens"]
    total_calls = pipeline_tokens["api_calls"]
    planning_cost = estimate_cost(
        planning_tokens["input_tokens"], planning_tokens["output_tokens"], model=CLAUDE_SONNET,
        cache_creation_tokens=planning_tokens.get("cache_creation_input_tokens", 0),
        cache_read_tokens=planning_tokens.get("cache_read_input_tokens", 0),
    )
    coding_cost = estimate_cost(
        coding_tokens["input_tokens"], coding_tokens["output_tokens"], model=CLAUDE_OPUS,
        cache_creation_tokens=coding_tokens.get("cache_creation_input_tokens", 0),
        cache_read_tokens=coding_tokens.get("cache_read_input_tokens", 0),
    )
    total_cost = planning_cost + coding_cost
    total_cache_created = pipeline_tokens.get("cache_creation_input_tokens", 0)
    total_cache_read = pipeline_tokens.get("cache_read_input_tokens", 0)
    return {
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "total_api_calls": total_calls,
        "tts_api_calls": tts_api_calls,
        "cache_creation_input_tokens": total_cache_created,
        "cache_read_input_tokens": total_cache_read,
        "estimated_cost_usd": round(total_cost, 4),
        "breakdown": {
            "planning": {
                "input_tokens": planning_tokens["input_tokens"],
                "output_tokens": planning_tokens["output_tokens"],
                "api_calls": planning_tokens["api_calls"],
                "cost_usd": round(planning_cost, 4),
            },
            "coding": {
                "input_tokens": coding_tokens["input_tokens"],
                "output_tokens": coding_tokens["output_tokens"],
                "api_calls": coding_tokens["api_calls"],
                "cache_creation_input_tokens": coding_tokens.get("cache_creation_input_tokens", 0),
                "cache_read_input_tokens": coding_tokens.get("cache_read_input_tokens", 0),
                "cost_usd": round(coding_cost, 4),
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

    # ── Token tracking accumulators ──────────────────────────────────
    pipeline_tokens = new_token_counter()
    planning_tokens = new_token_counter()
    coding_tokens = new_token_counter()
    tts_api_calls = 0

    # ── Resumability: look for an existing incomplete project ─────────
    resumed = False
    project_dir: str | None = None
    state: dict | None = None

    if not force_restart:
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

    # ── Step 1: Planning ──────────────────────────────────────────────

    storyboard = None
    timings: list[tuple[str, str, float]] = []

    if resumed and state and is_stage_done(state, "plan"):
        # Try to load cached storyboard from disk
        cached_sb = _load_storyboard(project_dir)
        if cached_sb and "segments" in cached_sb:
            storyboard = cached_sb
            segments = storyboard["segments"]
            num_segments = len(segments)
            timings.append(("Plan", "skipped", 0.0))
            yield {
                "stage": "plan",
                "status": f"Skipping (already completed) — {num_segments} segments",
                "skipped": True,
                "storyboard": storyboard,
                "num_segments": num_segments,
            }
        else:
            # Plan was marked done but storyboard file is missing/corrupt;
            # must re-plan.
            resumed = False
            state = None

    if storyboard is None:
        yield {"stage": "plan", "status": "Starting segmented storyboard planning..."}
        plan_start = time.perf_counter()

        planner_func = plan_segmented_storyboard_lite if is_lite else run_math2manim_planner
        planner_kwargs: dict = dict(
            max_retries=max_retries,
            previous_storyboard=previous_storyboard,
            feedback=feedback,
        )
        if questionnaire_answers:
            planner_kwargs["questionnaire_answers"] = questionnaire_answers
        for update in planner_func(concept, **planner_kwargs):
            if "status" in update:
                yield {"stage": "plan", "status": update["status"]}
            if update.get("final"):
                if "error" in update:
                    yield {"stage": "plan", "status": update["error"], "error": update["error"], "final": True}
                    return
                storyboard = update["storyboard"]
                # Extract planner token usage
                try:
                    planner_tu = update.get("token_usage")
                    if planner_tu:
                        merge_token_usage(planning_tokens, planner_tu)
                        merge_token_usage(pipeline_tokens, planner_tu)
                except Exception:
                    pass  # Never let token tracking crash the pipeline

        if not storyboard:
            yield {"stage": "plan", "status": "No storyboard generated.", "error": "Empty planner output.", "final": True}
            return

        segments = storyboard["segments"]
        num_segments = len(segments)
        plan_elapsed = time.perf_counter() - plan_start
        timings.append(("Plan", "ok", plan_elapsed))
        yield {
            "stage": "plan",
            "status": f"Storyboard planned: {num_segments} segments",
            "storyboard": storyboard,
            "num_segments": num_segments,
        }

        # Create project directory (only for fresh runs)
        if project_dir is None:
            project_dir = os.path.join(output_base, f"{slug}_{id(storyboard) % 10000:04d}")
            state = create_project(project_dir, concept, slug, total_segments=num_segments)

        mark_stage_done(project_dir, "plan", artifacts=[])
        _save_storyboard(project_dir, storyboard)
        # Reload state after marking stage done
        state = load_project(project_dir)

    # ── Step 2: Complexity downgrade heuristic ────────────────────────
    # Moved before the parallel block — only reads segment data.

    _3D_KEYWORDS = {"threedscene", "3d", "surface", "camera_rotation", "set_camera_orientation"}
    _UPDATER_KEYWORDS = {"always_redraw", "valuetracker", "updater", "add_updater"}

    for seg in segments:
        if seg.get("complexity") != "complex":
            continue
        vis = (seg.get("visual_instructions") or "").lower()
        eqs = seg.get("equations_latex", [])
        anims = seg.get("animations", [])
        has_3d = any(kw in vis for kw in _3D_KEYWORDS)
        has_updaters = any(kw in vis for kw in _UPDATER_KEYWORDS)
        if not has_3d and not has_updaters and len(eqs) <= 2 and len(anims) <= 5:
            seg["complexity"] = "medium"

    # ── Step 3: Pipelined-parallel per-segment processing ─────────────
    #
    # Each segment runs through TTS → Code → HD Render → Stitch inside
    # its own thread.  All segments execute concurrently.  This replaces
    # the old sequential-stage approach where ALL TTS had to finish
    # before ANY code generation could start, etc.

    tts_results: dict[int, dict] = {}
    code_results: dict[int, dict] = {}
    tool_call_counts: dict[str, int] = {}
    stitch_errors: list[str] = []

    theme_name = storyboard.get("theme_name", "")
    color_palette = storyboard.get("color_palette", {})
    status_queue: Queue[dict] = Queue()
    _state_lock = threading.Lock()

    def _merge_tool_calls(counts: dict[str, int] | None) -> None:
        if not counts:
            return
        for tool_name, count in counts.items():
            if not isinstance(count, int):
                continue
            tool_call_counts[tool_name] = tool_call_counts.get(tool_name, 0) + count

    # ── Per-segment pipeline worker ──────────────────────────────────

    def _run_segment_pipeline(seg: dict, few_shot_example: str = "") -> dict:
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
            "stitch_path": None,
            "stitch_error": None,
            "token_usage": None,
            "tool_call_counts": None,
            "tts_api_call": False,
        }

        # ── Phase 1: TTS ──────────────────────────────────────────
        if not skip_audio:
            audio_path = os.path.join(project_dir, f"segment_{seg_id}_audio.wav")

            # Check per-segment TTS cache
            cached_tts = False
            if resumed and state and is_segment_stage_done(state, seg_id, "tts"):
                if os.path.isfile(audio_path):
                    result["tts_result"] = {"success": True, "audio_path": audio_path, "duration": 0.0}
                    cached_tts = True
                else:
                    seg_info = state.get("segments", {}).get(str(seg_id), {}).get("tts", {})
                    found = next((a for a in seg_info.get("artifacts", []) if a and os.path.isfile(a)), None)
                    if found:
                        result["tts_result"] = {"success": True, "audio_path": found, "duration": 0.0}
                        cached_tts = True

            if cached_tts:
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
                        result["tts_api_call"] = True
                        with _state_lock:
                            mark_segment_stage(project_dir, seg_id, "tts", done=True,
                                               artifacts=[tts_r.get("audio_path", "")])
                        status_queue.put({
                            "stage": "tts", "segment_id": seg_id,
                            "status": f"Segment {seg_id}: TTS done",
                            "segment_phase": "done", "segment_final": True,
                        })
                    else:
                        with _state_lock:
                            mark_segment_stage(project_dir, seg_id, "tts", done=False,
                                               error=tts_r.get("error", ""))
                        status_queue.put({
                            "stage": "tts", "segment_id": seg_id,
                            "status": f"Segment {seg_id}: TTS failed",
                            "segment_phase": "failed", "segment_final": True,
                        })
                except Exception as e:
                    result["tts_result"] = {"success": False, "error": str(e), "audio_path": None, "duration": 0}
                    with _state_lock:
                        mark_segment_stage(project_dir, seg_id, "tts", done=False, error=str(e))
                    status_queue.put({
                        "stage": "tts", "segment_id": seg_id,
                        "status": f"Segment {seg_id}: TTS error",
                        "segment_phase": "failed", "segment_final": True,
                    })
                finally:
                    loop.close()

        # ── Phase 2: Code generation ──────────────────────────────
        code_cached = False
        if resumed and state and is_segment_stage_done(state, seg_id, "code"):
            seg_artifacts = state.get("segments", {}).get(str(seg_id), {}).get("code", {}).get("artifacts", [])
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
                result["code_result"] = {
                    "success": True, "video_path": video_found,
                    "code_validated": True, "code": "",
                }
                code_cached = True
                status_queue.put({
                    "stage": "code", "segment_id": seg_id,
                    "status": f"Segment {seg_id}: code cached",
                    "segment_phase": "done", "segment_final": True,
                    "skipped": True,
                })

        if not code_cached:
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
            ):
                last_update = update
                status_queue.put({
                    "stage": "code", "segment_id": seg_id,
                    "status": update.get("status", ""),
                    "segment_phase": update.get("phase", "running"),
                    "segment_final": bool(update.get("final")),
                })

            result["code_result"] = last_update
            result["token_usage"] = last_update.get("token_usage")
            result["tool_call_counts"] = last_update.get("tool_call_counts")

            has_code = _has_valid_code(last_update)
            with _state_lock:
                if has_code:
                    mark_segment_stage(project_dir, seg_id, "code", done=True,
                                       artifacts=[last_update.get("video_path", "")])
                    if last_update.get("video_path"):
                        mark_segment_stage(project_dir, seg_id, "render", done=True,
                                           artifacts=[last_update.get("video_path", "")])
                else:
                    mark_segment_stage(project_dir, seg_id, "code", done=False,
                                       error=last_update.get("error", "Code generation failed"))

        # ── Phase 3: HD Render ────────────────────────────────────
        code_r = result["code_result"]
        if _has_valid_code(code_r) and code_r.get("code"):
            hd_cached = False
            if resumed and state and is_segment_stage_done(state, seg_id, "hd_render"):
                hd_info = state.get("segments", {}).get(str(seg_id), {}).get("hd_render", {})
                hd_found = next((a for a in hd_info.get("artifacts", []) if a and os.path.isfile(a)), None)
                if hd_found:
                    code_r["video_path"] = hd_found
                    hd_cached = True
                    status_queue.put({
                        "stage": "render", "segment_id": seg_id,
                        "status": f"Segment {seg_id}: HD render cached",
                        "segment_phase": "done", "segment_final": True,
                        "skipped": True,
                    })

            if not hd_cached:
                status_queue.put({
                    "stage": "render", "segment_id": seg_id,
                    "status": f"Segment {seg_id}: HD rendering...",
                    "segment_phase": "running", "segment_final": False,
                })
                hd_job = RenderJob(
                    segment_id=seg_id,
                    code=code_r["code"],
                    quality_flag="-qh",
                    timeout_seconds=render_timeout_seconds or 300,
                    output_dir=seg_output_dir,
                )
                hd_results = render_parallel([hd_job])
                hd_result = hd_results[0] if hd_results else None
                if hd_result and hd_result.success and hd_result.video_path:
                    code_r["video_path"] = hd_result.video_path
                    with _state_lock:
                        mark_segment_stage(project_dir, seg_id, "hd_render", done=True,
                                           artifacts=[hd_result.video_path])
                    status_queue.put({
                        "stage": "render", "segment_id": seg_id,
                        "status": f"Segment {seg_id}: HD render done",
                        "segment_phase": "done", "segment_final": True,
                    })
                else:
                    err = hd_result.error if hd_result else "Unknown"
                    with _state_lock:
                        mark_segment_stage(project_dir, seg_id, "hd_render", done=False,
                                           error=err or "Unknown")
                    status_queue.put({
                        "stage": "render", "segment_id": seg_id,
                        "status": f"Segment {seg_id}: HD render failed, using preview",
                        "segment_phase": "failed", "segment_final": True,
                    })

        # ── Phase 4: Stitch ───────────────────────────────────────
        if not skip_audio:
            stitch_cached = False
            if resumed and state and is_segment_stage_done(state, seg_id, "stitch"):
                stitched_path = os.path.join(project_dir, f"segment_{seg_id}_stitched.mp4")
                if os.path.isfile(stitched_path):
                    result["stitch_path"] = stitched_path
                    stitch_cached = True
                else:
                    seg_stitch_info = state.get("segments", {}).get(str(seg_id), {}).get("stitch", {})
                    found_art = next((a for a in seg_stitch_info.get("artifacts", [])
                                      if a and os.path.isfile(a)), None)
                    if found_art:
                        result["stitch_path"] = found_art
                        stitch_cached = True

            if stitch_cached:
                status_queue.put({
                    "stage": "stitch", "segment_id": seg_id,
                    "status": f"Segment {seg_id}: stitch cached",
                    "playable_segment": result["stitch_path"],
                    "segment_phase": "done", "segment_final": True,
                    "skipped": True,
                })
            else:
                video_path = code_r.get("video_path")
                audio_path = result["tts_result"].get("audio_path")
                tts_success = result["tts_result"].get("success", False)

                if not video_path:
                    result["stitch_error"] = f"Segment {seg_id}: no video to stitch"
                elif not audio_path or not tts_success:
                    # No audio — use raw video
                    result["stitch_path"] = video_path
                    with _state_lock:
                        mark_segment_stage(project_dir, seg_id, "stitch", done=True,
                                           artifacts=[video_path])
                else:
                    stitched_output = os.path.join(project_dir, f"segment_{seg_id}_stitched.mp4")
                    stitch_r = None
                    for update in stitch_video_and_audio(video_path, audio_path, stitched_output):
                        if update.get("final"):
                            stitch_r = update

                    if stitch_r and stitch_r.get("success"):
                        result["stitch_path"] = stitch_r["output_path"]
                        with _state_lock:
                            mark_segment_stage(project_dir, seg_id, "stitch", done=True,
                                               artifacts=[stitch_r["output_path"]])
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
                            mark_segment_stage(project_dir, seg_id, "stitch", done=False, error=err)
        else:
            # skip_audio: use video directly
            result["stitch_path"] = code_r.get("video_path")

        return result

    # ── Launch all segments concurrently ──────────────────────────────

    yield {
        "stage": "pipeline",
        "status": f"Processing {num_segments} segments in parallel (TTS \u2192 Code \u2192 Render \u2192 Stitch)...",
    }

    pipeline_start = time.perf_counter()
    segment_results: dict[int, dict] = {}
    max_workers = max(1, min(5, num_segments))
    segments_done = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures_map: dict[Any, dict] = {}
        for seg in segments:
            futures_map[executor.submit(_run_segment_pipeline, seg)] = seg

        for fut in as_completed(futures_map):
            yield from _drain_status_queue(status_queue)

            seg = futures_map[fut]
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
                    f"Segment {seg_id}: complete ({segments_done}/{num_segments})"
                    if has_code
                    else f"Segment {seg_id}: failed ({segments_done}/{num_segments})"
                ),
                "segment_phase": "done" if has_code else "failed",
                "segment_final": True,
            }

        yield from _drain_status_queue(status_queue)

    pipeline_elapsed = time.perf_counter() - pipeline_start

    # ── Aggregate results from all workers ────────────────────────────

    for seg_id, seg_r in segment_results.items():
        tts_results[seg_id] = seg_r.get("tts_result", {})
        code_results[seg_id] = seg_r.get("code_result", {})

        seg_tu = seg_r.get("token_usage")
        if seg_tu:
            merge_token_usage(coding_tokens, seg_tu)
            merge_token_usage(pipeline_tokens, seg_tu)
        _merge_tool_calls(seg_r.get("tool_call_counts"))
        if seg_r.get("tts_api_call"):
            tts_api_calls += 1

    code_ok = sum(1 for r in code_results.values() if _has_valid_code(r))
    tts_ok = sum(1 for r in tts_results.values() if r.get("success"))

    # Mark completed stages
    if tts_ok == num_segments:
        mark_stage_done(project_dir, "tts", artifacts=[
            tts_results[seg["id"]].get("audio_path", "") for seg in segments
            if tts_results.get(seg["id"], {}).get("success")
        ])
    if code_ok == num_segments:
        mark_stage_done(project_dir, "code", artifacts=[])
    if code_ok > 0 and not stitch_errors:
        mark_stage_done(project_dir, "stitch", artifacts=[])
    state = load_project(project_dir)

    timings.append(("Parallel Pipeline", "ok" if code_ok > 0 else "failed", pipeline_elapsed))

    yield {
        "stage": "code",
        "status": f"Pipeline complete: {code_ok}/{num_segments} rendered, {tts_ok}/{num_segments} voiced",
        "code_results": code_results,
        "tts_results": tts_results,
    }

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
        retry_max_workers = max(1, min(5, len(failed_segs)))

        with ThreadPoolExecutor(max_workers=retry_max_workers) as retry_executor:
            retry_futures: dict[Any, dict] = {}
            for seg in failed_segs:
                retry_futures[retry_executor.submit(
                    _run_segment_pipeline, seg, few_shot
                )] = seg

            for fut in as_completed(retry_futures):
                yield from _drain_status_queue(status_queue)
                seg = retry_futures[fut]
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

    # ── Step 5: Concatenate all segments ──────────────────────────────

    if not valid_paths:
        token_summary = _build_token_summary(pipeline_tokens, planning_tokens, coding_tokens, tts_api_calls)
        yield {
            "stage": "done",
            "status": "No segments produced a video.",
            "error": "All segments failed.",
            "final": True,
            "project_dir": project_dir,
            "timings": timings,
            "tool_call_counts": dict(sorted(tool_call_counts.items())),
            "total_tool_calls": sum(tool_call_counts.values()),
            "token_summary": token_summary,
        }
        _save_pipeline_summary(timings, project_dir, concept, tool_call_counts=tool_call_counts, token_summary=token_summary)
        return

    final_output = os.path.join(project_dir, f"{slug}.mp4")

    # Check if concat is already done from a previous run
    if resumed and state and is_stage_done(state, "concat") and os.path.isfile(final_output):
        timings.append(("Concat", "skipped", 0.0))
        mark_project_complete(project_dir)
        token_summary = _build_token_summary(pipeline_tokens, planning_tokens, coding_tokens, tts_api_calls)
        _save_pipeline_summary(timings, project_dir, concept, tool_call_counts=tool_call_counts, token_summary=token_summary)
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
        mark_stage_done(project_dir, "concat", artifacts=[final_output])
        mark_project_complete(project_dir)

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

        token_summary = _build_token_summary(pipeline_tokens, planning_tokens, coding_tokens, tts_api_calls)
        _save_pipeline_summary(timings, project_dir, concept, tool_call_counts=tool_call_counts, token_summary=token_summary)
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
        }
    else:
        err = concat_result.get("error", "unknown") if concat_result else "unknown"
        timings.append(("Concat", "failed", concat_elapsed))
        token_summary = _build_token_summary(pipeline_tokens, planning_tokens, coding_tokens, tts_api_calls)
        _save_pipeline_summary(timings, project_dir, concept, tool_call_counts=tool_call_counts, token_summary=token_summary)
        # If concat fails but we have segments, return the first one
        yield {
            "stage": "done",
            "status": f"Concatenation failed: {err}",
            "final": True,
            "video_path": valid_paths[0] if valid_paths else None,
            "error": err,
            "project_dir": project_dir,
            "num_segments": num_segments,
            "timings": timings,
            "tool_call_counts": dict(sorted(tool_call_counts.items())),
            "total_tool_calls": sum(tool_call_counts.values()),
            "token_summary": token_summary,
        }
