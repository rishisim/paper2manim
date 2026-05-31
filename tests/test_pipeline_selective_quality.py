from __future__ import annotations

from concurrent.futures import Future
from types import SimpleNamespace
import os

import agents.pipeline as pipeline
from utils.project_state import load_project, save_project


def _storyboard(render_risk: str = "low", num_segments: int = 1) -> dict:
    return {
        "theme_name": "Test",
        "color_palette": {"Background": "#141414", "Primary": "#00AAFF"},
        "segments": [
            {
                "id": i,
                "title": f"Segment {i}",
                "learning_goal": "Explain one thing",
                "must_show": [f"eq{i}"],
                "end_state": f"eq{i} visible",
                "carry_over_from_previous": "clean reset",
                "visual_density": "low",
                "scene_strategy": "single_focus_derivation",
                "render_risk": render_risk if isinstance(render_risk, str) else render_risk[i - 1],
                "expensive_features_allowed": False,
                "final_anchor_required": f"Keep eq{i} visible",
                "audio_script": f"audio {i}",
                "complexity": "simple",
                "visual_instructions": f"visual {i}",
                "equations_latex": [],
                "variable_definitions": {},
                "elements": [],
                "element_colors": {},
                "animations": [],
                "layout_instructions": "",
            }
            for i in range(1, num_segments + 1)
        ],
    }


def _install_common_fakes(monkeypatch, tmp_path, storyboard: dict, call_counts: dict[str, int]) -> None:
    def fake_planner(*args, **kwargs):
        yield {"status": "planning"}
        yield {"final": True, "storyboard": storyboard}

    async def fake_tts_async(script, audio_path):
        os.makedirs(os.path.dirname(audio_path), exist_ok=True)
        with open(audio_path, "w", encoding="utf-8") as f:
            f.write("audio")
        return {"success": True, "audio_path": audio_path, "duration": 4.0}

    def fake_coder(*args, **kwargs):
        output_dir = kwargs["output_dir"]
        os.makedirs(output_dir, exist_ok=True)
        video_path = os.path.join(output_dir, "preview.mp4")
        with open(video_path, "w", encoding="utf-8") as f:
            f.write("preview")
        yield {
            "status": "code ok",
            "phase": "done",
            "code": (
                "from manim import *\n"
                "class Segment1Scene(Scene):\n"
                "    def construct(self):\n"
                "        self.play(Write(Text('hi')), run_time=1.0)\n"
                "        self.wait(1.0)\n"
            ),
            "video_path": video_path,
            "code_validated": True,
            "final": True,
            "tool_call_counts": {},
            "token_usage": {},
        }

    def fake_submit_render_job(job):
        call_counts["render"] += 1
        out = tmp_path / f"{job.segment_id}_{job.quality_flag.replace('-', '')}.mp4"
        out.write_text("video")
        future: Future = Future()
        future.set_result(SimpleNamespace(success=True, video_path=str(out), error=None))
        return future

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
    monkeypatch.setattr(pipeline, "submit_render_job", fake_submit_render_job)
    monkeypatch.setattr(pipeline, "stitch_video_and_audio", fake_stitch)
    monkeypatch.setattr(pipeline, "concatenate_segments", fake_concat)
    monkeypatch.setattr(pipeline, "mux_subtitles", fake_mux)
    monkeypatch.setattr(pipeline, "verify_code_transitions", lambda *args, **kwargs: [])
    monkeypatch.setattr(pipeline, "critique_project_consistency", lambda *args, **kwargs: None)


def test_balanced_low_risk_segment_skips_visual_critique(monkeypatch, tmp_path):
    call_counts = {"render": 0, "critique": 0}
    storyboard = _storyboard(render_risk="low")
    _install_common_fakes(monkeypatch, tmp_path, storyboard, call_counts)

    monkeypatch.setattr(
        pipeline,
        "verify_segment_code",
        lambda *args, **kwargs: SimpleNamespace(
            segment_id=1,
            passed=True,
            issues=[],
            suggestions=[],
            static_issues=[],
            verification_tier="static",
            quality_risk="low",
            expensive_features=[],
        ),
    )

    def fake_critique(*args, **kwargs):
        call_counts["critique"] += 1
        return SimpleNamespace(passed=True, score=0.9, issues=[], suggestions=[], sub_scores={})

    monkeypatch.setattr(pipeline, "critique_video", fake_critique)

    updates = list(
        pipeline.run_segmented_pipeline(
            "demo",
            output_base=str(tmp_path),
            questionnaire_answers={"quality_mode": "balanced"},
        )
    )

    final = updates[-1]
    assert final["segment_quality"][1]["verification_tier"] == "static"
    assert final["segment_quality"][1]["critique_skipped"] is True
    assert call_counts["critique"] == 0


