"""SRT subtitle generation from pipeline audio scripts and durations.

Generates per-segment and combined SRT files by splitting audio_script text
into sentences and distributing timing proportionally by word count.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Common abbreviations that should NOT trigger a sentence break.
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st",
    "vs", "etc", "inc", "ltd", "eg", "ie", "approx",
    "fig", "eq", "vol", "dept", "univ",
}


@dataclass
class SrtEntry:
    """A single subtitle cue."""
    index: int
    start: float  # seconds
    end: float    # seconds
    text: str


def format_srt_time(seconds: float) -> str:
    """Format a timestamp as ``HH:MM:SS,mmm`` for SRT files."""
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def split_into_sentences(text: str) -> list[str]:
    """Split *text* into sentences on ``.``, ``!``, and ``?`` boundaries.

    Handles common abbreviations and decimal numbers so that ``3.14`` or
    ``Dr. Smith`` do not produce spurious breaks.
    """
    if not text or not text.strip():
        return []

    # Split on sentence-ending punctuation followed by whitespace or end-of-string.
    # Negative lookbehind avoids splitting on single-letter abbreviations (e.g. "U.S.")
    # and decimal numbers (e.g. "3.14").
    raw_parts = re.split(r'(?<=[.!?])\s+', text.strip())

    # Re-join fragments that ended with a known abbreviation
    sentences: list[str] = []
    buf = ""
    for part in raw_parts:
        if buf:
            buf += " " + part
        else:
            buf = part

        # Check whether this fragment ends with an abbreviation (before the period)
        match = re.search(r'(\w+)\.$', buf)
        if match and match.group(1).lower() in _ABBREVIATIONS:
            continue  # keep buffering — this is an abbreviation, not end-of-sentence

        sentences.append(buf.strip())
        buf = ""

    if buf:
        sentences.append(buf.strip())

    return [s for s in sentences if s]


def generate_segment_srt(
    audio_script: str,
    duration: float,
    offset: float = 0.0,
    start_index: int = 1,
) -> list[SrtEntry]:
    """Generate SRT entries for a single segment.

    Timing is distributed proportionally by word count across sentences.
    """
    sentences = split_into_sentences(audio_script)
    if not sentences or duration <= 0:
        return []

    word_counts = [max(1, len(s.split())) for s in sentences]
    total_words = sum(word_counts)

    entries: list[SrtEntry] = []
    current_time = offset
    for i, (sentence, wc) in enumerate(zip(sentences, word_counts)):
        fraction = wc / total_words
        entry_duration = duration * fraction
        entries.append(SrtEntry(
            index=start_index + i,
            start=current_time,
            end=current_time + entry_duration,
            text=sentence,
        ))
        current_time += entry_duration

    return entries


def _probe_audio_duration(audio_path: str) -> float:
    """Get audio duration in seconds via ffprobe.  Returns 0.0 on failure."""
    if not audio_path or not os.path.isfile(audio_path):
        return 0.0
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
        logger.warning("ffprobe duration failed for %s: %s", audio_path, exc)
    return 0.0


def generate_combined_srt(
    segments: list[dict],
    tts_results: dict[int, dict],
) -> str:
    """Generate a complete SRT string for the full video.

    Iterates segments in order, computes cumulative timing offsets,
    and re-probes audio duration if the stored value is 0.0.
    """
    all_entries: list[SrtEntry] = []
    cumulative_offset = 0.0
    next_index = 1

    for seg in segments:
        seg_id = seg["id"]
        tts_r = tts_results.get(seg_id, {})
        if not tts_r.get("success"):
            continue

        duration = tts_r.get("duration") or 0.0
        if duration <= 0:
            duration = _probe_audio_duration(tts_r.get("audio_path", ""))
        if duration <= 0:
            continue

        audio_script = seg.get("audio_script", "")
        if not audio_script:
            cumulative_offset += duration
            continue

        entries = generate_segment_srt(
            audio_script, duration,
            offset=cumulative_offset,
            start_index=next_index,
        )
        all_entries.extend(entries)
        if entries:
            next_index = entries[-1].index + 1
        cumulative_offset += duration

    return _format_srt(all_entries)


def _format_srt(entries: list[SrtEntry]) -> str:
    """Format a list of SRT entries into a valid SRT string."""
    lines: list[str] = []
    for entry in entries:
        lines.append(str(entry.index))
        lines.append(f"{format_srt_time(entry.start)} --> {format_srt_time(entry.end)}")
        lines.append(entry.text)
        lines.append("")  # blank line separator
    return "\n".join(lines)


def write_srt(srt_content: str, output_path: str) -> None:
    """Write SRT content to a file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(srt_content)
