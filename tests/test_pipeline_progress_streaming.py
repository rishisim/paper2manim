import time

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

    def fake_overlay(video_path, audio_path, output_path):
        import os
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            f.write("fake")
        yield {"status": "overlaying"}
        yield {"final": True, "success": True, "output_path": output_path}

    monkeypatch.setattr(pipeline, "run_math2manim_planner", fake_planner)
    monkeypatch.setattr(pipeline, "generate_voiceover_async", fake_tts_async)
    monkeypatch.setattr(pipeline, "run_coder_agent", fake_coder)
    monkeypatch.setattr(pipeline, "concatenate_segments", fake_concat)


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
