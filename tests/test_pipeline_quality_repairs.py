from __future__ import annotations

from concurrent.futures import Future
from types import SimpleNamespace

import agents.pipeline as pipeline


def _planner_storyboard():
    return {
        "theme_name": "Test",
        "color_palette": {"Background": "#141414", "Primary": "#00AAFF"},
        "segments": [
            {
                "id": 1,
                "title": "One",
                "learning_goal": "Goal one",
                "must_show": ["eq1"],
                "end_state": "eq1 visible",
                "carry_over_from_previous": "clean reset",
                "visual_density": "medium",
                "audio_script": "audio 1",
                "complexity": "complex",
                "visual_instructions": "visual 1",
                "equations_latex": [],
                "variable_definitions": {},
                "elements": [],
                "element_colors": {},
                "animations": [],
                "layout_instructions": "",
            },
            {
                "id": 2,
                "title": "Two",
                "learning_goal": "Goal two",
                "must_show": ["eq2"],
                "end_state": "eq2 visible",
                "carry_over_from_previous": "reuse eq1",
                "visual_density": "medium",
                "audio_script": "audio 2",
                "complexity": "complex",
                "visual_instructions": "visual 2",
                "equations_latex": [],
                "variable_definitions": {},
                "elements": [],
                "element_colors": {},
                "animations": [],
                "layout_instructions": "",
            },
        ],
    }


def test_verify_failure_triggers_one_repair(monkeypatch, tmp_path):
    call_counter = {"count": 0}
    patch_counter = {"count": 0}
    repair_feedbacks: list[str] = []

    def fake_planner(*args, **kwargs):
        yield {"status": "planning"}
        yield {"final": True, "storyboard": _planner_storyboard()}

    async def fake_tts_async(script, audio_path):
        return {"success": True, "audio_path": audio_path, "duration": 4.0}

    def fake_coder(*args, **kwargs):
        call_counter["count"] += 1
        repair_feedbacks.append(kwargs.get("repair_feedback", ""))
        scene = kwargs["scene_class_name"]
        yield {"status": f"{scene}: generate", "phase": "generate"}
        yield {
            "status": f"{scene}: ok",
            "phase": "done",
            "code": "from manim import *\nclass SceneA(Scene):\n    def construct(self):\n        self.wait(1)\n",
            "code_validated": True,
            "final": True,
            "tool_call_counts": {},
            "token_usage": {},
        }

    def fake_patch_agent(*args, **kwargs):
        patch_counter["count"] += 1
        repair_feedbacks.append(kwargs.get("repair_feedback", ""))
        yield {
            "status": "patched",
            "phase": "done",
            "code": "from manim import *\nclass SceneA(Scene):\n    def construct(self):\n        self.wait(1.5)\n",
            "code_validated": True,
            "final": True,
            "tool_call_counts": {},
            "token_usage": {},
        }

    verify_calls = {"count": 0}

    def fake_verify(*args, **kwargs):
        verify_calls["count"] += 1
        passed = verify_calls["count"] > 1
        return SimpleNamespace(
            segment_id=1,
            passed=passed,
            issues=[] if passed else ["Too cluttered in the main zone."],
            suggestions=[],
            static_issues=[],
        )

    render_calls = {"count": 0}

    def fake_submit_render_job(job):
        render_calls["count"] += 1
        out = tmp_path / f"render_{render_calls['count']}.mp4"
        out.write_text("video")
        future: Future = Future()
        future.set_result(SimpleNamespace(success=True, video_path=str(out), error=None))
        return future

    def fake_critique(*args, **kwargs):
        return SimpleNamespace(
            passed=True,
            score=0.9,
            issues=[],
            suggestions=[],
            sub_scores={"readability": 0.9},
        )

    def fake_stitch(video_path, audio_path, output_path):
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("stitched")
        yield {"final": True, "success": True, "output_path": output_path}

    def fake_concat(paths, final_output):
        with open(final_output, "w", encoding="utf-8") as f:
            f.write("final")
        yield {"final": True, "success": True, "output_path": final_output}

    def fake_mux(video_path, srt_path, output_path):
        yield {"final": True, "success": True, "output_path": output_path}

    monkeypatch.setattr(pipeline, "run_math2manim_planner", fake_planner)
    monkeypatch.setattr(pipeline, "generate_voiceover_async", fake_tts_async)
    monkeypatch.setattr(pipeline, "run_coder_agent", fake_coder)
    monkeypatch.setattr(pipeline, "run_code_patch_agent", fake_patch_agent)
    monkeypatch.setattr(pipeline, "verify_segment_code", fake_verify)
    monkeypatch.setattr(pipeline, "submit_render_job", fake_submit_render_job)
    monkeypatch.setattr(pipeline, "critique_video", fake_critique)
    monkeypatch.setattr(pipeline, "stitch_video_and_audio", fake_stitch)
    monkeypatch.setattr(pipeline, "concatenate_segments", fake_concat)
    monkeypatch.setattr(pipeline, "mux_subtitles", fake_mux)
    monkeypatch.setattr(pipeline, "verify_code_transitions", lambda *args, **kwargs: [])
    monkeypatch.setattr(pipeline, "critique_project_consistency", lambda *args, **kwargs: SimpleNamespace(passed=True, issues=[]))

    updates = list(
        pipeline.run_segmented_pipeline(
            "demo",
            output_base=str(tmp_path),
            questionnaire_answers={"quality_mode": "balanced"},
        )
    )

    assert call_counter["count"] == 2
    assert patch_counter["count"] == 1
    assert any("Too cluttered" in feedback for feedback in repair_feedbacks)
    assert any(u.get("stage") == "code_retry" for u in updates)
    assert any(
        info["repair_attempted"] is True
        for info in updates[-1]["segment_quality"].values()
    )
    assert updates[-1]["runtime_metrics"]["code_patch_repairs"] == 1


