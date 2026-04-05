"""
Segmented video pipeline orchestrator.

Coordinates the full parallel pipeline:
  1. Planner  → segmented storyboard
  2. TTS      → per-segment voiceover   (async, parallel)
  3. Coder    → per-segment Manim code  (async, parallel)
  4. Renderer → per-segment Manim video (multiprocessing, parallel)
  5. Stitcher → per-segment audio+video (sequential, fast)
  6. Concat   → final output video      (ffmpeg concat)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Empty, Queue
from typing import Any, Iterator

from agents.planner import plan_segmented_storyboard, plan_segmented_storyboard_lite
from agents.planner_math2manim import run_math2manim_planner
from agents.coder import run_coder_agent
from utils.tts_engine import generate_voiceover_async
from utils.media_assembler import stitch_video_and_audio, concatenate_segments
from utils.parallel_renderer import RenderJob, render_two_pass, render_parallel
from utils.project_state import (
    create_project,
    load_project,
    save_project,
    mark_stage_done,
    mark_segment_stage,
    mark_project_complete,
    is_stage_done,
    is_segment_stage_done,
)


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
    while True:
        try:
            partial = q.get_nowait()
        except Empty:
            break
        seg_id = partial.get("segment_id")
        seg_status = partial.get("status")
        if seg_id and seg_status:
            yield {
                "stage": "code",
                "segment_id": seg_id,
                "segment_status": seg_status,
                "status": f"Segment {seg_id}: {seg_status}",
                "segment_phase": partial.get("phase", "running"),
                "segment_final": bool(partial.get("final")),
            }


def _save_pipeline_summary(
    timings: list[tuple[str, str, float]],
    project_dir: str,
    concept: str = "",
    tool_call_counts: dict[str, int] | None = None,
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
        tag = "OK" if status == "ok" else "ERR"
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

    os.makedirs(project_dir, exist_ok=True)
    summary_path = os.path.join(project_dir, "pipeline_summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return summary_path


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

    # ── Step 2: Parallel TTS ──────────────────────────────────────────

    tts_results: dict[int, dict] = {}
    tts_all_cached = False

    if not skip_audio:
        # Check if TTS is fully cached from a previous run
        if resumed and state and is_stage_done(state, "tts"):
            # Verify that all audio files actually exist on disk
            all_audio_present = True
            for seg in segments:
                seg_id = seg["id"]
                audio_path = os.path.join(project_dir, f"segment_{seg_id}_audio.wav")
                if os.path.isfile(audio_path):
                    tts_results[seg_id] = {"success": True, "audio_path": audio_path, "duration": 0.0}
                elif is_segment_stage_done(state, seg_id, "tts"):
                    # Marked done but file missing — check artifacts in state
                    seg_info = state.get("segments", {}).get(str(seg_id), {}).get("tts", {})
                    artifacts = seg_info.get("artifacts", [])
                    found = any(os.path.isfile(a) for a in artifacts if a)
                    if found:
                        actual_path = next(a for a in artifacts if a and os.path.isfile(a))
                        tts_results[seg_id] = {"success": True, "audio_path": actual_path, "duration": 0.0}
                    else:
                        all_audio_present = False
                        break
                else:
                    all_audio_present = False
                    break

            if all_audio_present:
                tts_all_cached = True
                tts_ok = len(tts_results)
                timings.append(("Voiceover", "skipped", 0.0))
                yield {
                    "stage": "tts",
                    "status": f"Skipping (already completed) — {tts_ok}/{num_segments} audio files cached",
                    "skipped": True,
                    "tts_results": tts_results,
                }

        if not tts_all_cached:
            # Determine which segments need TTS (skip individually completed ones)
            segments_needing_tts = []
            for seg in segments:
                seg_id = seg["id"]
                audio_path = os.path.join(project_dir, f"segment_{seg_id}_audio.wav")
                if resumed and state and is_segment_stage_done(state, seg_id, "tts") and os.path.isfile(audio_path):
                    tts_results[seg_id] = {"success": True, "audio_path": audio_path, "duration": 0.0}
                else:
                    segments_needing_tts.append(seg)

            cached_count = len(tts_results)
            remaining = len(segments_needing_tts)
            if cached_count > 0:
                yield {"stage": "tts", "status": f"Generating voiceovers: {cached_count} cached, {remaining} remaining..."}
            else:
                yield {"stage": "tts", "status": f"Generating voiceovers for {num_segments} segments in parallel..."}
            tts_start = time.perf_counter()

            if segments_needing_tts:
                async def _run_all_tts():
                    tasks = []
                    for seg in segments_needing_tts:
                        seg_id = seg["id"]
                        audio_path = os.path.join(project_dir, f"segment_{seg_id}_audio.wav")
                        coro = generate_voiceover_async(seg["audio_script"], audio_path)
                        if tts_timeout_seconds > 0:
                            coro = asyncio.wait_for(coro, timeout=tts_timeout_seconds)
                        tasks.append(coro)
                    return await asyncio.gather(*tasks, return_exceptions=True)

                # C10: asyncio.run() crashes if an event loop is already running (e.g. in
                # Jupyter / Streamlit). Use get_event_loop().run_until_complete() which
                # works in both contexts.
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                raw_tts = loop.run_until_complete(_run_all_tts())

                for seg, result in zip(segments_needing_tts, raw_tts):
                    seg_id = seg["id"]
                    if isinstance(result, Exception):
                        tts_results[seg_id] = {"success": False, "error": str(result), "audio_path": None, "duration": 0}
                        mark_segment_stage(project_dir, seg_id, "tts", done=False, error=str(result))
                    else:
                        tts_results[seg_id] = result
                        if result.get("success"):
                            mark_segment_stage(project_dir, seg_id, "tts", done=True,
                                               artifacts=[result.get("audio_path", "")])
                        else:
                            mark_segment_stage(project_dir, seg_id, "tts", done=False,
                                               error=result.get("error", ""))

            tts_ok = sum(1 for r in tts_results.values() if r.get("success"))
            tts_elapsed = time.perf_counter() - tts_start
            timings.append(("Voiceover", "ok" if tts_ok > 0 else "failed", tts_elapsed))

            # Mark the whole TTS stage done if all segments succeeded
            if tts_ok == num_segments:
                mark_stage_done(project_dir, "tts", artifacts=[
                    tts_results[seg["id"]].get("audio_path", "") for seg in segments
                    if tts_results.get(seg["id"], {}).get("success")
                ])
                state = load_project(project_dir)

            yield {"stage": "tts", "status": f"TTS complete: {tts_ok}/{num_segments} succeeded", "tts_results": tts_results}

    # ── Step 3: Parallel code generation ──────────────────────────────

    code_results: dict[int, dict] = {}
    tool_call_counts: dict[str, int] = {}

    def _merge_tool_calls(counts: dict[str, int] | None) -> None:
        if not counts:
            return
        for tool_name, count in counts.items():
            if not isinstance(count, int):
                continue
            tool_call_counts[tool_name] = tool_call_counts.get(tool_name, 0) + count

    theme_name = storyboard.get("theme_name", "")
    color_palette = storyboard.get("color_palette", {})
    status_queue: Queue[dict] = Queue()

    # Identify segments that already have code+video from a previous run
    segments_needing_code: list[dict] = []
    for seg in segments:
        seg_id = seg["id"]
        if resumed and state and is_segment_stage_done(state, seg_id, "code"):
            # Check if a video file actually exists on disk
            seg_output_dir = os.path.join(project_dir, f"segment_{seg_id}")
            seg_artifacts = state.get("segments", {}).get(str(seg_id), {}).get("code", {}).get("artifacts", [])
            video_found = None
            for art in seg_artifacts:
                if art and os.path.isfile(art):
                    video_found = art
                    break
            if not video_found:
                # Also check for common video filename patterns in the segment dir
                if os.path.isdir(seg_output_dir):
                    for f in os.listdir(seg_output_dir):
                        if f.endswith(".mp4"):
                            video_found = os.path.join(seg_output_dir, f)
                            break
            if video_found:
                code_results[seg_id] = {
                    "success": True,
                    "video_path": video_found,
                    "code_validated": True,
                    "code": "",  # Code text not needed for skipped segments
                }
                continue
        segments_needing_code.append(seg)

    cached_code_count = len(code_results)

    def _run_coder_for_segment(seg: dict, few_shot_example: str = "", emit_to_queue: bool = True) -> dict:
        seg_id = seg["id"]
        seg_output_dir = os.path.join(project_dir, f"segment_{seg_id}")
        os.makedirs(seg_output_dir, exist_ok=True)
        tts_r = tts_results.get(seg_id, {})
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
            if emit_to_queue:
                status_queue.put({"segment_id": seg_id, **update})
        return last_update

    code_all_cached = cached_code_count == num_segments

    if code_all_cached:
        # All segments already have code — skip entirely
        code_ok = num_segments
        timings.append(("Code + Validation", "skipped", 0.0))
        yield {
            "stage": "code",
            "status": f"Skipping (already completed) — {code_ok}/{num_segments} segments cached",
            "skipped": True,
            "code_results": code_results,
        }
    else:
        if cached_code_count > 0:
            yield {
                "stage": "code",
                "status": f"Generating Manim code: {cached_code_count} cached, {len(segments_needing_code)} remaining...",
            }
            for seg_id_cached in list(code_results.keys()):
                yield {
                    "stage": "code",
                    "segment_id": seg_id_cached,
                    "segment_phase": "done",
                    "segment_final": True,
                    "status": f"Segment {seg_id_cached}: cached (skipped)",
                    "skipped": True,
                }
        else:
            yield {"stage": "code", "status": f"Generating Manim code for {num_segments} segments in parallel..."}

        code_start = time.perf_counter()

        max_workers = max(1, min(5, len(segments_needing_code)))
        futures_map: dict[Any, dict] = {}
        segment_done_count = cached_code_count

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for seg in segments_needing_code:
                futures_map[executor.submit(_run_coder_for_segment, seg)] = seg

            for fut in as_completed(futures_map):
                yield from _drain_status_queue(status_queue)
                seg = futures_map[fut]
                seg_id = seg["id"]

                try:
                    result = fut.result()
                except Exception as exc:
                    result = {"success": False, "error": str(exc), "final": True}

                code_results[seg_id] = result
                _merge_tool_calls(result.get("tool_call_counts"))

                has_code = _has_valid_code(result)
                if has_code:
                    mark_segment_stage(project_dir, seg_id, "code", done=True,
                                       artifacts=[result.get("video_path", "")])
                    if result.get("video_path"):
                        mark_segment_stage(project_dir, seg_id, "render", done=True,
                                           artifacts=[result.get("video_path", "")])
                else:
                    mark_segment_stage(project_dir, seg_id, "code", done=False,
                                       error=result.get("error", "Code generation failed"))

                segment_done_count += 1
                yield {
                    "stage": "code",
                    "segment_id": seg_id,
                    "segment_phase": "done" if has_code else "failed",
                    "segment_final": True,
                    "status": (
                        f"Segment {seg_id}: done ({segment_done_count}/{num_segments})"
                        if has_code
                        else f"Segment {seg_id}: failed ({segment_done_count}/{num_segments})"
                    ),
                }

            yield from _drain_status_queue(status_queue)

        code_ok = sum(1 for r in code_results.values() if _has_valid_code(r))
        code_elapsed = time.perf_counter() - code_start
        timings.append(("Code + Validation", "ok" if code_ok > 0 else "failed", code_elapsed))

        # Mark code stage done if all segments succeeded
        if code_ok == num_segments:
            mark_stage_done(project_dir, "code", artifacts=[])
            state = load_project(project_dir)

        yield {
            "stage": "code",
            "status": f"Code generation complete: {code_ok}/{num_segments} have videos",
            "code_results": code_results,
        }

    # ── Step 3.1: Pipeline-level retry for failed segments ────────
    failed_seg_ids = [sid for sid, r in code_results.items() if not _has_valid_code(r)]
    if failed_seg_ids and code_ok > 0:
        # Pick the shortest successful segment's code as a few-shot example
        successful_codes = {}
        for seg in segments:
            sid = seg["id"]
            r = code_results.get(sid, {})
            if _has_valid_code(r) and r.get("code"):
                successful_codes[sid] = r["code"]
        few_shot_example = ""
        if successful_codes:
            few_shot_example = min(successful_codes.values(), key=len)

        yield {
            "stage": "code_retry",
            "status": f"Retrying {len(failed_seg_ids)} failed segment(s) in parallel with few-shot reference...",
        }

        failed_segs = [seg for seg in segments if seg["id"] in failed_seg_ids]

        retry_max_workers = max(1, min(5, len(failed_segs)))
        retry_futures_map: dict[Any, dict] = {}

        with ThreadPoolExecutor(max_workers=retry_max_workers) as retry_executor:
            for seg in failed_segs:
                retry_futures_map[retry_executor.submit(
                    _run_coder_for_segment, seg, few_shot_example, False
                )] = seg

            for fut in as_completed(retry_futures_map):
                seg = retry_futures_map[fut]
                sid = seg["id"]
                try:
                    last_update = fut.result()
                except Exception as exc:
                    last_update = {"success": False, "error": str(exc), "final": True}

                code_results[sid] = last_update
                _merge_tool_calls(last_update.get("tool_call_counts"))

                has_code = _has_valid_code(last_update)
                if has_code:
                    mark_segment_stage(project_dir, sid, "code", done=True,
                                       artifacts=[last_update.get("video_path", "")])
                    if last_update.get("video_path"):
                        mark_segment_stage(project_dir, sid, "render", done=True,
                                           artifacts=[last_update.get("video_path", "")])
                    code_ok += 1
                    yield {
                        "stage": "code_retry",
                        "segment_id": sid,
                        "status": f"Retry Segment {sid}: recovered!",
                        "segment_phase": "done",
                        "segment_final": True,
                    }
                else:
                    yield {
                        "stage": "code_retry",
                        "segment_id": sid,
                        "status": f"Retry Segment {sid}: still failed",
                        "segment_phase": "failed",
                        "segment_final": True,
                    }

    # ── Step 3.5: Parallel HD Rendering ───────────────────────────
    if code_ok > 0:
        # Check which segments already have HD renders from a previous run
        hd_jobs = []
        hd_cached = 0
        for seg in segments:
            seg_id = seg["id"]
            code_r = code_results.get(seg_id, {})
            if not _has_valid_code(code_r):
                continue
            # Check if this segment's HD render is already done
            if resumed and state and is_segment_stage_done(state, seg_id, "hd_render"):
                seg_hd_info = state.get("segments", {}).get(str(seg_id), {}).get("hd_render", {})
                hd_artifacts = seg_hd_info.get("artifacts", [])
                hd_found = any(os.path.isfile(a) for a in hd_artifacts if a)
                if hd_found:
                    hd_cached += 1
                    continue
            # Need code text to re-render; skip segments that were cached without code
            if not code_r.get("code"):
                continue
            seg_output_dir = os.path.join(project_dir, f"segment_{seg_id}")
            hd_jobs.append(RenderJob(
                segment_id=seg_id,
                code=code_r["code"],
                quality_flag="-qh",
                timeout_seconds=render_timeout_seconds or 300,
                output_dir=seg_output_dir,
            ))

        if not hd_jobs and hd_cached > 0:
            # All HD renders already done
            timings.append(("HD Render", "skipped", 0.0))
            yield {
                "stage": "render",
                "status": f"Skipping (already completed) — {hd_cached} HD renders cached",
                "skipped": True,
                "code_results": code_results,
            }
        elif hd_jobs:
            if hd_cached > 0:
                yield {"stage": "render", "status": f"Rendering HD videos: {hd_cached} cached, {len(hd_jobs)} remaining..."}
            else:
                yield {"stage": "render", "status": f"Rendering final HD videos for {code_ok} segments in parallel..."}
            render_start = time.perf_counter()

            hd_results = render_parallel(hd_jobs)
            hd_ok = hd_cached
            for res in hd_results:
                seg_id = res.segment_id
                if res.success and res.video_path:
                    code_results[seg_id]["video_path"] = res.video_path
                    hd_ok += 1
                    mark_segment_stage(project_dir, seg_id, "hd_render", done=True, artifacts=[res.video_path])
                else:
                    mark_segment_stage(project_dir, seg_id, "hd_render", done=False, error=res.error or "Unknown error")

            render_elapsed = time.perf_counter() - render_start
            timings.append(("HD Render", "ok" if hd_ok == code_ok else "partial", render_elapsed))

            # Mark render stage done if all succeeded
            if hd_ok == code_ok:
                mark_stage_done(project_dir, "render", artifacts=[])
                state = load_project(project_dir)

            yield {
                "stage": "render",
                "status": f"HD Rendering complete: {hd_ok}/{code_ok} succeeded",
                "code_results": code_results,
            }

    # ── Step 4: Stitch audio+video per segment (parallel) ──────────────

    stitch_errors: list[str] = []

    if not skip_audio:
        # Check if stitch stage is fully cached
        stitch_all_cached = False
        if resumed and state and is_stage_done(state, "stitch"):
            # Verify stitched files exist
            all_stitched_present = True
            cached_stitched: dict[int, str] = {}
            for seg in segments:
                seg_id = seg["id"]
                stitched_path = os.path.join(project_dir, f"segment_{seg_id}_stitched.mp4")
                if os.path.isfile(stitched_path):
                    cached_stitched[seg_id] = stitched_path
                elif is_segment_stage_done(state, seg_id, "stitch"):
                    seg_stitch_info = state.get("segments", {}).get(str(seg_id), {}).get("stitch", {})
                    artifacts = seg_stitch_info.get("artifacts", [])
                    found_art = next((a for a in artifacts if a and os.path.isfile(a)), None)
                    if found_art:
                        cached_stitched[seg_id] = found_art
                    else:
                        all_stitched_present = False
                        break
                else:
                    all_stitched_present = False
                    break

            if all_stitched_present and cached_stitched:
                stitch_all_cached = True
                timings.append(("Stitch", "skipped", 0.0))
                yield {
                    "stage": "stitch",
                    "status": f"Skipping (already completed) — {len(cached_stitched)} stitched files cached",
                    "skipped": True,
                }
                valid_paths = [cached_stitched.get(seg["id"]) for seg in segments
                               if cached_stitched.get(seg["id"])]

        if not stitch_all_cached:
            yield {"stage": "stitch", "status": "Stitching audio and video per segment..."}
            stitch_start = time.perf_counter()

            stitched_results: dict[int, tuple[str | None, str | None]] = {}  # seg_id -> (path, error)

            def _stitch_one(seg: dict) -> tuple[int, str | None, str | None]:
                seg_id = seg["id"]
                # Check if this individual segment's stitch is already cached
                if resumed and state and is_segment_stage_done(state, seg_id, "stitch"):
                    stitched_path = os.path.join(project_dir, f"segment_{seg_id}_stitched.mp4")
                    if os.path.isfile(stitched_path):
                        return (seg_id, stitched_path, None)
                    seg_stitch_info = state.get("segments", {}).get(str(seg_id), {}).get("stitch", {})
                    artifacts = seg_stitch_info.get("artifacts", [])
                    found_art = next((a for a in artifacts if a and os.path.isfile(a)), None)
                    if found_art:
                        return (seg_id, found_art, None)

                code_r = code_results.get(seg_id, {})
                tts_r = tts_results.get(seg_id, {})
                video_path = code_r.get("video_path")
                audio_path = tts_r.get("audio_path")

                if not video_path:
                    return (seg_id, None, f"Segment {seg_id}: no video to stitch")

                if not audio_path or not tts_r.get("success"):
                    mark_segment_stage(project_dir, seg_id, "stitch", done=True, artifacts=[video_path])
                    return (seg_id, video_path, None)

                stitched_output = os.path.join(project_dir, f"segment_{seg_id}_stitched.mp4")
                stitch_result = None
                for update in stitch_video_and_audio(video_path, audio_path, stitched_output):
                    if update.get("final"):
                        stitch_result = update

                if stitch_result and stitch_result.get("success"):
                    mark_segment_stage(project_dir, seg_id, "stitch", done=True,
                                       artifacts=[stitch_result["output_path"]])
                    return (seg_id, stitch_result["output_path"], None)
                else:
                    err = stitch_result.get("error", "unknown") if stitch_result else "unknown"
                    mark_segment_stage(project_dir, seg_id, "stitch", done=False, error=err)
                    return (seg_id, video_path, f"Segment {seg_id}: stitch failed ({err}), using raw video")

            with ThreadPoolExecutor(max_workers=max(1, len(segments))) as stitch_pool:
                futures = {stitch_pool.submit(_stitch_one, seg): seg["id"] for seg in segments}
                for fut in as_completed(futures):
                    seg_id, path, error = fut.result()
                    stitched_results[seg_id] = (path, error)
                    if error:
                        yield {"stage": "stitch", "status": f"Segment {seg_id}: {error}"}
                    else:
                        yield {"stage": "stitch", "status": f"Segment {seg_id} stitched."}

            # Reassemble in order
            stitched_paths: list[str] = []
            for seg in segments:
                path, error = stitched_results.get(seg["id"], (None, None))
                stitched_paths.append(path)
                if error:
                    stitch_errors.append(error)

            yield {"stage": "stitch", "status": f"Stitching done. Errors: {len(stitch_errors)}"}

            stitch_elapsed = time.perf_counter() - stitch_start
            timings.append(("Stitch", "ok" if len(stitch_errors) == 0 else "partial", stitch_elapsed))

            # Mark stitch stage done if no errors
            if len(stitch_errors) == 0:
                mark_stage_done(project_dir, "stitch", artifacts=[])
                state = load_project(project_dir)

            valid_paths = [p for p in stitched_paths if p is not None]
    else:
        # skip_audio: collect HD video paths directly, no stitching
        valid_paths = [
            code_results[seg["id"]]["video_path"]
            for seg in segments
            if code_results.get(seg["id"], {}).get("video_path")
        ]

    # ── Step 5: Concatenate all segments ──────────────────────────────

    if not valid_paths:
        yield {
            "stage": "done",
            "status": "No segments produced a video.",
            "error": "All segments failed.",
            "final": True,
            "project_dir": project_dir,
            "timings": timings,
            "tool_call_counts": dict(sorted(tool_call_counts.items())),
            "total_tool_calls": sum(tool_call_counts.values()),
        }
        _save_pipeline_summary(timings, project_dir, concept, tool_call_counts=tool_call_counts)
        return

    final_output = os.path.join(project_dir, f"{slug}.mp4")

    # Check if concat is already done from a previous run
    if resumed and state and is_stage_done(state, "concat") and os.path.isfile(final_output):
        timings.append(("Concat", "skipped", 0.0))
        mark_project_complete(project_dir)
        _save_pipeline_summary(timings, project_dir, concept, tool_call_counts=tool_call_counts)
        yield {
            "stage": "concat",
            "status": f"Skipping (already completed) — final video exists",
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
        _save_pipeline_summary(timings, project_dir, concept, tool_call_counts=tool_call_counts)
        yield {
            "stage": "done",
            "status": "Pipeline complete!",
            "final": True,
            "video_path": final_output,
            "project_dir": project_dir,
            "num_segments": num_segments,
            "stitch_errors": stitch_errors,
            "timings": timings,
            "tool_call_counts": dict(sorted(tool_call_counts.items())),
            "total_tool_calls": sum(tool_call_counts.values()),
        }
    else:
        err = concat_result.get("error", "unknown") if concat_result else "unknown"
        timings.append(("Concat", "failed", concat_elapsed))
        _save_pipeline_summary(timings, project_dir, concept, tool_call_counts=tool_call_counts)
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
        }
