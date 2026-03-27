import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterator


def stitch_video_and_audio(video_path: str, audio_path: str, output_path: str) -> Iterator[dict]:
    """
    Stitches an mp4 video and a wav/mp3 audio file together using ffmpeg.
    Yields status updates and finally a result dictionary.
    """
    # Ensure paths exist
    yield {"status": "Checking input files for stitching..."}
    if not os.path.exists(video_path) or not os.path.exists(audio_path):
        yield {
            "final": True,
            "success": False,
            "output_path": None,
            "error": (
                "Missing input files for stitching. "
                f"Video exists={os.path.exists(video_path)}, "
                f"Audio exists={os.path.exists(audio_path)}"
            ),
            "command": None,
        }
        return

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-i",
        audio_path,
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        output_path,
    ]

    yield {"status": "Executing ffmpeg command to stitch audio tracks..."}
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            yield {
                "final": True,
                "success": True,
                "output_path": output_path,
                "error": None,
                "command": " ".join(cmd),
            }
            return
        yield {
            "final": True,
            "success": False,
            "output_path": None,
            "error": result.stderr or result.stdout,
            "command": " ".join(cmd),
        }
    except Exception as exc:
        yield {
            "final": True,
            "success": False,
            "output_path": None,
            "error": str(exc),
            "command": " ".join(cmd),
        }


# ── Segment concatenation ────────────────────────────────────────────

def concatenate_segments(
    segment_video_paths: list[str],
    output_path: str,
) -> Iterator[dict]:
    """Concatenate multiple per-segment stitched videos into one final video.

    Uses ``ffmpeg -f concat`` (demuxer) which is a fast remux operation
    — no re-encoding is needed as long as all inputs share the same codec
    and resolution.

    Yields status dicts and finally ``{"final": True, ...}``.
    """
    yield {"status": f"Concatenating {len(segment_video_paths)} segments..."}

    # Validate inputs
    missing = [p for p in segment_video_paths if not os.path.exists(p)]
    if missing:
        yield {
            "final": True,
            "success": False,
            "output_path": None,
            "error": f"Missing segment videos: {missing}",
        }
        return

    if len(segment_video_paths) == 1:
        # Nothing to concatenate — just copy/rename
        import shutil
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        shutil.copy2(segment_video_paths[0], output_path)
        yield {
            "final": True,
            "success": True,
            "output_path": output_path,
            "error": None,
        }
        return

    try:
        # First, re-encode all segments to a consistent format to avoid
        # concat issues from different resolutions/codecs/frame-rates
        with tempfile.TemporaryDirectory() as temp_dir:
            # Normalize all segments in parallel
            def _normalize_one(args: tuple[int, str]) -> tuple[int, str, str | None]:
                i, vp = args
                norm_path = os.path.join(temp_dir, f"seg_{i:03d}.mp4")
                norm_cmd = [
                    "ffmpeg", "-y",
                    "-i", vp,
                    "-c:v", "libx264", "-preset", "fast",
                    "-c:a", "aac",
                    "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart",
                    norm_path,
                ]
                res = subprocess.run(norm_cmd, capture_output=True, text=True, timeout=180)
                if res.returncode != 0:
                    return (i, norm_path, res.stderr)
                return (i, norm_path, None)

            yield {"status": f"Normalizing {len(segment_video_paths)} segments in parallel..."}
            normalized_paths: list[str] = [""] * len(segment_video_paths)
            with ThreadPoolExecutor(max_workers=max(1, len(segment_video_paths))) as pool:
                futures = {pool.submit(_normalize_one, (i, vp)): i for i, vp in enumerate(segment_video_paths)}
                for fut in as_completed(futures):
                    i, norm_path, error = fut.result()
                    if error:
                        yield {
                            "final": True,
                            "success": False,
                            "output_path": None,
                            "error": f"Failed to normalize segment {i + 1}: {error}",
                        }
                        return
                    normalized_paths[i] = norm_path
                    yield {"status": f"Normalized segment {i + 1}/{len(segment_video_paths)}"}

            # Build the ffmpeg concat list file
            # Escape single quotes so paths like "O'Reilly" don't break ffmpeg concat.
            list_path = os.path.join(temp_dir, "concat_list.txt")
            with open(list_path, "w") as f:
                for p in normalized_paths:
                    escaped = p.replace("'", "'\\''")
                    f.write(f"file '{escaped}'\n")

            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", list_path,
                "-c", "copy",
                "-movflags", "+faststart",
                output_path,
            ]

            yield {"status": "Running ffmpeg concat..."}
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode == 0:
                yield {
                    "final": True,
                    "success": True,
                    "output_path": output_path,
                    "error": None,
                }
            else:
                yield {
                    "final": True,
                    "success": False,
                    "output_path": None,
                    "error": result.stderr or result.stdout,
                }
    except Exception as exc:
        yield {
            "final": True,
            "success": False,
            "output_path": None,
            "error": str(exc),
        }