def test_transition_verification_repairs_later_segment(monkeypatch, tmp_path):
    repair_feedbacks: list[str] = []
    generate_calls = {"count": 0}
    patch_calls = {"count": 0}

    def fake_planner(*args, **kwargs):
        yield {"status": "planning"}
        yield {"final": True, "storyboard": _planner_storyboard()}

    async def fake_tts_async(script, audio_path):
        return {"success": True, "audio_path": audio_path, "duration": 4.0}

    def fake_coder(*args, **kwargs):
        generate_calls["count"] += 1
        scene = kwargs["scene_class_name"]
        yield {
            "status": f"{scene}: ok",
            "phase": "done",
            "code": f"from manim import *\nclass {scene}(Scene):\n    def construct(self):\n        self.wait(1)\n",
            "code_validated": True,
            "final": True,
            "tool_call_counts": {},
            "token_usage": {},
        }

    def fake_patch_agent(*args, **kwargs):
        patch_calls["count"] += 1
        repair_feedbacks.append(kwargs.get("repair_feedback", ""))
        scene = kwargs["scene_class_name"]
        yield {
            "status": f"{scene}: patched",
            "phase": "done",
            "code": f"from manim import *\nclass {scene}(Scene):\n    def construct(self):\n        self.wait(1.5)\n",
            "code_validated": True,
            "final": True,
            "tool_call_counts": {},
            "token_usage": {},
        }

    def fake_submit_render_job(job):
        out = tmp_path / f"{job.segment_id}_{job.quality_flag.replace('-', '')}.mp4"
        out.write_text("video")
        future: Future = Future()
        future.set_result(SimpleNamespace(success=True, video_path=str(out), error=None))
        return future

    def fake_critique(*args, **kwargs):
        return SimpleNamespace(passed=True, score=0.9, issues=[], suggestions=[], sub_scores={})

    def fake_verify(*args, **kwargs):
        return SimpleNamespace(segment_id=1, passed=True, issues=[], suggestions=[], static_issues=[])

    def fake_transition_checks(*args, **kwargs):
        return [SimpleNamespace(segment_a_id=1, segment_b_id=2, smooth=False, issues=["Segment 2 starts without respecting the prior anchor."])]

    def fake_stitch(video_path, audio_path, output_path):
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(video_path)
        yield {"final": True, "success": True, "output_path": output_path}

    def fake_concat(paths, final_output):
        with open(final_output, "w", encoding="utf-8") as f:
            f.write("|".join(paths))
        yield {"final": True, "success": True, "output_path": final_output}

    def fake_mux(video_path, srt_path, output_path):
        yield {"final": True, "success": True, "output_path": output_path}

    monkeypatch.setattr(pipeline, "run_math2manim_planner", fake_planner)
    monkeypatch.setattr(pipeline, "generate_voiceover_async", fake_tts_async)
    monkeypatch.setattr(pipeline, "run_coder_agent", fake_coder)
    monkeypatch.setattr(pipeline, "run_code_patch_agent", fake_patch_agent)
    monkeypatch.setattr(pipeline, "verify_segment_code", fake_verify)
    monkeypatch.setattr(pipeline, "submit_render_job", fake_submit_render_job)
    monkeypatch.setattr(pipeline, "critique_video", fake_critique)
    monkeypatch.setattr(pipeline, "verify_code_transitions", fake_transition_checks)
    monkeypatch.setattr(pipeline, "stitch_video_and_audio", fake_stitch)
    monkeypatch.setattr(pipeline, "concatenate_segments", fake_concat)
    monkeypatch.setattr(pipeline, "mux_subtitles", fake_mux)
    monkeypatch.setattr(pipeline, "critique_project_consistency", lambda *args, **kwargs: SimpleNamespace(passed=True, issues=[]))

    updates = list(
        pipeline.run_segmented_pipeline(
            "demo",
            output_base=str(tmp_path),
            questionnaire_answers={"quality_mode": "balanced"},
        )
    )

    assert any("respecting the prior anchor" in feedback for feedback in repair_feedbacks)
    assert any(
        u.get("stage") == "code_retry" and u.get("segment_id") == 2
        for u in updates
    )
    assert generate_calls["count"] == 2
    assert patch_calls["count"] == 1


