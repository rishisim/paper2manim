"""Agentic Manim code generator with live documentation access and web search.

The model can call ``fetch_manim_docs``, ``fetch_manim_file``, ``search_web``
during generation to read real source code, docstrings, and community
examples — enabling higher-quality animations.
"""

from __future__ import annotations

import asyncio
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
from utils.web_search import search_web
from utils.manim_runner import run_manim_code, extract_class_name


# ── Model configuration ──────────────────────────────────────────────

MODEL_PRO = "gemini-3.1-pro-preview"          # complex segments
MODEL_FLASH = "gemini-flash-latest"            # simple segments (fast)

MAX_TOOL_CALLS = 3  # reduced from 10 to speed up execution and prevent infinite loops

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
- Use `search_web(query)` to find code examples, Python libraries, or community solutions when you need help with a specific animation technique or effect. This is especially useful for finding Manim plugins, mathematical visualization patterns, or code snippets from StackOverflow/GitHub.
- Output ONLY raw Python code.  No markdown fences, no prose.
- Import manim: `from manim import *`
- Define exactly one class inheriting from `Scene`, named `GeneratedScene`.
- **AESTHETICS & QUALITY:** 
  - Set the background to dark: `self.camera.background_color = "#141414"` (unless a different instruction overrides this).
  - Use the color palette and styling instructions provided in the prompt.
  - Use elegant and sophisticated animations: `TransformMatchingTex`, `TransformMatchingShapes`, `LaggedStart`, `AnimationGroup`, `FadeIn`. Avoid having elements just pop into existence.
  - Utilize rate functions like `rate_func=smooth` or `rate_func=there_and_back` to make movement feel organic.
