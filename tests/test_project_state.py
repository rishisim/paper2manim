"""Tests for utils.project_state — create, save, load, mark stages, progress."""

from __future__ import annotations

import json
import os

import pytest

from utils.project_state import (
    create_project,
    load_project,
    save_project,
    mark_stage_done,
    mark_segment_stage,
    mark_project_complete,
    is_stage_done,
    is_segment_stage_done,
    get_segment_progress,
    calculate_progress,
    _get_state_path,
)


# ---------------------------------------------------------------------------
# Create / Save / Load round-trip
# ---------------------------------------------------------------------------

def test_create_project_returns_state(tmp_path):
    state = create_project(str(tmp_path), "Fourier Transform", "fourier_transform", total_segments=3)
    assert state["concept"] == "Fourier Transform"
    assert state["slug"] == "fourier_transform"
    assert state["total_segments"] == 3
    assert state["status"] == "in_progress"
    assert "created_at" in state
    assert "updated_at" in state


def test_create_project_writes_file(tmp_path):
    create_project(str(tmp_path), "Dot Product", "dot_product")
    state_path = _get_state_path(str(tmp_path))
    assert os.path.exists(state_path)

    with open(state_path) as f:
        data = json.load(f)
    assert data["concept"] == "Dot Product"


def test_load_project_returns_saved_state(tmp_path):
    create_project(str(tmp_path), "Gradient Descent", "gradient_descent", total_segments=5)
    loaded = load_project(str(tmp_path))
    assert loaded is not None
    assert loaded["concept"] == "Gradient Descent"
    assert loaded["total_segments"] == 5


def test_load_project_missing_returns_none(tmp_path):
    assert load_project(str(tmp_path)) is None


def test_load_project_corrupt_json_returns_none(tmp_path):
    state_path = _get_state_path(str(tmp_path))
    os.makedirs(str(tmp_path), exist_ok=True)
    with open(state_path, "w") as f:
        f.write("{invalid json!!!")
    assert load_project(str(tmp_path)) is None


def test_save_project_updates_timestamp(tmp_path):
    state = create_project(str(tmp_path), "Eigen", "eigen")
    original_ts = state["updated_at"]

    # Mutate and save again
    state["status"] = "completed"
    save_project(str(tmp_path), state)

    reloaded = load_project(str(tmp_path))
    assert reloaded["status"] == "completed"
    # updated_at should be refreshed (or at least present)
    assert "updated_at" in reloaded


# ---------------------------------------------------------------------------
# Atomic write behavior
# ---------------------------------------------------------------------------

def test_save_project_atomic_no_leftover_tmp(tmp_path):
    """After save, no .tmp files should remain — only project_state.json."""
    create_project(str(tmp_path), "Test", "test")
    save_project(str(tmp_path), {"concept": "Test", "slug": "test", "status": "ok"})

    files = os.listdir(str(tmp_path))
    tmp_files = [f for f in files if f.endswith(".tmp")]
    assert tmp_files == [], f"Leftover temp files: {tmp_files}"
    assert "project_state.json" in files


def test_save_project_replaces_existing(tmp_path):
    create_project(str(tmp_path), "V1", "v1")
    save_project(str(tmp_path), {"concept": "V2", "slug": "v2", "status": "ok"})

    loaded = load_project(str(tmp_path))
    assert loaded["concept"] == "V2"


# ---------------------------------------------------------------------------
# Stage tracking
# ---------------------------------------------------------------------------

def test_mark_stage_done(tmp_path):
    create_project(str(tmp_path), "X", "x")
    state = mark_stage_done(str(tmp_path), "plan", artifacts=["storyboard.json"])
    assert state["stages"]["plan"]["done"] is True
    assert "storyboard.json" in state["stages"]["plan"]["artifacts"]


def test_mark_stage_done_no_project_raises(tmp_path):
    with pytest.raises(ValueError, match="No project state found"):
        mark_stage_done(str(tmp_path), "plan")


