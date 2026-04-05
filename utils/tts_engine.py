import asyncio
import base64
import logging
import os
import re
import subprocess
import tempfile
from typing import Iterator, Optional, Tuple

from google import genai
from google.genai import types

from agents.config import GEMINI_TTS

logger = logging.getLogger(__name__)

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
    except OSError as exc:
        logger.warning("ffmpeg process error: %s", exc)
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
    except subprocess.TimeoutExpired:
        logger.warning("ffprobe timed out validating audio file: %s", path)
        return False
    except OSError as e:
        logger.warning("ffprobe failed for %s: %s", path, e)
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
    except subprocess.TimeoutExpired:
        logger.warning("ffprobe timed out reading duration for: %s", path)
    except ValueError as e:
        logger.warning("Could not parse audio duration for %s: %s", path, e)
    except OSError as e:
        logger.warning("ffprobe failed for %s: %s", path, e)
    return None

def _gtts_fallback(text: str, output_path: str, original_error: str) -> dict:
    """Attempt gTTS fallback, return final result dict."""
    try:
        from gtts import gTTS
        with tempfile.TemporaryDirectory() as temp_dir:
            fallback_mp3 = os.path.join(temp_dir, "fallback.mp3")
            tts = gTTS(text)
            tts.save(fallback_mp3)
            success, error = _normalize_to_wav(fallback_mp3, output_path)
            if not success:
                return {"success": False, "audio_path": None, "mime_type": None, "duration": None, "error": f"Primary TTS failed: {original_error}. gTTS fallback failed: {error}"}
        if not _is_valid_audio_file(output_path):
            return {"success": False, "audio_path": None, "mime_type": None, "duration": None, "error": f"Primary TTS failed: {original_error}. gTTS fallback produced invalid audio."}
        duration = _get_audio_duration(output_path)
        return {"success": True, "audio_path": output_path, "mime_type": "audio/mpeg", "duration": duration, "error": f"Primary TTS failed, used gTTS fallback: {original_error}"}
    except Exception as fallback_exc:
        return {"success": False, "audio_path": None, "mime_type": None, "duration": None, "error": f"Primary TTS failed: {original_error}. gTTS fallback unavailable/failed: {fallback_exc}"}


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
            contents=f"Speak in a calm, clear, and instructional tone. Maintain a steady, measured pace. Use a thoughtful and inquisitive intonation as if explaining a complex mathematical concept to a curious student. When you encounter '......' (six dots), pause for about 1.5 seconds to mark a transition between video segments. Read the following text: {text}",
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


# ── Live API variant (WebSocket streaming) ───────────────────────────

async def generate_voiceover_live(text: str, output_path: str) -> dict:
    """Generate voiceover using Gemini Live API (WebSocket streaming).

    Returns the same result dict format as generate_voiceover's final yield.
    """
    try:
        client = genai.Client()
        live_model = os.getenv("GEMINI_TTS_LIVE_MODEL", "gemini-3.1-flash-live-preview")

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Sadaltager"
                    )
                )
            ),
        )

        audio_chunks: list[bytes] = []

        async with client.aio.live.connect(model=live_model, config=config) as session:
            prompt = (
                "Speak in a calm, clear, and instructional tone. "
                "Maintain a steady, measured pace. Use a thoughtful and "
                "inquisitive intonation as if explaining a complex mathematical "
                "concept to a curious student. When you encounter '......' (six dots), "
                "pause for about 1.5 seconds to mark a transition between video segments. "
                "Read the following text: " + text
            )
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=prompt)]),
                turn_complete=True,
            )

            async for message in session.receive():
                server_content = getattr(message, "server_content", None)
                if server_content is None:
                    continue
                model_turn = getattr(server_content, "model_turn", None)
                if model_turn is None:
                    if getattr(server_content, "turn_complete", False):
                        break
                    continue
                for part in getattr(model_turn, "parts", []) or []:
                    inline_data = getattr(part, "inline_data", None)
                    if inline_data and getattr(inline_data, "data", None):
                        audio_chunks.append(inline_data.data)

        if not audio_chunks:
            return _gtts_fallback(text, output_path, "No audio data received from Live API")

        pcm_data = b"".join(audio_chunks)

        with tempfile.TemporaryDirectory() as temp_dir:
            raw_path = os.path.join(temp_dir, "live_pcm.bin")
            with open(raw_path, "wb") as f:
                f.write(pcm_data)
            success, error = _wrap_pcm_to_wav(raw_path, output_path, 24000)
            if not success:
                return _gtts_fallback(text, output_path, f"PCM-to-WAV conversion failed: {error}")

        if not _is_valid_audio_file(output_path):
            return _gtts_fallback(text, output_path, "Live API audio invalid after conversion")

        duration = _get_audio_duration(output_path)
        return {"final": True, "success": True, "audio_path": output_path, "mime_type": "audio/pcm;rate=24000", "duration": duration, "error": None}

    except Exception as exc:
        return _gtts_fallback(text, output_path, f"Live API error: {exc}")


# ── Async entry point for parallel segment TTS ───────────────────────

async def generate_voiceover_async(text: str, output_path: str) -> dict:
    """Async TTS entry point for the pipeline.

    Routes to Live API or batch HTTP based on GEMINI_TTS_MODE env var.
    - "live"  -> generate_voiceover_live() (native async, WebSocket)
    - "batch" -> generate_voiceover() (sync generator in thread pool) [default]

    Returns the final result dict with keys: success, audio_path, duration, error.
    """
    mode = os.getenv("GEMINI_TTS_MODE", "batch").lower()

    if mode == "live":
        return await generate_voiceover_live(text, output_path)

    # Default: batch mode via thread pool (existing behavior)
    loop = asyncio.get_running_loop()

    def _run_sync() -> dict:
        last: dict = {}
        for update in generate_voiceover(text, output_path):
            last = update
        return last

    return await loop.run_in_executor(None, _run_sync)