def test_high_risk_segment_runs_visual_critique(monkeypatch, tmp_path):
    call_counts = {"render": 0, "critique": 0}
    storyboard = _storyboard(render_risk="high")
    _install_common_fakes(monkeypatch, tmp_path, storyboard, call_counts)

    monkeypatch.setattr(
        pipeline,
        "verify_segment_code",
        lambda *args, **kwargs: SimpleNamespace(
            segment_id=1,
            passed=True,
            issues=[],
            suggestions=[],
            static_issues=[],
            verification_tier="llm",
            quality_risk="high",
            expensive_features=[],
        ),
    )

    def fake_critique(*args, **kwargs):
        call_counts["critique"] += 1
        return SimpleNamespace(passed=True, score=0.93, issues=[], suggestions=[], sub_scores={})

    monkeypatch.setattr(pipeline, "critique_video", fake_critique)

    updates = list(
        pipeline.run_segmented_pipeline(
            "demo",
            output_base=str(tmp_path),
            questionnaire_answers={"quality_mode": "balanced"},
        )
    )

    final = updates[-1]
    assert final["segment_quality"][1]["quality_risk"] == "high"
    assert final["segment_quality"][1]["critique_skipped"] is False
    assert call_counts["critique"] == 1


def test_resume_reuses_verify_and_critique_fingerprints(monkeypatch, tmp_path):
    call_counts = {"render": 0, "verify": 0, "critique": 0}
    storyboard = _storyboard(render_risk="high")
    _install_common_fakes(monkeypatch, tmp_path, storyboard, call_counts)

    def fake_verify(*args, **kwargs):
        call_counts["verify"] += 1
        return SimpleNamespace(
            segment_id=1,
            passed=True,
            issues=[],
            suggestions=[],
            static_issues=[],
            verification_tier="llm",
            quality_risk="high",
            expensive_features=[],
        )

    def fake_critique(*args, **kwargs):
        call_counts["critique"] += 1
        return SimpleNamespace(passed=True, score=0.95, issues=[], suggestions=[], sub_scores={})

    monkeypatch.setattr(pipeline, "verify_segment_code", fake_verify)
    monkeypatch.setattr(pipeline, "critique_video", fake_critique)

    first_updates = list(
        pipeline.run_segmented_pipeline(
            "demo",
            output_base=str(tmp_path),
            questionnaire_answers={"quality_mode": "balanced"},
        )
    )
    first_final = first_updates[-1]
    project_dir = first_final["project_dir"]
    assert call_counts["verify"] == 1
    assert call_counts["critique"] == 1

    state = load_project(project_dir)
    state["status"] = "in_progress"
    state["stages"].pop("concat", None)
    state["segments"]["1"]["code"]["done"] = False
    save_project(project_dir, state)

    second_updates = list(
        pipeline.run_segmented_pipeline(
            "demo",
            output_base=str(tmp_path),
            questionnaire_answers={"quality_mode": "balanced"},
        )
    )

    second_final = second_updates[-1]
    assert call_counts["verify"] == 1
    assert call_counts["critique"] == 1
    assert second_final["segment_quality"][1]["verification_tier"] == "llm"


def test_balanced_mode_skips_project_consistency_check(monkeypatch, tmp_path):
    call_counts = {"render": 0, "project_consistency": 0}
    storyboard = _storyboard(render_risk="low", num_segments=2)
    _install_common_fakes(monkeypatch, tmp_path, storyboard, call_counts)

    monkeypatch.setattr(
        pipeline,
        "verify_segment_code",
        lambda *args, **kwargs: SimpleNamespace(
            segment_id=1,
            passed=True,
            issues=[],
            suggestions=[],
            static_issues=[],
            verification_tier="static",
            quality_risk="low",
            expensive_features=[],
        ),
    )

    monkeypatch.setattr(
        pipeline,
        "critique_video",
        lambda *args, **kwargs: SimpleNamespace(passed=True, score=0.9, issues=[], suggestions=[], sub_scores={}),
    )

    def fake_project_consistency(*args, **kwargs):
        call_counts["project_consistency"] += 1
        return SimpleNamespace(passed=True, issues=[])

    monkeypatch.setattr(pipeline, "critique_project_consistency", fake_project_consistency)

    updates = list(
        pipeline.run_segmented_pipeline(
            "demo",
            output_base=str(tmp_path),
            questionnaire_answers={"quality_mode": "balanced"},
        )
    )

    assert call_counts["project_consistency"] == 0
    assert any(u.get("stage") == "verify" and u.get("skipped") for u in updates)


