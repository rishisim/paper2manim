"""Agentic Manim code generator with live documentation access.

The model can call ``fetch_manim_docs`` and ``fetch_manim_file`` during
generation to read real source code and docstrings straight from the
official Manim GitHub repository — no scraping, just raw text.
"""

from __future__ import annotations

import re
from typing import Iterator

from google import genai
from google.genai import types

from utils.manim_docs import (
    fetch_manim_docs,
    fetch_manim_file,
    get_topic_index_description,
)
from utils.golden_scenes import fetch_golden_scenes
from utils.manim_runner import run_manim_code, extract_class_name


MODEL_NAME = "gemini-3.1-pro-preview"

# ── helpers ───────────────────────────────────────────────────────────

_CODE_FENCE_RE = re.compile(r"```(?:python)?\s*\n?|```\s*$", re.MULTILINE)


def _strip_code_fences(text: str) -> str:
    """Extract code from within markdown fences, or strip the entire string."""
    text = text.strip()
    match = re.search(r"```(?:python)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    
    # Fallback to simple replace
    return text.replace("```python", "").replace("```", "").strip()


def _compact_error(error: str, max_lines: int = 80) -> str:
    lines = [line for line in (error or "").splitlines() if line.strip()]
    if not lines:
        return "No error output was captured."

    signal: list[str] = []
    for line in lines:
        low = line.lower()
        if any(kw in low for kw in ("traceback", "error", "exception", "line ", "file ")):
            signal.append(line)

    merged = signal[-max_lines:] if signal else lines[-max_lines:]
    return "\n".join(merged)


# ── model interaction (chat-based with automatic tool calling) ────────

TOPIC_INDEX_TEXT = get_topic_index_description()

SYSTEM_INSTRUCTION = f"""
You are an expert Manim animator. Your goal is to write a single,
complete Python file that generates a 3Blue1Brown-quality educational video scene.

Here is the Manim documentation topic index:
{TOPIC_INDEX_TEXT}

IMPORTANT RULES:
- Call `fetch_golden_scenes()` to get concrete examples of beautiful 3b1b-style animations. Model your approach on these examples.
- Look up documentation for at most 1 or 2 complex classes you are unsure about BEFORE writing the code. Do not do excessive lookups that will blow up the context window.
- Output ONLY raw Python code.  No markdown fences, no prose.
- Import manim: `from manim import *`
- Define exactly one class inheriting from `Scene`, named `GeneratedScene`.
- **AESTHETICS & QUALITY:** 
  - Set the background to dark: `self.camera.background_color = "#141414"`.
  - Use vibrant 3b1b-style accent colors (e.g., TEAL (`#5CD0B3`), YELLOW (`#E8C11C`), RED (`#FC6255`), BLUE (`#58C4DD`), GREEN (`#83C167`)).
  - Use elegant and sophisticated animations: `TransformMatchingTex`, `TransformMatchingShapes`, `LaggedStart`, `AnimationGroup`, `FadeIn(..., shift=UP)`. Avoid having elements just pop into existence.
  - Utilize rate functions like `rate_func=smooth` or `rate_func=there_and_back` to make movement feel organic.
- No external assets (SVGs, images, audio files). Everything must be generated via code.
- Avoid `MathTex`/`Tex` unless the visual instructions explicitly require LaTeX equations. If you do use them, look up their docs first.
- Keep code deterministic — no randomness.
"""


def _build_config() -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        tools=[
            fetch_manim_docs,
            fetch_manim_file,
            fetch_golden_scenes,
        ],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0.2,
    )


def _send_and_extract(chat, message: str) -> str:
    """Send a message through the chat (which handles tool calls
    automatically) and return the final text with code fences stripped."""
    MAX_CALLS = 5
    calls = 0
    
    print(f"\n[Coder] Prompting model...")
    response = chat.send_message(message)
    
    while response.function_calls and calls < MAX_CALLS:
        calls += 1
        tool_responses = []
        for fc in response.function_calls:
            print(f"  [Coder] Tool usage ({calls}/{MAX_CALLS}): {fc.name}({fc.args})")
            try:
                if fc.name == "fetch_manim_docs":
                    res = fetch_manim_docs(**fc.args)
                elif fc.name == "fetch_manim_file":
                    res = fetch_manim_file(**fc.args)
                elif fc.name == "fetch_golden_scenes":
                    res = fetch_golden_scenes()
                else:
                    res = f"Unknown tool: {fc.name}"
            except Exception as e:
                res = f"Error executing tool: {e}"
                
            if calls >= MAX_CALLS:
                res += "\n\nCRITICAL SYSTEM WARNING: You have exhausted all tool calls. Do NOT call any more functions. You MUST output the complete final Manim code NOW based on the information you have gathered."
                
            tool_responses.append(
                types.Part.from_function_response(name=fc.name, response={"result": res})
            )
            
        if not tool_responses:
            break
            
        response = chat.send_message(tool_responses)
        
    raw_text = response.text or ""
    
    if not raw_text and response.candidates and response.candidates[0].content.parts:
        print("\nDEBUG: Response has no text. Parts:")
        for part in response.candidates[0].content.parts:
            print("  ", part)
            
    return _strip_code_fences(raw_text)


