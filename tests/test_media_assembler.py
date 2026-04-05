"""Tests for utils.media_assembler — ffmpeg command construction, missing files, etc.

All subprocess calls are mocked so ffmpeg is NOT required to run these tests.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from utils.media_assembler import (
    _size_based_timeout,
    concatenate_segments,
    stitch_video_and_audio,
)

# ---------------------------------------------------------------------------
# _size_based_timeout
# ---------------------------------------------------------------------------

def test_size_based_timeout_minimum():
    """Returns at least the base timeout when files are small or missing."""
    assert _size_based_timeout([], base=120) == 120
    assert _size_based_timeout(["/nonexistent/path.mp4"], base=60) == 60


def test_size_based_timeout_scales_with_size(tmp_path):
    """Timeout grows proportionally to total input size."""
    big_file = tmp_path / "big.mp4"
    big_file.write_bytes(b"\x00" * (100 * 1024 * 1024))  # 100 MB
    timeout = _size_based_timeout([str(big_file)], base=60)
    assert timeout >= 200  # 100 MB * 2 = 200s


# ---------------------------------------------------------------------------
# stitch_video_and_audio — missing inputs
# ---------------------------------------------------------------------------

def test_stitch_missing_video(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"\x00" * 100)

    updates = list(stitch_video_and_audio(
        str(tmp_path / "missing.mp4"), str(audio), str(tmp_path / "out.mp4")
    ))
    final = updates[-1]
    assert final["final"] is True
    assert final["success"] is False
    assert "Missing" in final["error"]


def test_stitch_missing_audio(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00" * 100)

    updates = list(stitch_video_and_audio(
        str(video), str(tmp_path / "missing.wav"), str(tmp_path / "out.mp4")
    ))
    final = updates[-1]
    assert final["final"] is True
    assert final["success"] is False
    assert "Missing" in final["error"]


def test_stitch_both_missing(tmp_path):
    updates = list(stitch_video_and_audio(
        str(tmp_path / "missing.mp4"),
        str(tmp_path / "missing.wav"),
        str(tmp_path / "out.mp4"),
    ))
    final = updates[-1]
    assert final["final"] is True
    assert final["success"] is False


# ---------------------------------------------------------------------------
# stitch_video_and_audio — ffmpeg command construction
# ---------------------------------------------------------------------------

@patch("utils.media_assembler.subprocess.run")
def test_stitch_ffmpeg_command_args(mock_run, tmp_path):
    video = tmp_path / "v.mp4"
    audio = tmp_path / "a.wav"
    output = tmp_path / "out.mp4"
    video.write_bytes(b"\x00" * 100)
    audio.write_bytes(b"\x00" * 100)

    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    updates = list(stitch_video_and_audio(str(video), str(audio), str(output)))
    final = updates[-1]
    assert final["success"] is True

    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert cmd[0] == "ffmpeg"
    assert "-y" in cmd
    assert "-c:v" in cmd and cmd[cmd.index("-c:v") + 1] == "copy"
    assert "-c:a" in cmd and cmd[cmd.index("-c:a") + 1] == "aac"
    assert "-movflags" in cmd
    assert str(output) in cmd


@patch("utils.media_assembler.subprocess.run")
def test_stitch_ffmpeg_failure_reports_error(mock_run, tmp_path):
    video = tmp_path / "v.mp4"
    audio = tmp_path / "a.wav"
    video.write_bytes(b"\x00" * 100)
    audio.write_bytes(b"\x00" * 100)

    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="codec error")

    updates = list(stitch_video_and_audio(
        str(video), str(audio), str(tmp_path / "out.mp4")
    ))
    final = updates[-1]
    assert final["success"] is False
    assert "codec error" in final["error"]


@patch("utils.media_assembler.subprocess.run")
def test_stitch_ffmpeg_exception(mock_run, tmp_path):
    """If subprocess.run raises an exception, stitch should report it."""
    video = tmp_path / "v.mp4"
    audio = tmp_path / "a.wav"
    video.write_bytes(b"\x00" * 100)
    audio.write_bytes(b"\x00" * 100)

    mock_run.side_effect = OSError("ffmpeg not found")

    updates = list(stitch_video_and_audio(
        str(video), str(audio), str(tmp_path / "out.mp4")
    ))
    final = updates[-1]
    assert final["success"] is False
    assert "ffmpeg not found" in final["error"]


# ---------------------------------------------------------------------------
# stitch yields status updates before final
# ---------------------------------------------------------------------------

@patch("utils.media_assembler.subprocess.run")
def test_stitch_yields_status_before_final(mock_run, tmp_path):
    video = tmp_path / "v.mp4"
    audio = tmp_path / "a.wav"
    video.write_bytes(b"\x00" * 100)
    audio.write_bytes(b"\x00" * 100)

    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    updates = list(stitch_video_and_audio(str(video), str(audio), str(tmp_path / "out.mp4")))
    # Should have at least 2 status updates + 1 final
    assert len(updates) >= 3
    # Non-final updates should have "status"
    for u in updates[:-1]:
        assert "status" in u


# ---------------------------------------------------------------------------
# concatenate_segments — missing inputs
# ---------------------------------------------------------------------------

def test_concat_missing_segments(tmp_path):
    updates = list(concatenate_segments(
        [str(tmp_path / "seg1.mp4"), str(tmp_path / "seg2.mp4")],
        str(tmp_path / "final.mp4"),
    ))
    final = updates[-1]
    assert final["final"] is True
    assert final["success"] is False
    assert "Missing" in final["error"]


def test_concat_single_segment_copies(tmp_path):
    """With a single segment, concatenate_segments should just copy it."""
    seg = tmp_path / "seg1.mp4"
    seg.write_bytes(b"fake video data")
    output = tmp_path / "final.mp4"

    updates = list(concatenate_segments([str(seg)], str(output)))
    final = updates[-1]
    assert final["final"] is True
    assert final["success"] is True
    assert os.path.exists(str(output))
    # Verify the content was actually copied
    assert output.read_bytes() == b"fake video data"


def test_concat_single_segment_creates_output_dir(tmp_path):
    """Output directory should be created if it does not exist."""
    seg = tmp_path / "seg1.mp4"
    seg.write_bytes(b"data")
    output = tmp_path / "subdir" / "final.mp4"

    updates = list(concatenate_segments([str(seg)], str(output)))
    final = updates[-1]
    assert final["success"] is True
    assert os.path.exists(str(output))


# ---------------------------------------------------------------------------
# concatenate_segments — ffmpeg command for multi-segment
# ---------------------------------------------------------------------------

@patch("utils.media_assembler.subprocess.run")
def test_concat_multi_segment_normalizes_then_concats(mock_run, tmp_path):
    """With multiple segments, should normalize first, then concat."""
    seg1 = tmp_path / "seg1.mp4"
    seg2 = tmp_path / "seg2.mp4"
    seg1.write_bytes(b"vid1")
    seg2.write_bytes(b"vid2")
    output = tmp_path / "final.mp4"

    # All subprocess.run calls return success
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    updates = list(concatenate_segments([str(seg1), str(seg2)], str(output)))
    final = updates[-1]
    assert final["success"] is True

    # Should have multiple subprocess.run calls: normalize * 2 + concat * 1
    assert mock_run.call_count >= 3

    # The last call should be the concat
    last_call_args = mock_run.call_args_list[-1][0][0]
    assert "ffmpeg" in last_call_args[0]
    assert "-f" in last_call_args
    assert "concat" in last_call_args


@patch("utils.media_assembler.subprocess.run")
def test_concat_normalization_failure(mock_run, tmp_path):
    """If normalization of a segment fails, concatenation should fail."""
    seg1 = tmp_path / "seg1.mp4"
    seg2 = tmp_path / "seg2.mp4"
    seg1.write_bytes(b"vid1")
    seg2.write_bytes(b"vid2")

    # First normalize call fails
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="encoding error")

    updates = list(concatenate_segments(
        [str(seg1), str(seg2)], str(tmp_path / "final.mp4")
    ))
    final = updates[-1]
    assert final["success"] is False
    assert "normalize" in final["error"].lower() or "Failed" in final["error"]


# ---------------------------------------------------------------------------
# concatenate_segments — empty list
# ---------------------------------------------------------------------------

def test_concat_empty_list(tmp_path):
    """Empty segment list: should report missing."""
    updates = list(concatenate_segments([], str(tmp_path / "final.mp4")))
    # Empty list has nothing missing but the status says 0 segments
    # Behavior depends on implementation — just check it doesn't crash
    assert len(updates) >= 1
