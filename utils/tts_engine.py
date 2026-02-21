import base64
import os
import re
import subprocess
import tempfile
from typing import Optional, Tuple
from google import genai
from google.genai import types

def _looks_like_container_audio(audio_bytes: bytes) -> bool:
    if audio_bytes.startswith((b"RIFF", b"ID3", b"OggS", b"fLaC")):
        return True
    if len(audio_bytes) > 8 and audio_bytes[4:8] == b"ftyp":
        return True
    return False

def _parse_sample_rate(mime_type: Optional[str]) -> int:
    if not mime_type:
        return 24000
    match = re.search(r"rate=(\d+)", mime_type)
    return int(match.group(1)) if match else 24000

def _run_ffmpeg(cmd: list[str]) -> Tuple[bool, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except Exception as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, ""
    return False, result.stderr or result.stdout

def _is_valid_audio_file(path: str) -> bool:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except Exception:
        return False
    return result.returncode == 0 and "codec_type=audio" in result.stdout

def _normalize_to_wav(input_path: str, output_path: str) -> Tuple[bool, str]:
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-ac",
        "1",
        "-ar",
        "48000",
        "-c:a",
        "pcm_s16le",
        output_path,
    ]
    return _run_ffmpeg(cmd)

def _wrap_pcm_to_wav(input_path: str, output_path: str, sample_rate: int) -> Tuple[bool, str]:
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "s16le",
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        "-i",
        input_path,
        "-c:a",
        "pcm_s16le",
        output_path,
    ]
    return _run_ffmpeg(cmd)

def _extract_inline_audio(response) -> Tuple[Optional[bytes], Optional[str]]:
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            inline_data = getattr(part, "inline_data", None)
            if not inline_data:
                continue
            raw_data = getattr(inline_data, "data", None)
            if raw_data is None:
                continue
            if isinstance(raw_data, str):
                raw_data = base64.b64decode(raw_data)
            return raw_data, getattr(inline_data, "mime_type", None)
    return None, None

def generate_voiceover(text: str, output_path: str) -> dict:
    """
    Generates a voiceover from text using Gemini's audio capability.
    Assumes GEMINI_API_KEY is natively available in the environment.
    """
    try:
        client = genai.Client()

        response = client.models.generate_content(
            model="gemini-2.5-flash-preview-tts",
            contents=f"Please read the following text aloud in a clear, educational, and engaging tone, like a lecture: {text}",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name="Aoede"
                        )
                    )
                )
            )
        )

        audio_bytes, mime_type = _extract_inline_audio(response)
        if not audio_bytes:
            return {"success": False, "audio_path": None, "mime_type": None, "error": "No audio data found in Gemini response."}

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = os.path.join(temp_dir, "tts_audio_input.bin")
            with open(input_path, "wb") as f:
                f.write(audio_bytes)

            if mime_type and "audio/pcm" in mime_type.lower():
                success, error = _wrap_pcm_to_wav(input_path, output_path, _parse_sample_rate(mime_type))
                if not success:
                    return {"success": False, "audio_path": None, "mime_type": mime_type, "error": f"Failed to wrap PCM audio to WAV: {error}"}
            elif _looks_like_container_audio(audio_bytes):
                success, error = _normalize_to_wav(input_path, output_path)
                if not success:
                    return {"success": False, "audio_path": None, "mime_type": mime_type, "error": f"Failed to normalize container audio: {error}"}
            else:
                success, error = _wrap_pcm_to_wav(input_path, output_path, _parse_sample_rate(mime_type))
                if not success:
                    return {"success": False, "audio_path": None, "mime_type": mime_type, "error": f"Unknown audio format and PCM wrapping failed: {error}"}

        if not _is_valid_audio_file(output_path):
            return {"success": False, "audio_path": None, "mime_type": mime_type, "error": "Generated audio file is invalid after normalization."}

        return {"success": True, "audio_path": output_path, "mime_type": mime_type, "error": None}
    except Exception as exc:
        gemini_error = str(exc)
        try:
            from gtts import gTTS
            with tempfile.TemporaryDirectory() as temp_dir:
                fallback_mp3 = os.path.join(temp_dir, "fallback.mp3")
                tts = gTTS(text)
                tts.save(fallback_mp3)
                success, error = _normalize_to_wav(fallback_mp3, output_path)
                if not success:
                    return {"success": False, "audio_path": None, "mime_type": None, "error": f"Gemini TTS failed: {gemini_error}. gTTS fallback failed: {error}"}

            if not _is_valid_audio_file(output_path):
                return {"success": False, "audio_path": None, "mime_type": None, "error": f"Gemini TTS failed: {gemini_error}. gTTS fallback produced invalid audio."}

            return {"success": True, "audio_path": output_path, "mime_type": "audio/mpeg", "error": f"Gemini TTS failed, used gTTS fallback: {gemini_error}"}
        except Exception as fallback_exc:
            return {"success": False, "audio_path": None, "mime_type": None, "error": f"Gemini TTS failed: {gemini_error}. gTTS fallback unavailable/failed: {fallback_exc}"}
