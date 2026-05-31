from __future__ import annotations

from types import SimpleNamespace

from utils import code_verifier


def test_verify_segment_code_flags_large_timing_mismatch(monkeypatch):
    monkeypatch.setattr(
        code_verifier,
        "run_text_completion",
        lambda **kwargs: SimpleNamespace(
            text='{"passed": true, "issues": [], "suggestions": []}'
        ),
    )
    monkeypatch.setattr(code_verifier, "resolve_stage_model", lambda *args, **kwargs: None)
    monkeypatch.setattr(code_verifier, "resolve_fallback_stage_model", lambda *args, **kwargs: None)

    code = (
        "from manim import *\n"
        "class Demo(Scene):\n"
        "    def construct(self):\n"
        "        self.play(Write(Text('Hello')), run_time=1.0)\n"
        "        self.wait(0.5)\n"
    )

    result = code_verifier.verify_segment_code(
        1,
        code,
        segment_context="timing demo",
        audio_duration=8.0,
    )

    assert result.passed is False
    assert any("Estimated scene timing" in issue for issue in result.issues)


def test_normalize_scene_timing_extends_final_wait():
    code = (
        "from manim import *\n"
        "class Demo(Scene):\n"
        "    def construct(self):\n"
        "        self.play(Write(Text('Hello')), run_time=1.0)\n"
        "        self.wait(0.5)\n"
    )

    normalized = code_verifier.normalize_scene_timing(code, 4.0)

    assert normalized.changed is True
    assert normalized.mode == "extend_final_wait"
    assert "self.wait(3.000)" in normalized.code
    assert abs((normalized.residual_delta or 0.0)) <= 0.75


def test_normalize_scene_timing_shrinks_waits_only():
    code = (
        "from manim import *\n"
        "class Demo(Scene):\n"
        "    def construct(self):\n"
        "        self.play(Write(Text('Hello')), run_time=1.0)\n"
        "        self.wait(2.0)\n"
        "        self.wait(2.0)\n"
    )

    normalized = code_verifier.normalize_scene_timing(code, 3.0)

    assert normalized.changed is True
    assert normalized.mode == "shrink_waits"
    assert "run_time=1.0" in normalized.code
    assert normalized.code.count("self.wait(1.000)") == 2
    assert abs((normalized.residual_delta or 0.0)) <= 0.75
