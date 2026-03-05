import json
import re
from typing import Iterator
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

def plan_video_concept(concept: str, max_retries: int = 3, previous_storyboard: dict | None = None, feedback: str | None = None) -> Iterator[dict]:
    """
    Takes a concept and generates a structured storyboard containing
    the visual instructions for Manim and the audio script for TTS.
    Yields status dictionaries and finally a dictionary with "final" and "storyboard".
    """
    client = genai.Client()

    base_prompt = f"""
You are an expert educational video planner, much like 3Blue1Brown.
The user wants to create a video about the following concept: "{concept}"
"""

    if previous_storyboard and feedback:
        base_prompt += f"""
Here is the previous storyboard you generated:
{json.dumps(previous_storyboard, indent=2)}

The user provided the following feedback to improve it:
"{feedback}"

Please revise the storyboard according to the feedback.
"""

    base_prompt += """
Please create a storyboard for a short 10-30 second introductory video.
Provide your response as a JSON object with two keys:
1. "visual_instructions": Very specific, step-by-step instructions for a Manim developer to animate this. Focus on basic shapes, text, equations, and simple animations (Create, Write, Transform). Do not invent extremely complex custom SVGs, keep it to standard Manim objects.
2. "audio_script": The words that the narrator will say. This should be engaging, clear, and perfectly match the pacing of the visuals.

Return ONLY the JSON. No markdown formatting.
"""
    prompt = base_prompt
    last_error = "unknown validation error"

    for attempt in range(max_retries):
        if previous_storyboard and feedback:
            yield {"status": f"Refining storyboard based on feedback (Attempt {attempt + 1})..."}
        else:
            yield {"status": f"Drafting storyboard (Attempt {attempt + 1})..."}

        response = client.models.generate_content(
            model="gemini-3.1-pro-preview",
            contents=prompt,
        )
        yield {"status": "Parsing generated content..."}
        raw_text = response.text or ""
        text = _extract_json_text(raw_text)

        try:
            yield {"status": "Validating JSON against strict schema..."}
            payload = json.loads(text)
            storyboard = Storyboard.model_validate(payload)
            yield {"final": True, "storyboard": storyboard.model_dump()}
            return
        except (json.JSONDecodeError, ValidationError) as exc:
            yield {"status": f"Validation failed, preparing correction (Attempt {attempt + 1})..."}
            last_error = str(exc)
            prompt = (
                f"{base_prompt}\n\n"
                "Your previous response was invalid JSON for this schema.\n"
                f"Validation/parsing error: {last_error}\n"
                "Return only a JSON object with string fields "
                '"visual_instructions" and "audio_script".'
            )

    yield {"final": True, "error": f"Failed to generate a valid storyboard after {max_retries} attempts: {last_error}"}