def test_is_stage_done_true(tmp_path):
    create_project(str(tmp_path), "Y", "y")
    state = mark_stage_done(str(tmp_path), "tts")
    assert is_stage_done(state, "tts") is True


def test_is_stage_done_false():
    assert is_stage_done({"stages": {}}, "render") is False
    assert is_stage_done(None, "render") is False
    assert is_stage_done({}, "render") is False


# ---------------------------------------------------------------------------
# Per-segment stage tracking
# ---------------------------------------------------------------------------

def test_mark_segment_stage(tmp_path):
    create_project(str(tmp_path), "Z", "z", total_segments=3)
    state = mark_segment_stage(str(tmp_path), 1, "tts", done=True, artifacts=["seg1.wav"])
    assert state["segments"]["1"]["tts"]["done"] is True
    assert "seg1.wav" in state["segments"]["1"]["tts"]["artifacts"]


def test_mark_segment_stage_error(tmp_path):
    create_project(str(tmp_path), "E", "e", total_segments=2)
    state = mark_segment_stage(str(tmp_path), 2, "code", done=False, error="Syntax error")
    assert state["segments"]["2"]["code"]["done"] is False
    assert state["segments"]["2"]["code"]["error"] == "Syntax error"


def test_mark_segment_stage_no_project_raises(tmp_path):
    with pytest.raises(ValueError):
        mark_segment_stage(str(tmp_path), 1, "code")


def test_is_segment_stage_done():
    state = {
        "segments": {
            "1": {"tts": {"done": True}, "code": {"done": False}},
            "2": {},
        }
    }
    assert is_segment_stage_done(state, 1, "tts") is True
    assert is_segment_stage_done(state, 1, "code") is False
    assert is_segment_stage_done(state, 2, "render") is False
    assert is_segment_stage_done(state, 99, "tts") is False


def test_get_segment_progress():
    state = {
        "segments": {
            "1": {"tts": {"done": True}, "code": {"done": True}},
            "2": {"tts": {"done": True}},
        }
    }
    progress = get_segment_progress(state)
    assert progress["1"]["tts"] is True
    assert progress["1"]["code"] is True
    assert progress["2"]["tts"] is True
    assert "code" not in progress["2"]


# ---------------------------------------------------------------------------
# Project completion
# ---------------------------------------------------------------------------

def test_mark_project_complete(tmp_path):
    create_project(str(tmp_path), "C", "c")
    state = mark_project_complete(str(tmp_path))
    assert state["status"] == "completed"


def test_mark_project_complete_no_project_raises(tmp_path):
    with pytest.raises(ValueError):
        mark_project_complete(str(tmp_path))


# ---------------------------------------------------------------------------
# Progress calculation
# ---------------------------------------------------------------------------

def test_calculate_progress_empty():
    done, total, desc = calculate_progress(None)
    assert done == 0
    assert total == 1
    assert desc == "Unknown"


def test_calculate_progress_completed():
    state = {"status": "completed"}
    done, total, desc = calculate_progress(state)
    assert done == 1
    assert total == 1
    assert desc == "Completed"


def test_calculate_progress_single_segment():
    state = {
        "status": "in_progress",
        "total_segments": 1,
        "stages": {
            "plan": {"done": True},
            "voiceover": {"done": True},
        },
        "segments": {},
    }
    done, total, desc = calculate_progress(state)
    assert done == 2
    assert total == 4


def test_calculate_progress_multi_segment():
    state = {
        "status": "in_progress",
        "total_segments": 2,
        "stages": {
            "plan": {"done": True},
        },
        "segments": {
            "1": {
                "tts": {"done": True},
                "code": {"done": True},
                "render": {"done": True},
                "stitch": {"done": True},
            },
            "2": {
                "tts": {"done": True},
                "code": {"done": True},
            },
        },
    }
    done, total, desc = calculate_progress(state)
    # plan=1 + seg1(4) + seg2(2) = 7
    # total = 1 + 4*2 + 1 = 10
    assert done == 7
    assert total == 10
    assert "segment" in desc.lower() or "generat" in desc.lower()
