import os
import subprocess

def stitch_video_and_audio(video_path: str, audio_path: str, output_path: str) -> dict:
    """
    Stitches an mp4 video and a wav/mp3 audio file together using ffmpeg.
    """
    # Ensure paths exist
    if not os.path.exists(video_path) or not os.path.exists(audio_path):
        return {
            "success": False,
            "output_path": None,
            "error": (
                "Missing input files for stitching. "
                f"Video exists={os.path.exists(video_path)}, "
                f"Audio exists={os.path.exists(audio_path)}"
            ),
            "command": None,
        }

    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        "-movflags", "+faststart",
        output_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return {"success": True, "output_path": output_path, "error": None, "command": " ".join(cmd)}
        return {
            "success": False,
            "output_path": None,
            "error": result.stderr or result.stdout,
            "command": " ".join(cmd),
        }
    except Exception as exc:
        return {"success": False, "output_path": None, "error": str(exc), "command": " ".join(cmd)}
