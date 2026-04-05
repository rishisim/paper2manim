"""Tests for pipeline resumability — skipping completed stages on re-run."""

import json
import os

import agents.pipeline as pipeline
from utils.project_state import (
    load_project,
)

# ── Shared fakes ──────────────────────────────────────────────────────

STORYBOARD = {
    "theme_name": "Test",
    "color_palette": {"primary": "#00AAFF"},
    "segments": [
        {
            "id": i,
            "audio_script": f"audio {i}",
            "complexity": "complex",
            "visual_instructions": f"visual {i}",
            "equations_latex": [],
            "variable_definitions": {},
            "elements": [],
            "element_colors": {},
            "animations": [],
            "layout_instructions": "",
        }
        for i in range(1, 4)  # 3 segments for faster tests
    ],
}


def _apply_monkeypatches(monkeypatch):
    """Wire up all fake functions so no real LLM/TTS/render calls happen."""
    call_counts = {"planner": 0, "tts": 0, "coder": 0, "stitch": 0, "concat": 0}

    def fake_planner(concept, max_retries=3, previous_storyboard=None, feedback=None):
        call_counts["planner"] += 1
        yield {"status": "planning"}
        yield {"final": True, "storyboard": STORYBOARD}

    async def fake_tts_async(script, audio_path):
        call_counts["tts"] += 1
        # Write a tiny file so the file-existence check passes on resume
        os.makedirs(os.path.dirname(audio_path), exist_ok=True)
        with open(audio_path, "w") as f:
            f.write("fake audio data")
        return {"success": True, "audio_path": audio_path, "duration": 1.0}

    def fake_coder(*args, **kwargs):
        call_counts["coder"] += 1
        scene = kwargs.get("scene_class_name", "SegmentX")
        seg_id = kwargs.get("segment_id", 0)
        output_dir = kwargs.get("output_dir", "/tmp")
        video_path = os.path.join(output_dir, f"{scene}.mp4")
        os.makedirs(output_dir, exist_ok=True)
        with open(video_path, "w") as f:
            f.write("fake video data")
        yield {"status": f"{scene}: Generating...", "phase": "generate"}
        yield {
            "status": f"{scene}: Success",
            "phase": "done",
            "video_path": video_path,
            "code": f"# code for segment {seg_id}",
            "code_validated": True,
            "final": True,
            "tool_call_counts": {},
        }

    def fake_stitch(video_path, audio_path, stitched_output):
        call_counts["stitch"] += 1
        os.makedirs(os.path.dirname(stitched_output), exist_ok=True)
        with open(stitched_output, "w") as f:
            f.write("stitched data")
        yield {"final": True, "success": True, "output_path": stitched_output}

    def fake_concat(paths, final_output):
        call_counts["concat"] += 1
        os.makedirs(os.path.dirname(final_output), exist_ok=True)
        with open(final_output, "w") as f:
            f.write("final video")
        yield {"status": "concatenating"}
        yield {"final": True, "success": True, "output_path": final_output}

    # render_parallel is used for HD rendering
    def fake_render_parallel(jobs):
        from utils.parallel_renderer import RenderResult
        results = []
        for job in jobs:
            video_path = os.path.join(job.output_dir or "/tmp", f"hd_{job.segment_id}.mp4")
            os.makedirs(os.path.dirname(video_path), exist_ok=True)
            with open(video_path, "w") as f:
                f.write("hd video")
            results.append(RenderResult(
                segment_id=job.segment_id,
                success=True,
                video_path=video_path,
            ))
        return results

    monkeypatch.setattr(pipeline, "run_math2manim_planner", fake_planner)
    monkeypatch.setattr(pipeline, "generate_voiceover_async", fake_tts_async)
    monkeypatch.setattr(pipeline, "run_coder_agent", fake_coder)
    monkeypatch.setattr(pipeline, "stitch_video_and_audio", fake_stitch)
    monkeypatch.setattr(pipeline, "concatenate_segments", fake_concat)
    monkeypatch.setattr(pipeline, "render_parallel", fake_render_parallel)

    return call_counts