def test_polished_mode_runs_project_consistency_check(monkeypatch, tmp_path):
    call_counts = {"render": 0, "project_consistency": 0}
    storyboard = _storyboard(render_risk="low", num_segments=2)
    _install_common_fakes(monkeypatch, tmp_path, storyboard, call_counts)

    monkeypatch.setattr(
        pipeline,
        "verify_segment_code",
        lambda *args, **kwargs: SimpleNamespace(
            segment_id=1,
            passed=True,
            issues=[],
            suggestions=[],
            static_issues=[],
            verification_tier="static",
            quality_risk="low",
            expensive_features=[],
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "critique_video",
        lambda *args, **kwargs: SimpleNamespace(passed=True, score=0.9, issues=[], suggestions=[], sub_scores={}),
    )

    def fake_project_consistency(*args, **kwargs):
        call_counts["project_consistency"] += 1
        return SimpleNamespace(passed=True, issues=[])

    monkeypatch.setattr(pipeline, "critique_project_consistency", fake_project_consistency)

    list(
        pipeline.run_segmented_pipeline(
            "demo",
            output_base=str(tmp_path),
            questionnaire_answers={"quality_mode": "polished"},
        )
    )

    assert call_counts["project_consistency"] == 1


def test_high_risk_segments_are_started_first_when_concurrency_is_limited(monkeypatch, tmp_path):
    call_counts = {"render": 0}
    storyboard = _storyboard(render_risk=["low", "high", "medium"], num_segments=3)
    _install_common_fakes(monkeypatch, tmp_path, storyboard, call_counts)
    started: list[int] = []

    async def fake_tts_async(script, audio_path):
        os.makedirs(os.path.dirname(audio_path), exist_ok=True)
        with open(audio_path, "w", encoding="utf-8") as f:
            f.write("audio")
        return {"success": True, "audio_path": audio_path, "duration": 2.0}

    def fake_coder(*args, **kwargs):
        started.append(kwargs["segment_id"])
        output_dir = kwargs["output_dir"]
        os.makedirs(output_dir, exist_ok=True)
        video_path = os.path.join(output_dir, "preview.mp4")
        with open(video_path, "w", encoding="utf-8") as f:
            f.write("preview")
        yield {
            "status": "code ok",
            "phase": "done",
            "code": (
                "from manim import *\n"
                "class SegmentScene(Scene):\n"
                "    def construct(self):\n"
                "        self.wait(1.0)\n"
            ),
            "video_path": video_path,
            "code_validated": True,
            "final": True,
            "tool_call_counts": {},
            "token_usage": {},
        }

    monkeypatch.setattr(pipeline, "generate_voiceover_async", fake_tts_async)
    monkeypatch.setattr(pipeline, "run_coder_agent", fake_coder)
    monkeypatch.setattr(
        pipeline,
        "verify_segment_code",
        lambda *args, **kwargs: SimpleNamespace(
            segment_id=kwargs.get("segment_id", 1),
            passed=True,
            issues=[],
            suggestions=[],
            static_issues=[],
            verification_tier="static",
            quality_risk="low",
            expensive_features=[],
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "critique_video",
        lambda *args, **kwargs: SimpleNamespace(passed=True, score=0.9, issues=[], suggestions=[], sub_scores={}),
    )
    monkeypatch.setenv("PAPER2MANIM_SEGMENT_CONCURRENCY", "1")

    list(
        pipeline.run_segmented_pipeline(
            "demo",
            output_base=str(tmp_path),
            questionnaire_answers={"quality_mode": "balanced"},
        )
    )

    assert started[:3] == [2, 3, 1]