# ── public generators ─────────────────────────────────────────────────

def generate_manim_script(instructions: str, audio_script: str = "", audio_duration: float = 0.0) -> Iterator[str]:
    """Yield the final generated code (single yield after tool calls resolve)."""
    client = genai.Client()
    chat = client.chats.create(model=MODEL_NAME, config=_build_config())

    prompt = (
        "Write a complete Manim script for the following visual instructions.\n"
        "Before writing any code, look up the documentation for the main "
        "classes and animations you plan to use.\n\n"
        f"Instructions:\n{instructions}\n\n"
    )
    if audio_script and audio_duration > 0:
        prompt += (
            f"CRITICAL TIMING MATCH: The generated voiceover for this segment is exactly {audio_duration:.1f} seconds long.\n"
            f"The narrator will say: \"{audio_script}\"\n"
            "You MUST time your animations (using `run_time` and `self.wait()`) so that the total scene duration perfectly matches the audio duration. "
            "Pace the visuals rhythmically to match the spoken sentences. DO NOT rush through the animations.\n"
        )

    yield "looking up docs"  # signal to caller

    code = _send_and_extract(chat, prompt)
    if not code:
        print("Falling back to tool-less code generation due to empty response.")
        fallback_config = _build_config()
        fallback_config.tools = None
        fallback_config.automatic_function_calling = None
        
        fallback_chat = client.chats.create(model=MODEL_NAME, config=fallback_config)
        code = _send_and_extract(fallback_chat, prompt)

    if code:
        yield code


def fix_manim_script(code: str, error: str) -> Iterator[str]:
    """Yield the corrected code after consulting docs."""
    client = genai.Client()
    chat = client.chats.create(model=MODEL_NAME, config=_build_config())

    compact = _compact_error(error)
    prompt = (
        "The following Manim script failed. Look up the relevant documentation "
        "for any classes or methods involved in the error, then return the "
        "corrected complete Python code.\n\n"
        f"Error:\n{compact}\n\n"
        f"Current code:\n{code}"
    )

    yield "looking up docs"

    fixed = _send_and_extract(chat, prompt)
    if fixed:
        yield fixed


# ── orchestrator ──────────────────────────────────────────────────────

def run_coder_agent(visual_instructions: str, max_retries: int = 3, audio_script: str = "", audio_duration: float = 0.0):
    """Generate a Manim script, execute it, self-correct up to *max_retries*.

    Yields status dicts consumed by the CLI or Streamlit front-end.
    """
    code = ""

    yield {"status": "Generating initial Manim script (consulting docs)..."}
    for chunk in generate_manim_script(visual_instructions, audio_script, audio_duration):
        if chunk == "looking up docs":
            yield {"status": "Looking up Manim documentation..."}
            continue
        code = chunk
        yield {"status": "Generating initial Manim script...", "code": code}

    if not code:
        yield {
            "status": "Failed to generate the initial Manim script.",
            "error": "Empty model response.",
            "final": True,
        }
        return

    for attempt in range(max_retries + 1):
        class_name = extract_class_name(code)
        yield {"status": f"Attempt {attempt + 1}: Executing code (Fast render -ql)...", "code": code}

        result = run_manim_code(code, class_name, quality_flag="-ql")

        if result["success"]:
            yield {"status": "Code successful! Rendering final HD video (-qh)...", "code": code}
            
            hd_result = run_manim_code(code, class_name, quality_flag="-qh", timeout_seconds=300)
            
            if hd_result["success"]:
                yield {
                    "status": "Success! HD Video generated.",
                    "video_path": hd_result["video_path"],
                    "code": code,
                    "final": True,
                }
            else:
                 yield {
                    "status": "HD Render failed, falling back to low-res video.",
                    "video_path": result["video_path"],
                    "error": hd_result["error"],
                    "code": code,
                    "final": True,
                }
                
            return

        if attempt < max_retries:
            yield {
                "status": f"Execution failed. Self-correcting (attempt {attempt + 1})...",
                "error": result["error"],
            }
            updated_code = ""
            for chunk in fix_manim_script(code, result["error"]):
                if chunk == "looking up docs":
                    yield {"status": f"Looking up docs for fix (attempt {attempt + 1})..."}
                    continue
                updated_code = chunk
                yield {
                    "status": f"Applying fix (attempt {attempt + 1})...",
                    "code": updated_code,
                }

            if not updated_code:
                yield {
                    "status": "Failed to receive corrected code from model.",
                    "error": "Empty model response while self-correcting.",
                    "final": True,
                }
                return

            code = updated_code
        else:
            yield {
                "status": "Failed to generate a working script after max retries.",
                "error": result["error"],
                "final": True,
            }
            return