def test_transition_repair_reuses_same_run_tts(monkeypatch, tmp_path):
    call_counts = {"tts": 0}
    patch_calls = {"count": 0}

    def fake_planner(*args, **kwargs):
        yield {"status": "planning"}
        yield {"final": True, "storyboard": _planner_storyboard()}

    async def fake_tts_async(script, audio_path):
        call_counts["tts"] += 1
        return {"success": True, "audio_path": audio_path, "duration": 4.0}

    def fake_coder(*args, **kwargs):
        scene = kwargs["scene_class_name"]
        yield {
            "status": f"{scene}: ok",
            "phase": "done",
            "code": f"from manim import *\nclass {scene}(Scene):\n    def construct(self):\n        self.wait(1)\n",
            "code_validated": True,
            "final": True,
            "tool_call_counts": {},
            "token_usage": {},
        }

    def fake_patch_agent(*args, **kwargs):
        patch_calls["count"] += 1
        scene = kwargs["scene_class_name"]
        yield {
            "status": f"{scene}: patched",
            "phase": "done",
            "code": f"from manim import *\nclass {scene}(Scene):\n    def construct(self):\n        self.wait(1.5)\n",
            "code_validated": True,
            "final": True,
            "tool_call_counts": {},
            "token_usage": {},
        }

    def fake_submit_render_job(job):
        out = tmp_path / f"{job.segment_id}_{job.quality_flag.replace('-', '')}.mp4"
        out.write_text("video")
        future: Future = Future()
        future.set_result(SimpleNamespace(success=True, video_path=str(out), error=None))
        return future

    def fake_critique(*args, **kwargs):
        return SimpleNamespace(passed=True, score=0.9, issues=[], suggestions=[], sub_scores={})

    def fake_verify(*args, **kwargs):
        return SimpleNamespace(segment_id=1, passed=True, issues=[], suggestions=[], static_issues=[])

    def fake_transition_checks(*args, **kwargs):
        return [SimpleNamespace(segment_a_id=1, segment_b_id=2, smooth=False, issues=["Segment 2 starts without respecting the prior anchor."])]

    def fake_stitch(video_path, audio_path, output_path):
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(video_path)
        yield {"final": True, "success": True, "output_path": output_path}

    def fake_concat(paths, final_output):
        with open(final_output, "w", encoding="utf-8") as f:
            f.write("|".join(paths))
        yield {"final": True, "success": True, "output_path": final_output}

    def fake_mux(video_path, srt_path, output_path):
        yield {"final": True, "success": True, "output_path": output_path}

    monkeypatch.setattr(pipeline, "run_math2manim_planner", fake_planner)
    monkeypatch.setattr(pipeline, "generate_voiceover_async", fake_tts_async)
    monkeypatch.setattr(pipeline, "run_coder_agent", fake_coder)
    monkeypatch.setattr(pipeline, "run_code_patch_agent", fake_patch_agent)
    monkeypatch.setattr(pipeline, "verify_segment_code", fake_verify)
    monkeypatch.setattr(pipeline, "submit_render_job", fake_submit_render_job)
    monkeypatch.setattr(pipeline, "critique_video", fake_critique)
    monkeypatch.setattr(pipeline, "verify_code_transitions", fake_transition_checks)
    monkeypatch.setattr(pipeline, "stitch_video_and_audio", fake_stitch)
    monkeypatch.setattr(pipeline, "concatenate_segments", fake_concat)
    monkeypatch.setattr(pipeline, "mux_subtitles", fake_mux)
    monkeypatch.setattr(pipeline, "critique_project_consistency", lambda *args, **kwargs: SimpleNamespace(passed=True, issues=[]))

    updates = list(
        pipeline.run_segmented_pipeline(
            "demo",
            output_base=str(tmp_path),
            questionnaire_answers={"quality_mode": "balanced"},
        )
    )

    assert updates[-1]["final"] is True
    assert call_counts["tts"] == 2
    assert patch_calls["count"] == 1
    assert updates[-1]["runtime_metrics"]["same_run_cache_hits"] >= 1


