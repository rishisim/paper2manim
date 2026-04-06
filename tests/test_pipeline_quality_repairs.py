from __future__ import annotations

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

    def fake_render_parallel(jobs):
        render_calls["count"] += 1
        out = tmp_path / f"render_{render_calls['count']}.mp4"
        out.write_text("video")
        return [SimpleNamespace(success=True, video_path=str(out), error=None)]

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
    monkeypatch.setattr(pipeline, "verify_segment_code", fake_verify)
    monkeypatch.setattr(pipeline, "render_parallel", fake_render_parallel)
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

    assert call_counter["count"] >= 3
    assert any("Too cluttered" in feedback for feedback in repair_feedbacks)
    assert any(u.get("stage") == "code_retry" for u in updates)
    assert any(
        info["repair_attempted"] is True
        for info in updates[-1]["segment_quality"].values()
    )


def test_transition_verification_repairs_later_segment(monkeypatch, tmp_path):
    repair_feedbacks: list[str] = []

    def fake_planner(*args, **kwargs):
        yield {"status": "planning"}
        yield {"final": True, "storyboard": _planner_storyboard()}

    async def fake_tts_async(script, audio_path):
        return {"success": True, "audio_path": audio_path, "duration": 4.0}

    def fake_coder(*args, **kwargs):
        repair_feedbacks.append(kwargs.get("repair_feedback", ""))
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

    def fake_render_parallel(jobs):
        out = tmp_path / f"{jobs[0].segment_id}_{jobs[0].quality_flag.replace('-', '')}.mp4"
        out.write_text("video")
        return [SimpleNamespace(success=True, video_path=str(out), error=None)]

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
    monkeypatch.setattr(pipeline, "verify_segment_code", fake_verify)
    monkeypatch.setattr(pipeline, "render_parallel", fake_render_parallel)
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
