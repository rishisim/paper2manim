import json
import re
from typing import Iterator, Literal
from pydantic import BaseModel, Field, ValidationError
from google import genai


# ── Legacy single-segment model (still used for backward compat) ──────

class Storyboard(BaseModel):
    visual_instructions: str = Field(min_length=1)
    audio_script: str = Field(min_length=1)
    clarifying_questions: list[str] = Field(
        default_factory=list,
        description="Optional clarifying questions to ask the user if the topic is too broad or ambiguous."
    )


# ── New segmented storyboard models ──────────────────────────────────

class Segment(BaseModel):
    id: int = Field(ge=1)
    title: str = Field(min_length=1)
    visual_instructions: str = Field(min_length=1)
    audio_script: str = Field(min_length=1)
    complexity: Literal["simple", "complex"] = Field(
        default="complex",
        description=(
            "'simple' for intros, conclusions, basic text/diagrams. "
            "'complex' for mathematical proofs, intricate animations."
        ),
    )


class SegmentedStoryboard(BaseModel):
    segments: list[Segment] = Field(min_length=1)
    clarifying_questions: list[str] = Field(
        default_factory=list,
        description="Optional clarifying questions to ask the user if the topic is too broad or ambiguous."
    )


def _extract_json_text(raw_text: str) -> str:
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text


# ── Legacy single-segment planner (kept for backward compat) ─────────

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
Please create a storyboard for an educational mathematics/cs video.
Choose the duration that is best suited for the topic.
Provide your response as a JSON object with three keys:
1. "visual_instructions": Very specific, step-by-step instructions for a Manim developer to animate this. Focus on basic shapes, text, equations, and simple animations (Create, Write, Transform). Do not invent extremely complex custom SVGs, keep it to standard Manim objects.
2. "audio_script": The words that the narrator will say. This should be engaging, clear, and perfectly match the pacing of the visuals.
3. "clarifying_questions": (Optional) If the topic is very broad and you think there are multiple ways to approach it, ask up to 3 clarifying questions. If it's specific enough, provide an empty list.

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
                "Return only a JSON object with fields "
                '"visual_instructions", "audio_script", and "clarifying_questions".'
            )

    yield {"final": True, "error": f"Failed to generate a valid storyboard after {max_retries} attempts: {last_error}"}


# ── New segmented planner ─────────────────────────────────────────────

def plan_segmented_storyboard(
    concept: str,
    max_retries: int = 3,
    previous_storyboard: dict | None = None,
    feedback: str | None = None,
) -> Iterator[dict]:
    """Generate a multi-segment storyboard.

    Yields status dicts and finally ``{"final": True, "storyboard": {...}}``.
    The storyboard dict has ``segments`` (list) and ``clarifying_questions``.
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
Please create a **segmented** storyboard for an educational mathematics/cs video.
Break the video into logical segments of roughly 60-90 seconds each.
Each segment should be self-contained enough that a Manim developer can animate
it independently, yet they should flow naturally when played in order.

Provide your response as a JSON object with TWO keys:
1. "segments": A JSON array where each element has:
   - "id": An integer starting from 1.
   - "title": A short descriptive title for this segment (e.g. "Introduction", "Core Proof Step 1").
   - "visual_instructions": Very specific, step-by-step instructions for a Manim developer.
     Focus on basic shapes, text, equations, and simple animations (Create, Write, Transform).
     Do NOT invent extremely complex custom SVGs — keep it to standard Manim objects.
   - "audio_script": The words the narrator will say for this segment. Engaging, clear,
     and matching the pacing of the visuals.
   - "complexity": Either "simple" (intros, conclusions, basic diagrams/text) or "complex"
     (mathematical proofs, intricate multi-step animations, coordinate systems, graphs).

2. "clarifying_questions": (Optional) If the topic is very broad, ask up to 3 clarifying
   questions. Otherwise provide an empty list.

Return ONLY the JSON. No markdown formatting.
"""
    prompt = base_prompt
    last_error = "unknown validation error"

    for attempt in range(max_retries):
        if previous_storyboard and feedback:
            yield {"status": f"Refining segmented storyboard (Attempt {attempt + 1})..."}
        else:
            yield {"status": f"Drafting segmented storyboard (Attempt {attempt + 1})..."}

        response = client.models.generate_content(
            model="gemini-3.1-pro-preview",
            contents=prompt,
        )
        yield {"status": "Parsing generated content..."}
        raw_text = response.text or ""
        text = _extract_json_text(raw_text)

        try:
            yield {"status": "Validating segmented storyboard against schema..."}
            payload = json.loads(text)
            storyboard = SegmentedStoryboard.model_validate(payload)
            yield {"final": True, "storyboard": storyboard.model_dump()}
            return
        except (json.JSONDecodeError, ValidationError) as exc:
            yield {"status": f"Validation failed, preparing correction (Attempt {attempt + 1})..."}
            last_error = str(exc)
            prompt = (
                f"{base_prompt}\n\n"
                "Your previous response was invalid JSON for this schema.\n"
                f"Validation/parsing error: {last_error}\n"
                "Return only a JSON object with fields "
                '"segments" (array of objects) and "clarifying_questions" (array of strings).'
            )

    yield {"final": True, "error": f"Failed to generate a valid segmented storyboard after {max_retries} attempts: {last_error}"}
