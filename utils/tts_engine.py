import os
import io
from google import genai
from google.genai import types

def generate_voiceover(text: str, output_path: str) -> bool:
    """
    Generates a voiceover from text using Gemini's audio capability.
    Assumes GEMINI_API_KEY is natively available in the environment.
    """
    try:
        client = genai.Client()
        
        response = client.models.generate_content(
            model='gemini-2.5-flash-preview-tts',
            contents=f"Please read the following text aloud in a clear, educational, and engaging tone, like a lecture: {text}",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name="Aoede"  # Aoede, Puck, Charon, Kore, Fenrir
                        )
                    )
                )
            )
        )
        
        # Audio is returned in inline_data
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                with open(output_path, "wb") as f:
                    f.write(part.inline_data.data)
                return True
                
        print("No audio data found in response.")
        return False
        
    except Exception as e:
        print(f"Error generating TTS: {e}")
        # Fallback to saving a silent audio file just so ffmpeg doesn't crash
        # or we could use edge_tts or simple gTTS
        try:
            from gtts import gTTS
            tts = gTTS(text)
            tts.save(output_path)
            return True
        except ImportError:
            pass
        return False
