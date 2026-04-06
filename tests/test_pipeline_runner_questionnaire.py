import json
import sys

import pipeline_runner
from utils.project_state import create_project


def _make_project(tmp_path, concept="resume me"):
    project_dir = tmp_path / "resume_project"
    create_project(str(project_dir), concept=concept, concept_slug="resume_project", total_segments=1)
    return project_dir


def test_resume_skips_questionnaire(monkeypatch, tmp_path):
    project_dir = _make_project(tmp_path)
    emitted = []
    captured_kwargs = {}

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(pipeline_runner, "_emit", lambda msg: emitted.append(msg))

    def fail_read_stdin_line(timeout_seconds=30.0):
        raise AssertionError("Questionnaire should not be requested during resume")

    def fake_run_segmented_pipeline(**kwargs):
        captured_kwargs.update(kwargs)
        yield {
            "stage": "done",
            "status": "ok",
            "final": True,
            "video_path": str(project_dir / "resume_project.mp4"),
            "project_dir": str(project_dir),
        }

    monkeypatch.setattr(pipeline_runner, "_read_stdin_line", fail_read_stdin_line)
    monkeypatch.setattr("agents.pipeline.run_segmented_pipeline", fake_run_segmented_pipeline)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pipeline_runner.py",
            json.dumps(
                {
                    "concept": "ignored",
                    "resume_dir": str(project_dir),
                    "skip_audio": True,
                }
            ),
        ],
    )

    pipeline_runner.main()

    assert not any(msg.get("type") == "questions" for msg in emitted)
    assert captured_kwargs["questionnaire_answers"] == {
        "video_length": "Medium (3-5 min)",
        "target_audience": "Undergraduate",
        "visual_style": "Let the AI decide",
        "pacing": "Balanced",
        "quality_mode": "balanced",
        "narration_style": "standard",
    }


def test_force_restart_still_asks_questionnaire(monkeypatch, tmp_path):
    project_dir = _make_project(tmp_path, concept="restart me")
    emitted = []
    captured_kwargs = {}
    read_calls = {"count": 0}

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(pipeline_runner, "_emit", lambda msg: emitted.append(msg))

    def fake_read_stdin_line(timeout_seconds=30.0):
        read_calls["count"] += 1
        return json.dumps(
            {
                "type": "answers",
                "answers": {
                    "video_length": "Short (1-2 min)",
                    "target_audience": "General audience",
                    "visual_style": "Step-by-step derivation",
                    "pacing": "Fast and dense",
                    "quality_mode": "polished",
                    "narration_style": "intuitive",
                },
            }
        )

    def fake_run_segmented_pipeline(**kwargs):
        captured_kwargs.update(kwargs)
        yield {
            "stage": "done",
            "status": "ok",
            "final": True,
            "video_path": str(project_dir / "resume_project.mp4"),
            "project_dir": str(project_dir),
        }

    monkeypatch.setattr(pipeline_runner, "_read_stdin_line", fake_read_stdin_line)
    monkeypatch.setattr("agents.pipeline.run_segmented_pipeline", fake_run_segmented_pipeline)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pipeline_runner.py",
            json.dumps(
                {
                    "concept": "ignored",
                    "resume_dir": str(project_dir),
                    "force_restart": True,
                    "skip_audio": True,
                }
            ),
        ],
    )

    pipeline_runner.main()

    assert read_calls["count"] == 1
    assert any(msg.get("type") == "questions" for msg in emitted)
    assert captured_kwargs["questionnaire_answers"]["video_length"] == "Short (1-2 min)"
    assert captured_kwargs["questionnaire_answers"]["quality_mode"] == "polished"