- No external assets (SVGs, images, audio files). Everything must be generated via code.
- Avoid `MathTex`/`Tex` unless the visual instructions explicitly require LaTeX equations. If you do use them, look up their docs first.
- If you receive `FileNotFoundError` mentioning `tex_to_svg_file`, DO NOT stretch into tool searches to find out why! This is a known Manim quirk: it simply means YOUR LaTeX code failed to compile due to a syntax error. Fix your LaTeX string instead (e.g., check for missing `\\`, unescaped characters, or undefined commands like `\\mathrm`).
- Keep code deterministic — no randomness.
"""


def _get_model_for_complexity(complexity: str = "complex") -> str:
    """Return the appropriate model name based on segment complexity."""
    if complexity == "simple":
        return MODEL_FLASH
    return MODEL_PRO


def _build_config(complexity: str = "complex") -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        tools=[
            fetch_manim_docs,
            fetch_manim_file,
            fetch_golden_scenes,
            search_web,
        ],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0.2,
    )


def _dispatch_tool_call(fc) -> str:
    """Execute a single tool call and return the result string."""
    try:
        if fc.name == "fetch_manim_docs":
            return fetch_manim_docs(**fc.args)
        elif fc.name == "fetch_manim_file":
            return fetch_manim_file(**fc.args)
        elif fc.name == "fetch_golden_scenes":
            return fetch_golden_scenes()
        elif fc.name == "search_web":
            return search_web(**fc.args)
        else:
            return f"Unknown tool: {fc.name}"
    except Exception as e:
        return f"Error executing tool: {e}"


def _send_and_extract(
    chat,
    message: str,
    tool_call_counts: dict[str, int] | None = None,
) -> str:
    """Send a message through the chat (which handles tool calls
    automatically) and return the final text with code fences stripped."""
    calls = 0
    
    print(f"\n[Coder] Prompting model...")
    response = chat.send_message(message)
    
    while response.function_calls and calls < MAX_TOOL_CALLS:
        calls += 1
        tool_responses = []
        for fc in response.function_calls:
            print(f"  [Coder] Tool usage ({calls}/{MAX_TOOL_CALLS}): {fc.name}({fc.args})")
            if tool_call_counts is not None:
                tool_call_counts[fc.name] = tool_call_counts.get(fc.name, 0) + 1
            res = _dispatch_tool_call(fc)
                
            if calls >= MAX_TOOL_CALLS:
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

def generate_manim_script(
    instructions: str | dict,
    audio_script: str = "",
    audio_duration: float = 0.0,
    complexity: str = "complex",
    scene_class_name: str = "GeneratedScene",
    tool_call_counts: dict[str, int] | None = None,
    theme_name: str = "",
    color_palette: dict[str, str] | None = None,
) -> Iterator[str]:
    """Yield the final generated code (single yield after tool calls resolve)."""
    model = _get_model_for_complexity(complexity)
    client = genai.Client()
    chat = client.chats.create(model=model, config=_build_config(complexity))

    # Build the prompt dynamically based on whether it's Lite (str) or Pro (dict)
    if isinstance(instructions, str):
        prompt = (
            "Write a complete Manim script for the following visual instructions.\n"
            "Before writing any code, look up the documentation for the main "
            "classes and animations you plan to use.\n"
            "If you're unsure about a technique, use search_web() to find code examples.\n\n"
            f"The scene class MUST be named `{scene_class_name}`.\n\n"
            f"Instructions:\n{instructions}\n\n"
        )
    else:
        # Structured Pro segment
        seg = instructions
        
        # Merge theme and segment-specific colors
        palette_str = "No specific palette provided."
        if color_palette:
            palette_str = "\n".join([f"- {k}: {v}" for k, v in color_palette.items()])
            
        equations_str = "\n".join([f"- {eq}" for eq in seg.get('equations_latex', [])])
        vars_str = "\n".join([f"- {k}: {v}" for k, v in seg.get('variable_definitions', {}).items()])
        elements_str = "\n".join([f"- {el}" for el in seg.get('elements', [])])
        element_colors_str = "\n".join([f"- {k}: {v}" for k, v in seg.get('element_colors', {}).items()])
        animations_str = "\n".join([f"- {a}" for a in seg.get('animations', [])])
        
        prompt = (
            "Write a complete Manim script for the following highly structured scene specification.\n"
            "Before writing any code, look up the documentation for the main "
            "classes and animations you plan to use.\n"
            "If you're unsure about a technique, use search_web() to find code examples.\n\n"
            f"The scene class MUST be named `{scene_class_name}`.\n\n"
            f"### Visual Theme: {theme_name or 'Default'}\n"
            f"Global Color Palette:\n{palette_str}\n\n"
            f"### Mathematical Content (CRITICAL)\n"
            f"You MUST use THESE EXACT LaTeX strings using double backslashes (e.g. r\"$\\frac{{1}}{{2}}$\"):\n{equations_str}\n\n"
            f"Variable Meanings (for your understanding):\n{vars_str}\n\n"
            f"### Visual Layout & Elements\n"
            f"Layout Instructions: {seg.get('layout_instructions', '')}\n"
            f"Elements to draw:\n{elements_str}\n\n"
            f"Element Color Mapping:\n{element_colors_str}\n\n"
            f"### Visual & Animation Flow\n"
            f"Narrative Flow Instructions:\n{seg.get('visual_instructions', '')}\n\n"
            f"Required Animations:\n{animations_str}\n\n"
        )

    if audio_script and audio_duration > 0:
        duration_hint = ""
        if isinstance(instructions, dict) and instructions.get("duration_hint_seconds"):
            duration_hint = f"\nNote: The planner also suggested a minimum digest time of {instructions['duration_hint_seconds']} seconds for the visuals to breathe. Add `self.wait()` padding if necessary to allow math comprehension.\n"

        prompt += (
            f"CRITICAL TIMING MATCH: The generated voiceover for this segment is exactly {audio_duration:.1f} seconds long.\n"
            f"The narrator will say: \"{audio_script}\"\n"
            "You MUST time your animations (using `run_time` and `self.wait()`) so that the total scene duration perfectly matches or slightly exceeds the audio duration. "
            "Pace the visuals rhythmically to match the spoken sentences. DO NOT rush through the animations.\n"
            f"{duration_hint}"
        )

    yield "looking up docs"  # signal to caller

    code = _send_and_extract(chat, prompt, tool_call_counts=tool_call_counts)
    if not code:
        print(f"Falling back to tool-less code generation due to empty response (model={model}).")
        fallback_config = _build_config(complexity)
        fallback_config.tools = None
        fallback_config.automatic_function_calling = None
        
        fallback_chat = client.chats.create(model=model, config=fallback_config)
        code = _send_and_extract(fallback_chat, prompt, tool_call_counts=tool_call_counts)

    if code:
        yield code


def fix_manim_script(
    code: str,
    error: str,
    complexity: str = "complex",
    tool_call_counts: dict[str, int] | None = None,
) -> Iterator[str]:
    """Yield the corrected code after consulting docs."""
    model = _get_model_for_complexity(complexity)
    client = genai.Client()
    chat = client.chats.create(model=model, config=_build_config(complexity))

    compact = _compact_error(error)
    prompt = (
        "The following Manim script failed. Look up the relevant documentation "
        "for any classes or methods involved in the error, then return the "
        "corrected complete Python code.\n\n"
        f"Error:\n{compact}\n\n"
        f"Current code:\n{code}"
    )

    yield "looking up docs"

    fixed = _send_and_extract(chat, prompt, tool_call_counts=tool_call_counts)
    if fixed:
        yield fixed


# ── orchestrator ──────────────────────────────────────────────────────

def run_coder_agent(
    instructions: str | dict,
    max_retries: int = 3,
    audio_script: str = "",
    audio_duration: float = 0.0,
    complexity: str = "complex",
    scene_class_name: str = "GeneratedScene",
    output_dir: str | None = None,
    theme_name: str = "",
    color_palette: dict[str, str] | None = None,
):
    """Generate a Manim script, execute it, self-correct up to *max_retries*.

    Yields status dicts consumed by the CLI or Streamlit front-end.

    Args:
        complexity: "simple" or "complex" — controls which model is used.
        scene_class_name: The Manim Scene class name to generate.
        output_dir: Optional custom output directory for the rendered video.
    """
    model_label = _get_model_for_complexity(complexity)
    code = ""
    tool_call_counts: dict[str, int] = {}

    def _attach_tool_usage(payload: dict) -> dict:
        counts = dict(sorted(tool_call_counts.items()))
        payload["tool_call_counts"] = counts
        payload["total_tool_calls"] = sum(counts.values())
        return payload

    yield {"status": f"Generating Manim script [{complexity}] via {model_label}..."}
    for chunk in generate_manim_script(
        instructions, audio_script, audio_duration,
        complexity=complexity, scene_class_name=scene_class_name,
        tool_call_counts=tool_call_counts,
        theme_name=theme_name,
        color_palette=color_palette,
    ):
        if chunk == "looking up docs":
            yield {"status": "Looking up Manim documentation..."}
            continue
        code = chunk
        yield {"status": "Generating initial Manim script...", "code": code}

    if not code:
        yield _attach_tool_usage({
            "status": "Failed to generate the initial Manim script.",
            "error": "Empty model response.",
            "final": True,
        })
        return

    for attempt in range(max_retries + 1):
        class_name = extract_class_name(code)
        yield {"status": f"Attempt {attempt + 1}: Executing code (Fast render -ql)...", "code": code}

        result = run_manim_code(code, class_name, quality_flag="-ql", output_dir=output_dir)

        if result["success"]:
            yield _attach_tool_usage({
                "status": "Success! Low-res preview generated (-ql).",
                "video_path": result["video_path"],
                "code": code,
                "final": True,
            })
            return

        if attempt < max_retries:
            yield {
                "status": f"Execution failed. Self-correcting (attempt {attempt + 1})...",
                "error": result["error"],
            }
            updated_code = ""
            for chunk in fix_manim_script(
                code,
                result["error"],
                complexity=complexity,
                tool_call_counts=tool_call_counts,
            ):
                if chunk == "looking up docs":
                    yield {"status": f"Looking up docs for fix (attempt {attempt + 1})..."}
                    continue
                updated_code = chunk
                yield {
                    "status": f"Applying fix (attempt {attempt + 1})...",
                    "code": updated_code,
                }

            if not updated_code:
                yield _attach_tool_usage({
                    "status": "Failed to receive corrected code from model.",
                    "error": "Empty model response while self-correcting.",
                    "final": True,
                })
                return

            code = updated_code
        else:
            yield _attach_tool_usage({
                "status": "Failed to generate a working script after max retries.",
                "error": result["error"],
                "final": True,
            })
            return


# ── Async variant for parallel segment processing ────────────────────

async def run_coder_agent_async(
    instructions: str | dict,
    max_retries: int = 3,
    audio_script: str = "",
    audio_duration: float = 0.0,
    complexity: str = "complex",
    scene_class_name: str = "GeneratedScene",
    output_dir: str | None = None,
    theme_name: str = "",
    color_palette: dict[str, str] | None = None,
) -> dict:
    """Async wrapper around ``run_coder_agent``.

    Runs the synchronous generator in a thread-pool so multiple segments
    can be generated concurrently via ``asyncio.gather()``.

    Returns the final result dict (the one with ``"final": True``).
    """
    loop = asyncio.get_event_loop()

    def _run_sync() -> dict:
        last_update: dict = {}
        for update in run_coder_agent(
            instructions,
            max_retries=max_retries,
            audio_script=audio_script,
            audio_duration=audio_duration,
            complexity=complexity,
            scene_class_name=scene_class_name,
            output_dir=output_dir,
            theme_name=theme_name,
            color_palette=color_palette,
        ):
            last_update = update
        return last_update

    return await loop.run_in_executor(None, _run_sync)