def test_timing_mismatch_triggers_repair(monkeypatch, tmp_path):
    repair_feedbacks: list[str] = []
    patch_calls = {"count": 0}

    def fake_planner(*args, **kwargs):
        yield {"status": "planning"}
        yield {"final": True, "storyboard": _planner_storyboard()}

    async def fake_tts_async(script, audio_path):
        return {"success": True, "audio_path": audio_path, "duration": 8.0}

    def fake_coder(*args, **kwargs):
        repair_feedbacks.append(kwargs.get("repair_feedback", ""))
        scene = kwargs["scene_class_name"]
        yield {
            "status": f"{scene}: ok",
            "phase": "done",
            "code": (
                "from manim import *\n"
                f"class {scene}(Scene):\n"
                "    def construct(self):\n"
                "        self.play(Write(Text('hi')), run_time=1.0)\n"
                "        self.wait(0.5)\n"
            ),
            "code_validated": True,
            "final": True,
            "tool_call_counts": {},
            "token_usage": {},
        }

    def fake_patch_agent(*args, **kwargs):
        patch_calls["count"] += 1
        yield {
            "status": "patch failed",
            "phase": "failed",
            "error": "patch failed",
            "final": True,
            "tool_call_counts": {},
            "token_usage": {},
        }

    def fake_submit_render_job(job):
        out = tmp_path / f"{job.segment_id}_{job.quality_flag.replace('-', '')}.mp4"
        out.write_text("video")
        future: Future = Future()
        future.set_result(SimpleNamespace(success=True, video_path=str(out), error=None))
        return future

    def fake_critique(*args, **kwargs):
        return SimpleNamespace(passed=True, score=0.9, issues=[], suggestions=[], sub_scores={})

    def fake_stitch(video_path, audio_path, output_path):
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(video_path)
        yield {"final": True, "success": True, "output_path": output_path}

    def fake_concat(paths, final_output):
        with open(final_output, "w", encoding="utf-8") as f:
            f.write("|".join(paths))
        yield {"final": True, "success": True, "output_path": final_output}

    def fake_mux(video_path, srt_path, output_path):
        yield {"final": True, "success": True, "output_path": output_path}

    monkeypatch.setattr(pipeline, "run_math2manim_planner", fake_planner)
    monkeypatch.setattr(pipeline, "generate_voiceover_async", fake_tts_async)
    monkeypatch.setattr(pipeline, "run_coder_agent", fake_coder)
    monkeypatch.setattr(pipeline, "run_code_patch_agent", fake_patch_agent)
    monkeypatch.setattr(
        pipeline,
        "verify_segment_code",
        lambda *args, **kwargs: SimpleNamespace(
            segment_id=1,
            passed=False,
            issues=["Estimated scene timing (1.5s) is too short for the target audio (8.0s)."],
            suggestions=[],
            static_issues=["Estimated scene timing (1.5s) is too short for the target audio (8.0s)."],
        ),
    )
    monkeypatch.setattr(pipeline, "submit_render_job", fake_submit_render_job)
    monkeypatch.setattr(pipeline, "critique_video", fake_critique)
    monkeypatch.setattr(pipeline, "stitch_video_and_audio", fake_stitch)
    monkeypatch.setattr(pipeline, "concatenate_segments", fake_concat)
    monkeypatch.setattr(pipeline, "mux_subtitles", fake_mux)
    monkeypatch.setattr(pipeline, "verify_code_transitions", lambda *args, **kwargs: [])
    monkeypatch.setattr(pipeline, "critique_project_consistency", lambda *args, **kwargs: SimpleNamespace(passed=True, issues=[]))

    updates = list(
        pipeline.run_segmented_pipeline(
            "demo",
            output_base=str(tmp_path),
            questionnaire_answers={"quality_mode": "balanced"},
        )
    )

    assert patch_calls["count"] >= 1
    assert any("Estimated scene timing" in feedback for feedback in repair_feedbacks)
    assert any(u.get("stage") == "code_retry" for u in updates)
    assert updates[-1]["runtime_metrics"]["full_regen_repairs"] >= 1


