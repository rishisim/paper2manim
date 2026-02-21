import json
import re
from pydantic import BaseModel, Field, ValidationError
from google import genai

class Storyboard(BaseModel):
    visual_instructions: str = Field(min_length=1)
    audio_script: str = Field(min_length=1)

def _extract_json_text(raw_text: str) -> str:
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text

def plan_video_concept(concept: str, max_retries: int = 3) -> dict:
    """
    Takes a concept and generates a structured storyboard containing
    the visual instructions for Manim and the audio script for TTS.
    """
    client = genai.Client()

    base_prompt = f"""
You are an expert educational video planner, much like 3Blue1Brown.
The user wants to create a video about the following concept: "{concept}"

Please create a storyboard for a short 10-30 second introductory video.
Provide your response as a JSON object with two keys:
1. "visual_instructions": Very specific, step-by-step instructions for a Manim developer to animate this. Focus on basic shapes, text, equations, and simple animations (Create, Write, Transform). Do not invent extremely complex custom SVGs, keep it to standard Manim objects.
2. "audio_script": The words that the narrator will say. This should be engaging, clear, and perfectly match the pacing of the visuals.

Return ONLY the JSON. No markdown formatting.
"""
    prompt = base_prompt
    last_error = "unknown validation error"

    for _ in range(max_retries):
        response = client.models.generate_content(
            model="gemini-3.1-pro-preview",
            contents=prompt,
        )
        raw_text = response.text or ""
        text = _extract_json_text(raw_text)

        try:
            payload = json.loads(text)
            storyboard = Storyboard.model_validate(payload)
            return storyboard.model_dump()
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc)
            prompt = (
                f"{base_prompt}\n\n"
                "Your previous response was invalid JSON for this schema.\n"
                f"Validation/parsing error: {last_error}\n"
                "Return only a JSON object with string fields "
                '"visual_instructions" and "audio_script".'
            )

    raise RuntimeError(f"Failed to generate a valid storyboard after {max_retries} attempts: {last_error}")