# ── Tests ─────────────────────────────────────────────────────────────

def test_fresh_run_completes_and_saves_storyboard(monkeypatch, tmp_path):
    """A fresh run (no prior state) should work exactly as before and save storyboard.json."""
    _apply_monkeypatches(monkeypatch)

    updates = list(
        pipeline.run_segmented_pipeline(
            "test concept",
            output_base=str(tmp_path),
            is_lite=False,
        )
    )

    # Verify pipeline completed
    final = updates[-1]
    assert final.get("final") is True
    assert final.get("video_path") is not None

    # Verify storyboard.json was saved
    project_dir = final["project_dir"]
    storyboard_path = os.path.join(project_dir, "storyboard.json")
    assert os.path.isfile(storyboard_path), "storyboard.json should be saved after planning"

    with open(storyboard_path) as f:
        saved_sb = json.load(f)
    assert "segments" in saved_sb
    assert len(saved_sb["segments"]) == 3


def test_resume_skips_plan_stage(monkeypatch, tmp_path):
    """When a project already has plan done + storyboard.json, planning should be skipped."""
    call_counts = _apply_monkeypatches(monkeypatch)

    # First run — builds everything from scratch
    updates1 = list(
        pipeline.run_segmented_pipeline(
            "test concept",
            output_base=str(tmp_path),
            is_lite=False,
        )
    )
    final1 = updates1[-1]
    assert final1.get("final") is True
    project_dir = final1["project_dir"]
    first_planner_calls = call_counts["planner"]
    assert first_planner_calls == 1

    # Reset the project status to in_progress so it can be resumed
    state = load_project(project_dir)
    state["status"] = "in_progress"
    # Remove concat to force re-concat (simulating partial completion)
    state["stages"].pop("concat", None)
    from utils.project_state import save_project
    save_project(project_dir, state)

    # Second run — should resume and skip planning
    updates2 = list(
        pipeline.run_segmented_pipeline(
            "test concept",
            output_base=str(tmp_path),
            is_lite=False,
        )
    )

    # Planner should NOT have been called again
    assert call_counts["planner"] == 1, "Planner should not be called on resume"

    # Should see a "Resuming" message
    resumed_msgs = [u for u in updates2 if u.get("resumed")]
    assert resumed_msgs, "Expected a 'resumed' status message"

    # Should see plan skip message
    plan_skips = [u for u in updates2 if u.get("stage") == "plan" and u.get("skipped")]
    assert plan_skips, "Expected plan stage to be marked as skipped"

    # Pipeline should still complete
    final2 = updates2[-1]
    assert final2.get("final") is True


def test_resume_skips_cached_tts_segments(monkeypatch, tmp_path):
    """When TTS audio files exist from a previous run, they should be reused."""
    call_counts = _apply_monkeypatches(monkeypatch)

    # First run
    updates1 = list(
        pipeline.run_segmented_pipeline(
            "tts resume",
            output_base=str(tmp_path),
            is_lite=False,
        )
    )
    final1 = updates1[-1]
    assert final1.get("final") is True
    first_tts_calls = call_counts["tts"]
    assert first_tts_calls == 3  # 3 segments

    # Reset to in_progress, remove concat
    project_dir = final1["project_dir"]
    state = load_project(project_dir)
    state["status"] = "in_progress"
    state["stages"].pop("concat", None)
    from utils.project_state import save_project
    save_project(project_dir, state)

    # Second run
    updates2 = list(
        pipeline.run_segmented_pipeline(
            "tts resume",
            output_base=str(tmp_path),
            is_lite=False,
        )
    )

    # TTS should be fully skipped (audio files exist, stage marked done)
    tts_skips = [u for u in updates2 if u.get("stage") == "tts" and u.get("skipped")]
    assert tts_skips, "Expected TTS stage to be skipped on resume"

    # TTS fake should NOT have been called again
    assert call_counts["tts"] == first_tts_calls, "TTS should not be called again on resume"