def test_timing_normalization_can_avoid_repair(monkeypatch, tmp_path):
    def fake_planner(*args, **kwargs):
        yield {"status": "planning"}
        yield {"final": True, "storyboard": _planner_storyboard()}

    async def fake_tts_async(script, audio_path):
        return {"success": True, "audio_path": audio_path, "duration": 8.0}

    def fake_coder(*args, **kwargs):
        scene = kwargs["scene_class_name"]
        yield {
            "status": f"{scene}: ok",
            "phase": "done",
            "code": (
                "from manim import *\n"
                f"class {scene}(Scene):\n"
                "    def construct(self):\n"
                "        self.play(Write(Text('hi')), run_time=1.0)\n"
                "        self.wait(0.5)\n"
            ),
            "code_validated": True,
            "final": True,
            "tool_call_counts": {},
            "token_usage": {},
        }

    def fake_verify(*args, **kwargs):
        code = kwargs.get("code") if "code" in kwargs else args[1]
        if "self.wait(7.000)" in code:
            return SimpleNamespace(segment_id=1, passed=True, issues=[], suggestions=[], static_issues=[])
        return SimpleNamespace(
            segment_id=1,
            passed=False,
            issues=["Estimated scene timing (1.5s) is too short for the target audio (8.0s)."],
            suggestions=[],
            static_issues=["Estimated scene timing (1.5s) is too short for the target audio (8.0s)."],
        )

    def fake_submit_render_job(job):
        out = tmp_path / f"{job.segment_id}_{job.quality_flag.replace('-', '')}.mp4"
        out.write_text("video")
        future: Future = Future()
        future.set_result(SimpleNamespace(success=True, video_path=str(out), error=None))
        return future

    def fake_critique(*args, **kwargs):
        return SimpleNamespace(passed=True, score=0.9, issues=[], suggestions=[], sub_scores={})

    def fake_stitch(video_path, audio_path, output_path):
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(video_path)
        yield {"final": True, "success": True, "output_path": output_path}

    def fake_concat(paths, final_output):
        with open(final_output, "w", encoding="utf-8") as f:
            f.write("|".join(paths))
        yield {"final": True, "success": True, "output_path": final_output}

    def fake_mux(video_path, srt_path, output_path):
        yield {"final": True, "success": True, "output_path": output_path}

    monkeypatch.setattr(pipeline, "run_math2manim_planner", fake_planner)
    monkeypatch.setattr(pipeline, "generate_voiceover_async", fake_tts_async)
    monkeypatch.setattr(pipeline, "run_coder_agent", fake_coder)
    monkeypatch.setattr(pipeline, "verify_segment_code", fake_verify)
    monkeypatch.setattr(pipeline, "submit_render_job", fake_submit_render_job)
    monkeypatch.setattr(pipeline, "critique_video", fake_critique)
    monkeypatch.setattr(pipeline, "stitch_video_and_audio", fake_stitch)
    monkeypatch.setattr(pipeline, "concatenate_segments", fake_concat)
    monkeypatch.setattr(pipeline, "mux_subtitles", fake_mux)
    monkeypatch.setattr(pipeline, "verify_code_transitions", lambda *args, **kwargs: [])
    monkeypatch.setattr(pipeline, "critique_project_consistency", lambda *args, **kwargs: SimpleNamespace(passed=True, issues=[]))

    updates = list(
        pipeline.run_segmented_pipeline(
            "demo",
            output_base=str(tmp_path),
            questionnaire_answers={"quality_mode": "balanced"},
        )
    )

    assert not any(u.get("stage") == "code_retry" for u in updates)
    assert updates[-1]["segment_quality"][1]["timing_normalization"]["mode"] == "extend_final_wait"


