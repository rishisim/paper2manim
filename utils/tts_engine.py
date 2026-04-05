import asyncio
import base64
import os
import re
import subprocess
import tempfile
from typing import Optional, Tuple, Iterator
from google import genai
from google.genai import types

from agents.config import GEMINI_TTS

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

def _run_ffmpeg(cmd: list[str], timeout: int = 60) -> Tuple[bool, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"ffmpeg timed out after {timeout}s"
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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
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
    """Extract and concatenate ALL audio parts from the response.

    Gemini TTS can return multiple audio chunks/parts for longer text.
    Returning only the first chunk causes glitchy, truncated speech.
    """
    all_audio_bytes: list[bytes] = []
    mime_type: Optional[str] = None
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
            if mime_type is None:
                mime_type = getattr(inline_data, "mime_type", None)
            all_audio_bytes.append(raw_data)
    if not all_audio_bytes:
        return None, None
    return b"".join(all_audio_bytes), mime_type

def _get_audio_duration(path: str) -> Optional[float]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception:
        pass
    return None

def generate_voiceover(text: str, output_path: str) -> Iterator[dict]:
    """
    Generates a voiceover from text using Gemini's audio capability.
    Assumes GEMINI_API_KEY is natively available in the environment.
    """
    try:
        yield {"status": "Initializing Gemini TTS client..."}
        client = genai.Client()

        yield {"status": "Requesting audio generation from LLM..."}
        # L5: Allow model override via env var so callers aren't broken when the
        # preview model is promoted or renamed (e.g. gemini-2.5-flash-tts).
        tts_model = os.getenv("GEMINI_TTS_MODEL", GEMINI_TTS)
        response = client.models.generate_content(
            model=tts_model,
            contents=f"Speak in a calm, clear, and instructional tone. Maintain a steady, measured pace. Use a thoughtful and inquisitive intonation as if explaining a complex mathematical concept to a curious student. Read the following text: {text}",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name="Sadaltager"
                        )
                    )
                )
            )
        )

        yield {"status": "Extracting audio data from response..."}
        audio_bytes, mime_type = _extract_inline_audio(response)
        if not audio_bytes:
            yield {"final": True, "success": False, "audio_path": None, "mime_type": None, "error": "No audio data found in Gemini response."}
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = os.path.join(temp_dir, "tts_audio_input.bin")
            with open(input_path, "wb") as f:
                f.write(audio_bytes)

            yield {"status": f"Normalizing {mime_type or 'unknown'} audio format..."}
            if mime_type and "audio/pcm" in mime_type.lower():
                success, error = _wrap_pcm_to_wav(input_path, output_path, _parse_sample_rate(mime_type))
                if not success:
                    yield {"final": True, "success": False, "audio_path": None, "mime_type": mime_type, "error": f"Failed to wrap PCM audio to WAV: {error}"}
                    return
            elif _looks_like_container_audio(audio_bytes):
                success, error = _normalize_to_wav(input_path, output_path)
                if not success:
                    yield {"final": True, "success": False, "audio_path": None, "mime_type": mime_type, "error": f"Failed to normalize container audio: {error}"}
                    return
            else:
                success, error = _wrap_pcm_to_wav(input_path, output_path, _parse_sample_rate(mime_type))
                if not success:
                    yield {"final": True, "success": False, "audio_path": None, "mime_type": mime_type, "error": f"Unknown audio format and PCM wrapping failed: {error}"}
                    return

        yield {"status": "Validating finalized audio file..."}
        if not _is_valid_audio_file(output_path):
            yield {"final": True, "success": False, "audio_path": None, "mime_type": mime_type, "error": "Generated audio file is invalid after normalization."}
            return
            
        duration = _get_audio_duration(output_path)

        yield {"final": True, "success": True, "audio_path": output_path, "mime_type": mime_type, "duration": duration, "error": None}
    except Exception as exc:
        gemini_error = str(exc)
        yield {"status": "Gemini TTS failed, falling back to gTTS..."}
        try:
            from gtts import gTTS
            with tempfile.TemporaryDirectory() as temp_dir:
                fallback_mp3 = os.path.join(temp_dir, "fallback.mp3")
                tts = gTTS(text)
                yield {"status": "Generating fallback mp3..."}
                tts.save(fallback_mp3)
                yield {"status": "Normalizing fallback audio..."}
                success, error = _normalize_to_wav(fallback_mp3, output_path)
                if not success:
                    yield {"final": True, "success": False, "audio_path": None, "mime_type": None, "error": f"Gemini TTS failed: {gemini_error}. gTTS fallback failed: {error}"}
                    return

            if not _is_valid_audio_file(output_path):
                yield {"final": True, "success": False, "audio_path": None, "mime_type": None, "error": f"Gemini TTS failed: {gemini_error}. gTTS fallback produced invalid audio."}
                return

            duration = _get_audio_duration(output_path)
            yield {"final": True, "success": True, "audio_path": output_path, "mime_type": "audio/mpeg", "duration": duration, "error": f"Gemini TTS failed, used gTTS fallback: {gemini_error}"}
        except Exception as fallback_exc:
            yield {"final": True, "success": False, "audio_path": None, "mime_type": None, "error": f"Gemini TTS failed: {gemini_error}. gTTS fallback unavailable/failed: {fallback_exc}"}


# ── Async variant for parallel segment TTS ────────────────────────────

async def generate_voiceover_async(text: str, output_path: str) -> dict:
    """Async wrapper around ``generate_voiceover``.

    Runs the synchronous generator in a thread-pool so multiple segments'
    TTS can be generated concurrently via ``asyncio.gather()``.

    Returns the final result dict (the one with ``"final": True``).
    """
    loop = asyncio.get_running_loop()

    def _run_sync() -> dict:
        last: dict = {}
        for update in generate_voiceover(text, output_path):
            last = update
        return last

    return await loop.run_in_executor(None, _run_sync)
