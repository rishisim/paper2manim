"""Tests for pipeline resumability — skipping completed stages on re-run."""

from concurrent.futures import Future
import json
import os

import agents.pipeline as pipeline
import pytest
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

    def fake_submit_render_job(job):
        video_path = os.path.join(job.output_dir or "/tmp", f"hd_{job.segment_id}.mp4")
        os.makedirs(os.path.dirname(video_path), exist_ok=True)
        with open(video_path, "w") as f:
            f.write("hd video")
        future: Future = Future()
        future.set_result(type("RenderResult", (), {
            "segment_id": job.segment_id,
            "success": True,
            "video_path": video_path,
            "error": None,
        })())
        return future

    monkeypatch.setattr(pipeline, "run_math2manim_planner", fake_planner)
    monkeypatch.setattr(pipeline, "generate_voiceover_async", fake_tts_async)
    monkeypatch.setattr(pipeline, "run_coder_agent", fake_coder)
    monkeypatch.setattr(pipeline, "stitch_video_and_audio", fake_stitch)
    monkeypatch.setattr(pipeline, "concatenate_segments", fake_concat)
    monkeypatch.setattr(pipeline, "submit_render_job", fake_submit_render_job)

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


@pytest.mark.parametrize(
    ("failure_stage", "expected_stage_key"),
    [
        ("tts", "tts"),
        ("code", "code"),
        ("render", "hd_render"),
        ("stitch", "stitch"),
    ],
)
def test_stage_failures_are_flushed_to_project_state(monkeypatch, tmp_path, failure_stage, expected_stage_key):
    storyboard = {
        "theme_name": "Test",
        "color_palette": {"Background": "#141414", "Primary": "#00AAFF"},
        "segments": [
            {
                "id": 1,
                "title": "Segment 1",
                "learning_goal": "Explain one thing",
                "must_show": ["eq1"],
                "end_state": "eq1 visible",
                "carry_over_from_previous": "clean reset",
                "visual_density": "low",
                "scene_strategy": "clean_reset",
                "render_risk": "low",
                "expensive_features_allowed": False,
                "final_anchor_required": "Keep eq1 visible",
                "audio_script": "audio 1",
                "complexity": "simple",
                "visual_instructions": "visual 1",
                "equations_latex": [],
                "variable_definitions": {},
                "elements": [],
                "element_colors": {},
                "animations": [],
                "layout_instructions": "",
            }
        ],
    }

    def fake_planner(*args, **kwargs):
        yield {"status": "planning"}
        yield {"final": True, "storyboard": storyboard}

    async def fake_tts_async(script, audio_path):
        if failure_stage == "tts":
            return {"success": False, "audio_path": None, "duration": 0.0, "error": "tts failed"}
        os.makedirs(os.path.dirname(audio_path), exist_ok=True)
        with open(audio_path, "w", encoding="utf-8") as f:
            f.write("audio")
        return {"success": True, "audio_path": audio_path, "duration": 3.0}

    def fake_coder(*args, **kwargs):
        if failure_stage == "code":
            yield {
                "status": "code failed",
                "phase": "failed",
                "error": "code failed",
                "final": True,
                "tool_call_counts": {},
                "token_usage": {},
            }
            return

        yield {
            "status": "code ok",
            "phase": "done",
            "code": (
                "from manim import *\n"
                "class Segment1Scene(Scene):\n"
                "    def construct(self):\n"
                "        self.wait(1.0)\n"
            ),
            "code_validated": True,
            "final": True,
            "tool_call_counts": {},
            "token_usage": {},
        }

    def fake_submit_render_job(job):
        future: Future = Future()
        if failure_stage == "render":
            future.set_result(type("RenderResult", (), {
                "segment_id": job.segment_id,
                "success": False,
                "video_path": None,
                "error": "render failed",
            })())
        else:
            video_path = os.path.join(job.output_dir or str(tmp_path), f"hd_{job.segment_id}.mp4")
            os.makedirs(os.path.dirname(video_path), exist_ok=True)
            with open(video_path, "w", encoding="utf-8") as f:
                f.write("video")
            future.set_result(type("RenderResult", (), {
                "segment_id": job.segment_id,
                "success": True,
                "video_path": video_path,
                "error": None,
            })())
        return future

    def fake_stitch(video_path, audio_path, output_path):
        if failure_stage == "stitch":
            yield {"final": True, "success": False, "error": "stitch failed"}
            return
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("stitched")
        yield {"final": True, "success": True, "output_path": output_path}

    def fake_concat(paths, final_output):
        with open(final_output, "w", encoding="utf-8") as f:
            f.write("final")
        yield {"final": True, "success": True, "output_path": final_output}

    monkeypatch.setattr(pipeline, "run_math2manim_planner", fake_planner)
    monkeypatch.setattr(pipeline, "generate_voiceover_async", fake_tts_async)
    monkeypatch.setattr(pipeline, "run_coder_agent", fake_coder)
    monkeypatch.setattr(pipeline, "submit_render_job", fake_submit_render_job)
    monkeypatch.setattr(
        pipeline,
        "verify_segment_code",
        lambda *args, **kwargs: type("VerifyResult", (), {
            "segment_id": 1,
            "passed": True,
            "issues": [],
            "suggestions": [],
            "static_issues": [],
            "verification_tier": "static",
            "quality_risk": "low",
            "expensive_features": [],
        })(),
    )
    monkeypatch.setattr(
        pipeline,
        "critique_video",
        lambda *args, **kwargs: type("CritiqueResult", (), {
            "passed": True,
            "score": 0.9,
            "issues": [],
            "suggestions": [],
            "sub_scores": {},
        })(),
    )
    monkeypatch.setattr(pipeline, "stitch_video_and_audio", fake_stitch)
    monkeypatch.setattr(pipeline, "concatenate_segments", fake_concat)
    monkeypatch.setattr(pipeline, "verify_code_transitions", lambda *args, **kwargs: [])
    monkeypatch.setattr(pipeline, "critique_project_consistency", lambda *args, **kwargs: None)

    updates = list(
        pipeline.run_segmented_pipeline(
            f"flush {failure_stage}",
            output_base=str(tmp_path),
            questionnaire_answers={"quality_mode": "balanced"},
        )
    )

    final = updates[-1]
    state = load_project(final["project_dir"])
    assert state is not None
    assert state["segments"]["1"][expected_stage_key]["done"] is False
