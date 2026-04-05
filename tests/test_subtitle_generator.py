"""Tests for utils.subtitle_generator — SRT generation from audio scripts."""

from __future__ import annotations

from utils.subtitle_generator import (
    SrtEntry,
    format_srt_time,
    generate_combined_srt,
    generate_segment_srt,
    split_into_sentences,
)

# ---------------------------------------------------------------------------
# format_srt_time
# ---------------------------------------------------------------------------

def test_format_srt_time_zero():
    assert format_srt_time(0.0) == "00:00:00,000"


def test_format_srt_time_seconds():
    assert format_srt_time(5.5) == "00:00:05,500"


def test_format_srt_time_minutes():
    assert format_srt_time(65.123) == "00:01:05,123"


def test_format_srt_time_hours():
    assert format_srt_time(3661.5) == "01:01:01,500"


def test_format_srt_time_negative_clamped():
    assert format_srt_time(-1.0) == "00:00:00,000"


# ---------------------------------------------------------------------------
# split_into_sentences
# ---------------------------------------------------------------------------

def test_split_simple():
    result = split_into_sentences("Hello world. How are you? I'm fine!")
    assert result == ["Hello world.", "How are you?", "I'm fine!"]


def test_split_abbreviations():
    result = split_into_sentences("Dr. Smith went to the store. He bought milk.")
    assert result == ["Dr. Smith went to the store.", "He bought milk."]


def test_split_empty():
    assert split_into_sentences("") == []
    assert split_into_sentences("   ") == []


def test_split_single_sentence():
    result = split_into_sentences("Just one sentence here.")
    assert result == ["Just one sentence here."]


def test_split_no_trailing_period():
    result = split_into_sentences("First sentence. Second one without period")
    assert result == ["First sentence.", "Second one without period"]


def test_split_multiple_spaces():
    result = split_into_sentences("First.  Second.   Third.")
    assert result == ["First.", "Second.", "Third."]


def test_split_fig_abbreviation():
    result = split_into_sentences("See fig. 3 for details. The result is clear.")
    assert result == ["See fig. 3 for details.", "The result is clear."]


# ---------------------------------------------------------------------------
# generate_segment_srt
# ---------------------------------------------------------------------------

def test_segment_srt_basic():
    entries = generate_segment_srt("Hello world. Goodbye world.", duration=10.0)
    assert len(entries) == 2
    assert entries[0].index == 1
    assert entries[0].start == 0.0
    assert entries[0].text == "Hello world."
    assert entries[1].index == 2
    assert entries[1].text == "Goodbye world."
    # Total should cover full duration
    assert abs(entries[-1].end - 10.0) < 0.01


def test_segment_srt_with_offset():
    entries = generate_segment_srt("One sentence.", duration=5.0, offset=10.0)
    assert len(entries) == 1
    assert entries[0].start == 10.0
    assert entries[0].end == 15.0


def test_segment_srt_empty_script():
    assert generate_segment_srt("", duration=5.0) == []


def test_segment_srt_zero_duration():
    assert generate_segment_srt("Some text.", duration=0.0) == []


def test_segment_srt_proportional_timing():
    # "Short. A much longer sentence with more words."
    # word counts: 1 vs 7 → ratio 1:7
    entries = generate_segment_srt(
        "Short. A much longer sentence with more words.",
        duration=8.0,
    )
    assert len(entries) == 2
    # First entry should be ~1s (1/8 of 8s), second ~7s (7/8 of 8s)
    first_dur = entries[0].end - entries[0].start
    second_dur = entries[1].end - entries[1].start
    assert second_dur > first_dur


def test_segment_srt_start_index():
    entries = generate_segment_srt("A. B.", duration=4.0, start_index=5)
    assert entries[0].index == 5
    assert entries[1].index == 6


# ---------------------------------------------------------------------------
# generate_combined_srt
# ---------------------------------------------------------------------------

def test_combined_srt_two_segments():
    segments = [
        {"id": 1, "audio_script": "First segment here."},
        {"id": 2, "audio_script": "Second segment here."},
    ]
    tts_results = {
        1: {"success": True, "duration": 5.0, "audio_path": "/tmp/a.wav"},
        2: {"success": True, "duration": 5.0, "audio_path": "/tmp/b.wav"},
    }
    srt = generate_combined_srt(segments, tts_results)
    assert "First segment here." in srt
    assert "Second segment here." in srt
    # Second segment should start at offset 5.0
    assert "00:00:05" in srt


def test_combined_srt_skips_failed():
    segments = [
        {"id": 1, "audio_script": "Good."},
        {"id": 2, "audio_script": "Bad."},
    ]
    tts_results = {
        1: {"success": True, "duration": 3.0, "audio_path": "/tmp/a.wav"},
        2: {"success": False, "duration": 0.0, "audio_path": ""},
    }
    srt = generate_combined_srt(segments, tts_results)
    assert "Good." in srt
    assert "Bad." not in srt


def test_combined_srt_empty():
    assert generate_combined_srt([], {}).strip() == ""
