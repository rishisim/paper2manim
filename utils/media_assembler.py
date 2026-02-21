import os
import subprocess

def stitch_video_and_audio(video_path: str, audio_path: str, output_path: str) -> bool:
    """
    Stitches an mp4 video and a wav/mp3 audio file together using ffmpeg.
    """
    # Ensure paths exist
    if not os.path.exists(video_path) or not os.path.exists(audio_path):
        print(f"Error: Missing input files for stitching. Video: {os.path.exists(video_path)}, Audio: {os.path.exists(audio_path)}")
        return False
        
    cmd = [
        "ffmpeg",
        "-y", # Overwrite output file
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy", # Copy video stream without re-encoding
        "-c:a", "aac",  # Encode audio to aac
        "-shortest",    # Finish encoding when the shortest input stream ends
        output_path
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return True
        else:
            print(f"FFmpeg Error: {result.stderr}")
            return False
    except Exception as e:
        print(f"Failed to execute FFmpeg: {e}")
        return False