def test_render_only_failure_reruns_render_without_regeneration(monkeypatch, tmp_path):
    call_counts = {"generate": 0, "render": 0}

    def fake_planner(*args, **kwargs):
        storyboard = _planner_storyboard()
        storyboard["segments"] = [storyboard["segments"][0]]
        yield {"status": "planning"}
        yield {"final": True, "storyboard": storyboard}

    async def fake_tts_async(script, audio_path):
        return {"success": True, "audio_path": audio_path, "duration": 4.0}

    def fake_coder(*args, **kwargs):
        call_counts["generate"] += 1
        scene = kwargs["scene_class_name"]
        yield {
            "status": f"{scene}: ok",
            "phase": "done",
            "code": f"from manim import *\nclass {scene}(Scene):\n    def construct(self):\n        self.wait(1)\n",
            "code_validated": True,
            "final": True,
            "tool_call_counts": {},
            "token_usage": {},
        }

    def fake_verify(*args, **kwargs):
        return SimpleNamespace(segment_id=1, passed=True, issues=[], suggestions=[], static_issues=[])

    def fake_submit_render_job(job):
        call_counts["render"] += 1
        future: Future = Future()
        if call_counts["render"] == 1:
            future.set_result(SimpleNamespace(success=False, video_path=None, error="render failed"))
        else:
            out = tmp_path / "rerender.mp4"
            out.write_text("video")
            future.set_result(SimpleNamespace(success=True, video_path=str(out), error=None))
        return future

    def fake_stitch(video_path, audio_path, output_path):
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("stitched")
        yield {"final": True, "success": True, "output_path": output_path}

    def fake_concat(paths, final_output):
        with open(final_output, "w", encoding="utf-8") as f:
            f.write("|".join(paths))
        yield {"final": True, "success": True, "output_path": final_output}

    def fake_mux(video_path, srt_path, output_path):
        yield {"final": True, "success": True, "output_path": output_path}

    monkeypatch.setattr(pipeline, "run_math2manim_planner", fake_planner)
    monkeypatch.setattr(pipeline, "generate_voiceover_async", fake_tts_async)
    monkeypatch.setattr(pipeline, "run_coder_agent", fake_coder)
    monkeypatch.setattr(pipeline, "verify_segment_code", fake_verify)
    monkeypatch.setattr(pipeline, "submit_render_job", fake_submit_render_job)
    monkeypatch.setattr(pipeline, "critique_video", lambda *args, **kwargs: SimpleNamespace(passed=True, score=0.9, issues=[], suggestions=[], sub_scores={}))
    monkeypatch.setattr(pipeline, "stitch_video_and_audio", fake_stitch)
    monkeypatch.setattr(pipeline, "concatenate_segments", fake_concat)
    monkeypatch.setattr(pipeline, "mux_subtitles", fake_mux)
    monkeypatch.setattr(pipeline, "verify_code_transitions", lambda *args, **kwargs: [])
    monkeypatch.setattr(pipeline, "critique_project_consistency", lambda *args, **kwargs: SimpleNamespace(passed=True, issues=[]))

    updates = list(
        pipeline.run_segmented_pipeline(
            "demo",
            output_base=str(tmp_path),
            questionnaire_answers={"quality_mode": "balanced"},
        )
    )

    assert updates[-1]["final"] is True
    assert call_counts["generate"] == 1
    assert call_counts["render"] == 2


