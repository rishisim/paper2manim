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
import os
import re
import time
from typing import Any, Callable, Iterator, Optional

from agents.planner import plan_segmented_storyboard, plan_segmented_storyboard_lite
from agents.planner_math2manim import run_math2manim_planner
from agents.coder import run_coder_agent, run_coder_agent_async
from utils.tts_engine import generate_voiceover, generate_voiceover_async
from utils.media_assembler import stitch_video_and_audio, concatenate_segments
from utils.parallel_renderer import RenderJob, render_two_pass, render_parallel
from utils.project_state import (
    create_project,
    load_project,
    save_project,
    mark_stage_done,
    mark_segment_stage,
    mark_project_complete,
    is_segment_stage_done,
)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s-]+", "_", slug).strip("_")[:60]


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
    lines.append(f"{'Status':<8} {'Stage':<25} {'Time':>8}")
    lines.append("-" * 50)
    for name, status, elapsed in timings:
        tag = "OK" if status == "ok" else "ERR"
        lines.append(f"{tag:<8} {name:<25} {elapsed:>7.1f}s")
    lines.append("-" * 50)
    lines.append(f"{'':8} {'Total':<25} {total:>7.1f}s")
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
) -> Iterator[dict]:
    """Run the full segmented pipeline, yielding progress updates.

    Each yielded dict has at least ``{"stage", "status"}``.
    The final yield has ``{"stage": "done", "final": True, ...}``.
    """

    # ── Step 1: Planning ──────────────────────────────────────────────

    yield {"stage": "plan", "status": "Starting segmented storyboard planning..."}
    plan_start = time.perf_counter()

    storyboard = None
    planner_func = plan_segmented_storyboard_lite if is_lite else run_math2manim_planner
    for update in planner_func(
        concept,
        max_retries=max_retries,
        previous_storyboard=previous_storyboard,
        feedback=feedback,
    ):
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
    timings: list[tuple[str, str, float]] = [("Plan", "ok", plan_elapsed)]
    yield {
        "stage": "plan",
        "status": f"Storyboard planned: {num_segments} segments",
        "storyboard": storyboard,
        "num_segments": num_segments,
    }

    # Create project directory
    slug = _slugify(concept)
    project_dir = os.path.join(output_base, f"{slug}_{id(storyboard) % 10000:04d}")
    state = create_project(project_dir, concept, slug, total_segments=num_segments)
    mark_stage_done(project_dir, "plan", artifacts=[])

    # ── Step 2: Parallel TTS ──────────────────────────────────────────

    yield {"stage": "tts", "status": f"Generating voiceovers for {num_segments} segments in parallel..."}
    tts_start = time.perf_counter()

    tts_results: dict[int, dict] = {}

    async def _run_all_tts():
        tasks = []
        for seg in segments:
            seg_id = seg["id"]
            audio_path = os.path.join(project_dir, f"segment_{seg_id}_audio.wav")
            tasks.append(generate_voiceover_async(seg["audio_script"], audio_path))
        return await asyncio.gather(*tasks, return_exceptions=True)

    raw_tts = asyncio.run(_run_all_tts())

    for seg, result in zip(segments, raw_tts):
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
    yield {"stage": "tts", "status": f"TTS complete: {tts_ok}/{num_segments} succeeded", "tts_results": tts_results}

    # ── Step 3: Parallel code generation ──────────────────────────────

    yield {"stage": "code", "status": f"Generating Manim code for {num_segments} segments in parallel..."}
    code_start = time.perf_counter()

    code_results: dict[int, dict] = {}
    tool_call_counts: dict[str, int] = {}

    def _merge_tool_calls(counts: dict[str, int] | None) -> None:
        if not counts:
            return
        for tool_name, count in counts.items():
            if not isinstance(count, int):
                continue
            tool_call_counts[tool_name] = tool_call_counts.get(tool_name, 0) + count

    async def _run_all_coder():
        tasks = []
        theme_name = storyboard.get("theme_name", "")
        color_palette = storyboard.get("color_palette", {})
        
        for seg in segments:
            seg_id = seg["id"]
            seg_output_dir = os.path.join(project_dir, f"segment_{seg_id}")
            os.makedirs(seg_output_dir, exist_ok=True)
            tts_r = tts_results.get(seg_id, {})
            
            # Pass simple string for Lite, pass full segment dict for Pro
            coder_instructions = seg["visual_instructions"] if is_lite else seg
            
            tasks.append(run_coder_agent_async(
                instructions=coder_instructions,
                max_retries=max_retries,
                audio_script=seg.get("audio_script", ""),
                audio_duration=tts_r.get("duration", 0.0) or 0.0,
                complexity=seg.get("complexity", "complex"),
                scene_class_name=f"Segment{seg_id}Scene",
                output_dir=seg_output_dir,
                theme_name=theme_name,
                color_palette=color_palette,
            ))
        return await asyncio.gather(*tasks, return_exceptions=True)

    raw_code = asyncio.run(_run_all_coder())

    for seg, result in zip(segments, raw_code):
        seg_id = seg["id"]
        if isinstance(result, Exception):
            code_results[seg_id] = {"success": False, "error": str(result)}
            mark_segment_stage(project_dir, seg_id, "code", done=False, error=str(result))
        else:
            code_results[seg_id] = result
            _merge_tool_calls(result.get("tool_call_counts"))
            has_video = result.get("video_path") is not None
            if has_video:
                mark_segment_stage(project_dir, seg_id, "code", done=True,
                                   artifacts=[result.get("video_path", "")])
                mark_segment_stage(project_dir, seg_id, "render", done=True,
                                   artifacts=[result.get("video_path", "")])
            else:
                mark_segment_stage(project_dir, seg_id, "code", done=False,
                                   error=result.get("error", "Code generation failed"))

    code_ok = sum(1 for r in code_results.values() if r.get("video_path"))
    code_elapsed = time.perf_counter() - code_start
    timings.append(("Code + Draft Render", "ok" if code_ok > 0 else "failed", code_elapsed))
    yield {
        "stage": "code",
        "status": f"Code generation complete: {code_ok}/{num_segments} have videos",
        "code_results": code_results,
    }

    # ── Step 3.5: Parallel HD Rendering ───────────────────────────
    if code_ok > 0:
        yield {"stage": "render", "status": f"Rendering final HD videos for {code_ok} segments in parallel..."}
        render_start = time.perf_counter()
        
        hd_jobs = []
        for seg in segments:
            seg_id = seg["id"]
            if code_results.get(seg_id, {}).get("code") and code_results.get(seg_id, {}).get("video_path"):
                seg_output_dir = os.path.join(project_dir, f"segment_{seg_id}")
                hd_jobs.append(RenderJob(
                    segment_id=seg_id,
                    code=code_results[seg_id]["code"],
                    quality_flag="-qh",
                    timeout_seconds=300,
                    output_dir=seg_output_dir,
                ))
        
        hd_results = render_parallel(hd_jobs)
        hd_ok = 0
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
        yield {
            "stage": "render",
            "status": f"HD Rendering complete: {hd_ok}/{code_ok} succeeded",
            "code_results": code_results,
        }

    # ── Step 4: Stitch audio+video per segment ────────────────────────

    yield {"stage": "stitch", "status": "Stitching audio and video per segment..."}
    stitch_start = time.perf_counter()

    stitched_paths: list[str] = []
    stitch_errors: list[str] = []

    for seg in segments:
        seg_id = seg["id"]
        code_r = code_results.get(seg_id, {})
        tts_r = tts_results.get(seg_id, {})

        video_path = code_r.get("video_path")
        audio_path = tts_r.get("audio_path")

        if not video_path:
            stitch_errors.append(f"Segment {seg_id}: no video to stitch")
            stitched_paths.append(None)
            continue

        if not audio_path or not tts_r.get("success"):
            # No audio — use raw video
            yield {"stage": "stitch", "status": f"Segment {seg_id}: no audio, using raw video"}
            stitched_paths.append(video_path)
            mark_segment_stage(project_dir, seg_id, "stitch", done=True,
                               artifacts=[video_path])
            continue

        stitched_output = os.path.join(project_dir, f"segment_{seg_id}_stitched.mp4")
        yield {"stage": "stitch", "status": f"Stitching segment {seg_id}..."}

        stitch_result = None
        for update in stitch_video_and_audio(video_path, audio_path, stitched_output):
            if update.get("final"):
                stitch_result = update

        if stitch_result and stitch_result.get("success"):
            stitched_paths.append(stitch_result["output_path"])
            mark_segment_stage(project_dir, seg_id, "stitch", done=True,
                               artifacts=[stitch_result["output_path"]])
        else:
            # Fall back to raw video
            stitched_paths.append(video_path)
            err = stitch_result.get("error", "unknown") if stitch_result else "unknown"
            stitch_errors.append(f"Segment {seg_id}: stitch failed ({err}), using raw video")
            mark_segment_stage(project_dir, seg_id, "stitch", done=False, error=err)

    yield {"stage": "stitch", "status": f"Stitching done. Errors: {len(stitch_errors)}"}

    # ── Step 5: Concatenate all segments ──────────────────────────────

    stitch_elapsed = time.perf_counter() - stitch_start
    timings.append(("Stitch", "ok" if len(stitch_errors) == 0 else "partial", stitch_elapsed))

    valid_paths = [p for p in stitched_paths if p is not None]

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
