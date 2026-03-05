import os
import subprocess
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
        result = subprocess.run(cmd, capture_output=True, text=True)
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
