from __future__ import annotations

from types import SimpleNamespace

from utils import visual_critique


def test_critique_video_fails_when_no_frames(monkeypatch):
    monkeypatch.setattr(visual_critique, "_extract_key_frames", lambda *args, **kwargs: [])
    result = visual_critique.critique_video("/tmp/missing.mp4")
    assert result.passed is False
    assert result.score == 0.0


def test_critique_video_uses_score_threshold_and_subscores(monkeypatch):
    monkeypatch.setattr(visual_critique, "_extract_key_frames", lambda *args, **kwargs: ["/tmp/f1.png"])
    monkeypatch.setattr(visual_critique, "_heuristic_frame_issues", lambda frames: ([], {"readability": 0.6}))
    monkeypatch.setattr(visual_critique, "_encode_image_base64", lambda path: "ZmFrZQ==")

    def fake_run_text_completion(**kwargs):
        return SimpleNamespace(
            text="""
            {
              "score": 0.68,
              "passed": true,
              "sub_scores": {
                "readability": 0.7,
                "clutter": 0.8,
                "content_coverage": 0.75,
                "end_frame_quality": 0.72
              },
              "issues": ["Minor spacing issue"],
              "suggestions": ["Add a slightly longer hold"]
            }
            """
        )

    monkeypatch.setattr(visual_critique, "run_text_completion", fake_run_text_completion)
    monkeypatch.setattr(visual_critique, "resolve_stage_model", lambda *args, **kwargs: SimpleNamespace(provider="openai", model="gpt", reasoning_effort="medium", cache_retention=None, cache_key_prefix="x"))
    monkeypatch.setattr(visual_critique, "resolve_fallback_stage_model", lambda *args, **kwargs: None)

    result = visual_critique.critique_video("/tmp/demo.mp4")
    assert result.passed is False
    assert result.sub_scores["end_frame_quality"] == 0.72
    assert "Minor spacing issue" in result.issues


def test_critique_video_hard_fails_on_heuristic_overload(monkeypatch):
    monkeypatch.setattr(visual_critique, "_extract_key_frames", lambda *args, **kwargs: ["/tmp/f1.png", "/tmp/f2.png"])
    monkeypatch.setattr(
        visual_critique,
        "_heuristic_frame_issues",
        lambda frames: (["Frames appear visually overloaded or cluttered."], {"readability": 0.4, "clutter": 0.1, "content_coverage": 0.8, "end_frame_quality": 0.6}),
    )
    result = visual_critique.critique_video("/tmp/demo.mp4")
    assert result.passed is False
    assert "overloaded" in result.issues[0].lower()
