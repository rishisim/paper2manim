import asyncio
import time
from concurrent.futures import Future
from types import SimpleNamespace

import agents.pipeline as pipeline


def test_pro_pipeline_streams_code_progress(monkeypatch, tmp_path):
    def fake_planner(concept, max_retries=3, previous_storyboard=None, feedback=None):
        yield {"status": "planning"}
        yield {
            "final": True,
            "storyboard": {
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
                    for i in range(1, 10)
                ],
            },
        }

    async def fake_tts_async(script, audio_path):
        return {"success": True, "audio_path": audio_path, "duration": 9.0}

    def fake_coder(*args, **kwargs):
        scene = kwargs.get("scene_class_name", "SegmentX")
        yield {"status": f"{scene}: Generating initial Manim script...", "phase": "generate"}
        time.sleep(0.01)
        yield {"status": f"{scene}: Attempt 1: Executing code (Fast render -ql)...", "phase": "execute"}
        time.sleep(0.01)
        yield {
            "status": f"{scene}: Success",
            "phase": "done",
            "video_path": f"/tmp/{scene}.mp4",
            "final": True,
            "tool_call_counts": {},
        }

    def fake_concat(paths, final_output):
        import os
        os.makedirs(os.path.dirname(final_output) or ".", exist_ok=True)
        with open(final_output, "w") as f:
            f.write("fake")
        yield {"status": "concatenating"}
        yield {"final": True, "success": True, "output_path": final_output}

    def fake_stitch(video_path, audio_path, output_path):
        import os
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            f.write("fake")
        yield {"status": "stitching"}
        yield {"final": True, "success": True, "output_path": output_path}

    def fake_mux(video_path, srt_path, output_path):
        yield {"status": "muxing"}
        yield {"final": True, "success": True, "output_path": output_path}

    monkeypatch.setattr(pipeline, "run_math2manim_planner", fake_planner)
    monkeypatch.setattr(pipeline, "generate_voiceover_async", fake_tts_async)
    monkeypatch.setattr(pipeline, "run_coder_agent", fake_coder)
    monkeypatch.setattr(pipeline, "stitch_video_and_audio", fake_stitch)
    monkeypatch.setattr(pipeline, "concatenate_segments", fake_concat)
    monkeypatch.setattr(pipeline, "mux_subtitles", fake_mux)
    monkeypatch.setattr(pipeline, "critique_project_consistency", lambda *args, **kwargs: None)


    updates = list(
        pipeline.run_segmented_pipeline(
            "demo",
            output_base=str(tmp_path),
            is_lite=False,
        )
    )

    code_updates = [u for u in updates if u.get("stage") == "code" and u.get("segment_id")]
    intermediate = [u for u in code_updates if not u.get("segment_final")]
    updated_segments = {u["segment_id"] for u in intermediate}

    assert code_updates, "Expected per-segment code updates."
    assert intermediate, "Expected intermediate code updates before final completion."
    assert len(updated_segments) == 9, "Expected streamed intermediate updates for all 9 segments."
    assert updates[-1].get("final") is True


def test_pipeline_streams_worker_updates_before_segment_completion(monkeypatch, tmp_path):
    def fake_planner(concept, max_retries=3, previous_storyboard=None, feedback=None):
        yield {"status": "planning"}
        yield {
            "final": True,
            "storyboard": {
                "theme_name": "Test",
                "color_palette": {"primary": "#00AAFF"},
                "segments": [
                    {
                        "id": 1,
                        "audio_script": "audio 1",
                        "complexity": "complex",
                        "visual_instructions": "visual 1",
                        "equations_latex": [],
                        "variable_definitions": {},
                        "elements": [],
                        "element_colors": {},
                        "animations": [],
                        "layout_instructions": "",
                    }
                ],
            },
        }

    async def fake_tts_async(script, audio_path):
        await asyncio.sleep(0.3)
        return {"success": True, "audio_path": audio_path, "duration": 9.0}

    def fake_coder(*args, **kwargs):
        yield {"status": "Generating initial Manim script...", "phase": "generate"}
        time.sleep(0.3)
        yield {
            "status": "Success",
            "phase": "done",
            "video_path": "/tmp/Segment1.mp4",
            "final": True,
            "tool_call_counts": {},
        }

    def fake_stitch(video_path, audio_path, output_path):
        yield {"status": "stitching"}
        yield {"final": True, "success": True, "output_path": output_path}

    def fake_concat(paths, final_output):
        yield {"status": "concatenating"}
        yield {"final": True, "success": True, "output_path": final_output}

    def fake_mux(video_path, srt_path, output_path):
        yield {"status": "muxing"}
        yield {"final": True, "success": True, "output_path": output_path}

    monkeypatch.setattr(pipeline, "run_math2manim_planner", fake_planner)
    monkeypatch.setattr(pipeline, "generate_voiceover_async", fake_tts_async)
    monkeypatch.setattr(pipeline, "run_coder_agent", fake_coder)
    monkeypatch.setattr(pipeline, "stitch_video_and_audio", fake_stitch)
    monkeypatch.setattr(pipeline, "concatenate_segments", fake_concat)
    monkeypatch.setattr(pipeline, "mux_subtitles", fake_mux)
    monkeypatch.setattr(pipeline, "critique_project_consistency", lambda *args, **kwargs: None)

    gen = pipeline.run_segmented_pipeline("demo", output_base=str(tmp_path), is_lite=False)
    for _ in range(4):
        next(gen)

    start = time.perf_counter()
    update = next(gen)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.2, "Expected a worker heartbeat before the segment finished."
    assert update["stage"] == "tts"
    assert update["segment_id"] == 1
    assert "voiceover" in update["status"].lower()