def test_stitch_only_failure_reruns_stitch_without_regeneration(monkeypatch, tmp_path):
    call_counts = {"generate": 0, "render": 0, "stitch": 0}

    def fake_planner(*args, **kwargs):
        storyboard = _planner_storyboard()
        storyboard["segments"] = [storyboard["segments"][0]]
        yield {"status": "planning"}
        yield {"final": True, "storyboard": storyboard}

    async def fake_tts_async(script, audio_path):
        return {"success": True, "audio_path": audio_path, "duration": 4.0}

    def fake_coder(*args, **kwargs):
        call_counts["generate"] += 1
        scene = kwargs["scene_class_name"]
        yield {
            "status": f"{scene}: ok",
            "phase": "done",
            "code": f"from manim import *\nclass {scene}(Scene):\n    def construct(self):\n        self.wait(1)\n",
            "code_validated": True,
            "final": True,
            "tool_call_counts": {},
            "token_usage": {},
        }

    def fake_verify(*args, **kwargs):
        return SimpleNamespace(segment_id=1, passed=True, issues=[], suggestions=[], static_issues=[])

    def fake_submit_render_job(job):
        call_counts["render"] += 1
        out = tmp_path / "render.mp4"
        out.write_text("video")
        future: Future = Future()
        future.set_result(SimpleNamespace(success=True, video_path=str(out), error=None))
        return future

    def fake_stitch(video_path, audio_path, output_path):
        call_counts["stitch"] += 1
        if call_counts["stitch"] == 1:
            yield {"final": True, "success": False, "error": "mux failed", "output_path": None}
            return
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("stitched")
        yield {"final": True, "success": True, "output_path": output_path}

    def fake_concat(paths, final_output):
        with open(final_output, "w", encoding="utf-8") as f:
            f.write("|".join(paths))
        yield {"final": True, "success": True, "output_path": final_output}

    def fake_mux(video_path, srt_path, output_path):
        yield {"final": True, "success": True, "output_path": output_path}

    monkeypatch.setattr(pipeline, "run_math2manim_planner", fake_planner)
    monkeypatch.setattr(pipeline, "generate_voiceover_async", fake_tts_async)
    monkeypatch.setattr(pipeline, "run_coder_agent", fake_coder)
    monkeypatch.setattr(pipeline, "verify_segment_code", fake_verify)
    monkeypatch.setattr(pipeline, "submit_render_job", fake_submit_render_job)
    monkeypatch.setattr(pipeline, "critique_video", lambda *args, **kwargs: SimpleNamespace(passed=True, score=0.9, issues=[], suggestions=[], sub_scores={}))
    monkeypatch.setattr(pipeline, "stitch_video_and_audio", fake_stitch)
    monkeypatch.setattr(pipeline, "concatenate_segments", fake_concat)
    monkeypatch.setattr(pipeline, "mux_subtitles", fake_mux)
    monkeypatch.setattr(pipeline, "verify_code_transitions", lambda *args, **kwargs: [])
    monkeypatch.setattr(pipeline, "critique_project_consistency", lambda *args, **kwargs: SimpleNamespace(passed=True, issues=[]))

    updates = list(
        pipeline.run_segmented_pipeline(
            "demo",
            output_base=str(tmp_path),
            questionnaire_answers={"quality_mode": "balanced"},
        )
    )

    assert updates[-1]["final"] is True
    assert call_counts["generate"] == 1
    assert call_counts["render"] == 1
    assert call_counts["stitch"] == 2
