import time
from google import genai
from google.genai import types
from utils.manim_runner import run_manim_code, extract_class_name


def generate_manim_script(instructions: str) -> str:
    client = genai.Client()
    prompt = f"""
You are an expert Manim developer. Write a complete Python script using the Manim library to animate the following instructions.
Only output the raw Python code. Do not use markdown blocks.

Instructions:
{instructions}

Requirements:
- Import manim: `from manim import *`
- Define a single class inheriting from Scene.
- Use simple and robust Manim features (e.g., Text, MathTex, Circle, Square, Create, Transform).
- Keep animations simple to minimize rendering errors.
- End your construct method with a `self.wait(5)` so the final scene stays visible while the narrator finishes speaking.
- Use your Google Search tool to look up the latest Manim Community documentation (docs.manim.community) to ensure syntax is correct.
"""
    response = client.models.generate_content(
        model="gemini-3.1-pro-preview",
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[{"google_search": {}}],
        ),
    )
    text = response.text or ""
    code = text.replace("```python", "").replace("```", "").strip()
    return code


def fix_manim_script(code: str, error: str) -> str:
    client = genai.Client()
    prompt = f"""
The following Manim script failed to execute. Fix the error and return the corrected complete Python code.
Do not use markdown blocks, output only the raw code.
Use your Google Search tool to search the latest Manim Community error logs or documentation if you are unsure why it failed.

Error:
{error}

Current Code:
{code}
"""
    response = client.models.generate_content(
        model="gemini-3.1-pro-preview",
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[{"google_search": {}}],
        ),
    )
    text = response.text or ""
    return text.replace("```python", "").replace("```", "").strip()


def run_coder_agent(visual_instructions: str, max_retries: int = 3):
    """
    Generates a Manim script, tries to run it, and self-corrects up to max_retries.
    Yields status updates and finally returns the result dict.
    """
    yield {"status": "Generating initial Manim script..."}
    code = generate_manim_script(visual_instructions)

    for attempt in range(max_retries + 1):
        class_name = extract_class_name(code)
        yield {"status": f"Attempt {attempt + 1}: Executing code...", "code": code}

        result = run_manim_code(code, class_name)

        if result["success"]:
            yield {
                "status": "Success! Video generated.",
                "video_path": result["video_path"],
                "code": code,
                "final": True,
            }
            return

        if attempt < max_retries:
            yield {
                "status": f"Execution failed. Self-correcting (Attempt {attempt + 1})...",
                "error": result["error"],
            }
            code = fix_manim_script(code, result["error"])
        else:
            yield {
                "status": "Failed to generate a working script after max retries.",
                "error": result["error"],
                "final": True,
            }
            return