def test_resume_skips_cached_code_segments(monkeypatch, tmp_path):
    """When code/video files exist from a previous run, code gen should be skipped per-segment."""
    call_counts = _apply_monkeypatches(monkeypatch)

    # First run
    updates1 = list(
        pipeline.run_segmented_pipeline(
            "code resume",
            output_base=str(tmp_path),
            is_lite=False,
        )
    )
    final1 = updates1[-1]
    assert final1.get("final") is True
    first_coder_calls = call_counts["coder"]
    assert first_coder_calls == 3

    # Reset to in_progress
    project_dir = final1["project_dir"]
    state = load_project(project_dir)
    state["status"] = "in_progress"
    state["stages"].pop("concat", None)
    from utils.project_state import save_project
    save_project(project_dir, state)

    # Second run
    updates2 = list(
        pipeline.run_segmented_pipeline(
            "code resume",
            output_base=str(tmp_path),
            is_lite=False,
        )
    )

    # Code should show skipped segments
    code_skips = [u for u in updates2 if u.get("stage") == "code" and u.get("skipped")]
    assert code_skips, "Expected code stage segments to be skipped on resume"

    # Coder should NOT have been called again
    assert call_counts["coder"] == first_coder_calls, "Coder should not be called again on resume"


def test_force_restart_ignores_cache(monkeypatch, tmp_path):
    """force_restart=True should ignore all cached state and start fresh."""
    call_counts = _apply_monkeypatches(monkeypatch)

    # First run
    updates1 = list(
        pipeline.run_segmented_pipeline(
            "force restart",
            output_base=str(tmp_path),
            is_lite=False,
        )
    )
    final1 = updates1[-1]
    assert final1.get("final") is True

    # Reset to in_progress
    project_dir = final1["project_dir"]
    state = load_project(project_dir)
    state["status"] = "in_progress"
    state["stages"].pop("concat", None)
    from utils.project_state import save_project
    save_project(project_dir, state)

    first_planner = call_counts["planner"]

    # Second run with force_restart
    updates2 = list(
        pipeline.run_segmented_pipeline(
            "force restart",
            output_base=str(tmp_path),
            is_lite=False,
            force_restart=True,
        )
    )

    # Planner SHOULD be called again
    assert call_counts["planner"] == first_planner + 1, "Planner should be called with force_restart"

    # Should NOT see any resumed/skipped messages
    resumed_msgs = [u for u in updates2 if u.get("resumed")]
    assert not resumed_msgs, "Should not see resumed message with force_restart"

    final2 = updates2[-1]
    assert final2.get("final") is True


def test_completed_project_is_not_resumed(monkeypatch, tmp_path):
    """A project with status='completed' should not be picked up for resume."""
    call_counts = _apply_monkeypatches(monkeypatch)

    # First run (completes normally)
    updates1 = list(
        pipeline.run_segmented_pipeline(
            "completed project",
            output_base=str(tmp_path),
            is_lite=False,
        )
    )
    final1 = updates1[-1]
    assert final1.get("final") is True
    first_planner = call_counts["planner"]

    # Status should be "completed" — resume should NOT find it
    project_dir = final1["project_dir"]
    state = load_project(project_dir)
    assert state["status"] == "completed"

    # Second run — should be a fresh run since the old one is completed
    updates2 = list(
        pipeline.run_segmented_pipeline(
            "completed project",
            output_base=str(tmp_path),
            is_lite=False,
        )
    )

    # Planner should be called again (fresh run, not resume)
    assert call_counts["planner"] == first_planner + 1
    resumed_msgs = [u for u in updates2 if u.get("resumed")]
    assert not resumed_msgs, "Should not resume a completed project"
