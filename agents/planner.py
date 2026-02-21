import json
import re
from pydantic import BaseModel
from google import genai

class Storyboard(BaseModel):
    visual_instructions: str
    audio_script: str

def plan_video_concept(concept: str) -> dict:
    """
    Takes a concept and generates a structured storyboard containing
    the visual instructions for Manim and the audio script for TTS.
    """
    client = genai.Client()
    
    prompt = f"""
You are an expert educational video planner, much like 3Blue1Brown.
The user wants to create a video about the following concept: "{concept}"

Please create a storyboard for a short 10-30 second introductory video.
Provide your response as a JSON object with two keys:
1. "visual_instructions": Very specific, step-by-step instructions for a Manim developer to animate this. Focus on basic shapes, text, equations, and simple animations (Create, Write, Transform). Do not invent extremely complex custom SVGs, keep it to standard Manim objects.
2. "audio_script": The words that the narrator will say. This should be engaging, clear, and perfectly match the pacing of the visuals.

Return ONLY the JSON. No markdown formatting.
"""

    response = client.models.generate_content(
        model='gemini-3.1-pro-preview',
        contents=prompt,
    )
    
    text = response.text.strip()
    # Strip markdown if present
    text = re.sub(r'^```json\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON storyboard: {e}\nRaw output: {text}")
        return {"visual_instructions": "Write the concept name on screen.", "audio_script": f"Let's learn about {concept}."}