def test_pipeline_starts_segment_work_before_planner_finalizes(monkeypatch, tmp_path):
    timestamps: dict[str, float] = {}

    segment_1 = {
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
    }
    segment_2 = {**segment_1, "id": 2, "title": "Two", "audio_script": "audio 2", "visual_instructions": "visual 2"}
    storyboard = {"theme_name": "Test", "color_palette": {"primary": "#00AAFF"}, "segments": [segment_1, segment_2]}

    def fake_planner(concept, max_retries=3, previous_storyboard=None, feedback=None, questionnaire_answers=None):
        yield {"status": "planning"}
        yield {
            "status": "segment 1 ready",
            "segment_storyboard": segment_1,
            "segment_id": 1,
            "num_segments": 2,
            "theme_name": "Test",
            "color_palette": {"primary": "#00AAFF"},
        }
        time.sleep(0.15)
        timestamps["planner_final"] = time.perf_counter()
        yield {"final": True, "storyboard": storyboard}

    async def fake_tts_async(script, audio_path):
        timestamps.setdefault("segment_1_tts", time.perf_counter())
        return {"success": True, "audio_path": audio_path, "duration": 4.0}

    def fake_coder(*args, **kwargs):
        scene = kwargs.get("scene_class_name", "SegmentX")
        yield {
            "status": f"{scene}: ok",
            "phase": "done",
            "code": f"from manim import *\nclass {scene}(Scene):\n    def construct(self):\n        self.wait(1)\n",
            "video_path": f"/tmp/{scene}.mp4",
            "code_validated": True,
            "final": True,
            "tool_call_counts": {},
            "token_usage": {},
        }

    def fake_submit_render_job(job):
        future: Future = Future()
        out = tmp_path / f"{job.segment_id}.mp4"
        out.write_text("video")
        future.set_result(type("RenderResult", (), {"success": True, "video_path": str(out), "error": None})())
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
    monkeypatch.setattr(pipeline, "verify_segment_code", lambda *args, **kwargs: SimpleNamespace(passed=True, issues=[], suggestions=[], static_issues=[], verification_tier="static", quality_risk="low", expensive_features=[]))
    monkeypatch.setattr(pipeline, "verify_code_transitions", lambda *args, **kwargs: [])
    monkeypatch.setattr(pipeline, "critique_project_consistency", lambda *args, **kwargs: None)

    updates = list(pipeline.run_segmented_pipeline("demo", output_base=str(tmp_path), is_lite=False))

    assert updates[-1]["final"] is True
    assert timestamps["segment_1_tts"] < timestamps["planner_final"]


def test_pipeline_summary_uses_wall_clock_total(tmp_path):
    summary_path = pipeline._save_pipeline_summary(
        [("Plan", "ok", 5.0), ("Parallel Pipeline", "ok", 4.0), ("Concat", "ok", 1.0)],
        str(tmp_path),
        concept="demo",
        total_elapsed_seconds=7.0,
    )

    with open(summary_path, "r", encoding="utf-8") as f:
        text = f.read()

    assert "Total" in text
    assert "7.0s" in text
