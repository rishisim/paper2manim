"""Agentic Manim code generator with live documentation access and web search.

The model can call ``fetch_manim_docs``, ``fetch_manim_file``, ``search_web``
during generation to read real source code, docstrings, and community
examples — enabling higher-quality animations.

Uses Claude Opus 4.6 (Anthropic) for code generation.
"""

from __future__ import annotations

import asyncio
import re
from typing import Iterator

import anthropic

from utils.manim_docs import (
    fetch_manim_docs,
    fetch_manim_file,
    get_topic_index_description,
)
from utils.golden_scenes import fetch_golden_scenes
from utils.web_search import search_web
from utils.manim_runner import run_manim_code, extract_class_name

import logging
_log = logging.getLogger(__name__)


# ── Model configuration ──────────────────────────────────────────────

MODEL_PRO = "claude-opus-4-6"              # complex segments
MODEL_FAST = "claude-sonnet-4-6"           # simple segments (fast)

MAX_TOOL_CALLS_COMPLEX = 1
MAX_TOOL_CALLS_SIMPLE = 0

# During self-correction, allow more tool calls so the model can look up docs/examples
MAX_TOOL_CALLS_FIX_COMPLEX = 3
MAX_TOOL_CALLS_FIX_SIMPLE = 1

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


# ── model interaction (Anthropic Messages API with tool calling) ─────

TOPIC_INDEX_TEXT = get_topic_index_description()

EMBEDDED_GOLDEN_SNIPPETS = """
Golden snippet A (fluid equation morph):
eq1 = MathTex("a^2", "+", "b^2", "=", "c^2")
eq2 = MathTex("a^2", "=", "c^2", "-", "b^2")
self.play(TransformMatchingTex(eq1, eq2), run_time=1.5)

Golden snippet B (staggered elegant intro):
self.play(
    LaggedStart(
        Create(plane),
        GrowArrow(v1),
        GrowArrow(v2),
        lag_ratio=0.35,
    ),
    run_time=2.4,
)

Golden snippet C (controlled dynamic updater):
t = ValueTracker(0)
curve = always_redraw(lambda: FunctionGraph(lambda x: np.sin(x + t.get_value()), x_range=[-3, 3]))
self.play(t.animate.set_value(PI), run_time=2.0, rate_func=smooth)

Golden snippet D (3D surface with camera rotation):
axes = ThreeDAxes(x_range=[-3, 3], y_range=[-3, 3], z_range=[-2, 2])
surface = Surface(
    lambda u, v: axes.c2p(u, v, np.sin(u) * np.cos(v)),
    u_range=[-3, 3], v_range=[-3, 3],
    resolution=(32, 32),
    fill_opacity=0.7,
)
surface.set_style(fill_color=[BLUE, GREEN], fill_opacity=0.7)
self.set_camera_orientation(phi=75 * DEGREES, theta=-45 * DEGREES)
self.play(Create(axes), Create(surface), run_time=3.0)
self.begin_ambient_camera_rotation(rate=0.15)
self.wait(4)

Golden snippet E (axes with plotted function and labels):
axes = Axes(
    x_range=[-1, 5, 1], y_range=[-1, 6, 1],
    x_length=6, y_length=5,
    axis_config={"include_numbers": True, "color": WHITE},
)
graph = axes.plot(lambda x: 0.25 * x**2, x_range=[0, 4.5], color=YELLOW)
label = axes.get_graph_label(graph, label="f(x) = \\frac{1}{4}x^2", x_val=3, direction=UP + LEFT)
area = axes.get_area(graph, x_range=[1, 4], color=[BLUE, GREEN], opacity=0.5)
self.play(Create(axes), run_time=1.5)
self.play(Create(graph), Write(label), run_time=2.0)
self.play(FadeIn(area), run_time=1.5)

Golden snippet F (text-heavy explanation with sequential reveals):
title = Text("Key Insight", font_size=42, color=YELLOW).to_edge(UP)
bullet1 = Text("• First, we define the domain", font_size=28).next_to(title, DOWN, buff=0.8).align_to(title, LEFT)
bullet2 = Text("• Then, apply the transformation", font_size=28).next_to(bullet1, DOWN, buff=0.4).align_to(bullet1, LEFT)
bullet3 = Text("• Finally, observe the invariant", font_size=28).next_to(bullet2, DOWN, buff=0.4).align_to(bullet2, LEFT)
self.play(Write(title), run_time=1.0)
self.wait(0.5)
self.play(FadeIn(bullet1, shift=RIGHT * 0.3), run_time=0.8)
self.wait(1.0)
self.play(FadeIn(bullet2, shift=RIGHT * 0.3), run_time=0.8)
self.wait(1.0)
self.play(FadeIn(bullet3, shift=RIGHT * 0.3), run_time=0.8)
self.wait(1.5)
"""

SYSTEM_INSTRUCTION = f"""You are an expert Manim animator and mathematical educator. Your goal is to write a single,
complete Python file that generates a 3Blue1Brown-quality educational video scene.

Here is the Manim documentation topic index:
{TOPIC_INDEX_TEXT}

== OUTPUT FORMAT ==
- Output ONLY raw Python code. No markdown fences, no prose, no explanations.
- Import manim: `from manim import *`
- Define exactly one class inheriting from `Scene` (or `ThreeDScene` for 3D content).
- No external assets (SVGs, images, audio files). Everything must be generated via code.
- Keep code deterministic — no randomness.

== AESTHETICS & QUALITY (3Blue1Brown Standard) ==
- Background: Always set `self.camera.background_color = "#141414"` in the first line of construct() unless overridden.
- Color palette: Use the colors provided in the prompt. Default to rich, saturated colors: BLUE, YELLOW, GREEN, RED, TEAL, GOLD, MAROON.
- Font sizing: Titles 42-48pt, body text 28-32pt, labels 22-26pt. Use consistent sizing throughout.
- Never have objects just appear. ALWAYS use elegant animations:
  * `Write()` for text and equations
  * `Create()` for geometric shapes
  * `GrowArrow()` for arrows and vectors
  * `FadeIn(obj, shift=direction)` for bullets and supporting elements
  * `TransformMatchingTex()` for equation morphs
  * `LaggedStart(..., lag_ratio=0.3)` for staggered group intros
  * `AnimationGroup()` for synchronized parallel animations
- Every `self.play()` MUST have an explicit `run_time` parameter.
- After every animation, add `self.wait()` for breathing room (0.5-2.0 seconds depending on complexity).
- Use `rate_func=smooth` for most movements, `rate_func=there_and_back` for demonstrations.
- Layout: Use `.to_edge()`, `.to_corner()`, `.next_to()`, `.shift()` for positioning. NEVER hardcode pixel coordinates.
- Clean up: `FadeOut()` elements that are no longer needed before introducing new ones. Avoid cluttered scenes.

== LATEX BEST PRACTICES ==
- Always use raw strings for MathTex: `MathTex(r"\\frac{{a}}{{b}}")`
- Use double backslashes in ALL LaTeX commands: `\\frac`, `\\int`, `\\sum`, `\\vec`, etc.
- Split equations into substrings for TransformMatchingTex: `MathTex("a^2", "+", "b^2", "=", "c^2")`
- If you get `FileNotFoundError` mentioning `tex_to_svg_file`, this means YOUR LaTeX string has a syntax error. Fix the LaTeX, do not search for files.
- Avoid `\\mathrm` — use `\\text` instead if needed.

== TIMING & PACING ==
- Match animation timing to audio duration when provided.
- Pace visuals rhythmically: introduce concept → pause → animate → pause → transition.
- Use `self.wait()` generously. Better to have breathing room than a rushed scene.
- A good rule: 2-3 seconds per equation, 1-2 seconds per geometric construction, 0.5-1s pauses between beats.

== TOOL USAGE ==
- Prefer writing code directly using your built-in Manim knowledge.
- ONLY call tools if you genuinely cannot recall the correct API.
- If you can write valid code without tools, do not call any tool.

Embedded style snippets you can reuse directly:
{EMBEDDED_GOLDEN_SNIPPETS}"""


def _get_model_for_complexity(complexity: str = "complex") -> str:
    """Return the appropriate model name based on segment complexity."""
    if complexity == "simple":
        return MODEL_FAST
    return MODEL_PRO


def _build_tools() -> list[dict]:
    """Return Anthropic tool definitions for the coder agent."""
    return [
        {
            "name": "fetch_manim_docs",
            "description": (
                "Retrieve Manim source documentation for a topic. "
                "Pass a keyword like 'circle', 'transform', 'axes', 'scene', etc."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "A keyword identifying the Manim concept to look up.",
                    }
                },
                "required": ["topic"],
            },
        },
        {
            "name": "fetch_manim_file",
            "description": (
                "Retrieve any file from the Manim GitHub repository by its path. "
                "E.g. 'manim/animation/creation.py'."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path relative to the Manim repo root.",
                    }
                },
                "required": ["file_path"],
            },
        },
        {
            "name": "fetch_golden_scenes",
            "description": "Returns high-quality golden reference Manim scenes for inspiration. Takes no arguments.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "search_web",
            "description": (
                "Search the web for Manim code examples, Python libraries, or animation techniques. "
                "Be specific, e.g. 'manim 3D surface plot example'."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A search query describing what you're looking for.",
                    }
                },
                "required": ["query"],
            },
        },
    ]


def _dispatch_tool_call(name: str, input_args: dict) -> str:
    """Execute a single tool call and return the result string."""
    try:
        if name == "fetch_manim_docs":
            return fetch_manim_docs(**input_args)
        elif name == "fetch_manim_file":
            return fetch_manim_file(**input_args)
        elif name == "fetch_golden_scenes":
            return fetch_golden_scenes()
        elif name == "search_web":
            return search_web(**input_args)
        else:
            return f"Unknown tool: {name}"
    except Exception as e:
        return f"Error executing tool: {e}"


def _send_and_extract(
    client: anthropic.Anthropic,
    model: str,
    system: str,
    user_message: str,
    max_tool_calls: int,
    tool_call_counts: dict[str, int] | None = None,
) -> str:
    """Send a message via Anthropic Messages API, handle tool calls,
    and return the final text with code fences stripped."""
    messages: list[dict] = [{"role": "user", "content": user_message}]
    tools = _build_tools() if max_tool_calls > 0 else []
    calls = 0

    _log.debug("prompting model (%s)…", model)

    while True:
        kwargs: dict = {
            "model": model,
            "max_tokens": 16384,
            "temperature": 0.2,
            "system": system,
            "messages": messages,
        }
        if tools and calls < max_tool_calls:
            kwargs["tools"] = tools

        response = client.messages.create(**kwargs)

        # Extract text blocks and tool use blocks
        text_parts: list[str] = []
        tool_use_blocks: list = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_use_blocks.append(block)

        # If no tool calls or budget exhausted, return the text
        if response.stop_reason != "tool_use" or not tool_use_blocks or calls >= max_tool_calls:
            raw_text = "\n".join(text_parts)
            return _strip_code_fences(raw_text)

        # Process tool calls
        # Append assistant message to history
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in tool_use_blocks:
            calls += 1
            _log.debug("tool call %d/%d  %s  %s", calls, max_tool_calls, block.name, block.input)
            if tool_call_counts is not None:
                tool_call_counts[block.name] = tool_call_counts.get(block.name, 0) + 1

            result = _dispatch_tool_call(block.name, block.input)

            if calls >= max_tool_calls:
                result += (
                    "\n\nCRITICAL SYSTEM WARNING: You have exhausted all tool calls. "
                    "Do NOT call any more functions. You MUST output the complete final "
                    "Manim code NOW based on the information you have gathered."
                )

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})


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
    max_tool_calls = MAX_TOOL_CALLS_SIMPLE if complexity == "simple" else MAX_TOOL_CALLS_COMPLEX
    client = anthropic.Anthropic()

    system = SYSTEM_INSTRUCTION + f"\n\nHard tool budget for this segment: {max_tool_calls} total function calls."

    # Build the prompt dynamically based on whether it's Lite (str) or Pro (dict)
    if isinstance(instructions, str):
        prompt = (
            "Write a complete Manim script for the following visual instructions.\n"
            "Prefer writing code immediately using core Manim primitives.\n"
            "Only use docs lookup if absolutely necessary.\n\n"
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
            "This is a DETAILED production spec — follow it precisely.\n\n"
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
            f"### DETAILED VISUAL & ANIMATION FLOW (follow this beat-by-beat)\n"
            f"{seg.get('visual_instructions', '')}\n\n"
            f"### Required Animations:\n{animations_str}\n\n"
            f"### CRITICAL REQUIREMENTS\n"
            f"- Set background: self.camera.background_color = \"{(color_palette or {}).get('Background', '#141414')}\"\n"
            f"- Every self.play() MUST have run_time parameter\n"
            f"- Add self.wait() after every animation beat\n"
            f"- Use the exact hex colors from the palette above\n"
            f"- Follow the visual flow instructions PRECISELY — they are a beat-by-beat screenplay\n"
            f"- FadeOut elements that are no longer needed before introducing new ones\n\n"
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

    code = _send_and_extract(
        client, model, system, prompt,
        max_tool_calls=max_tool_calls,
        tool_call_counts=tool_call_counts,
    )
    if not code:
        _log.debug("falling back to tool-less generation (model=%s)", model)
        code = _send_and_extract(
            client, model, system, prompt,
            max_tool_calls=0,
            tool_call_counts=tool_call_counts,
        )

    if code:
        yield code


def fix_manim_script(
    code: str,
    error: str,
    complexity: str = "complex",
    tool_call_counts: dict[str, int] | None = None,
    original_instructions: str = "",
) -> Iterator[str]:
    """Yield the corrected code after consulting docs."""
    model = _get_model_for_complexity(complexity)
    max_tool_calls = MAX_TOOL_CALLS_FIX_SIMPLE if complexity == "simple" else MAX_TOOL_CALLS_FIX_COMPLEX
    client = anthropic.Anthropic()

    system = SYSTEM_INSTRUCTION

    compact = _compact_error(error)

    # Classify error type for targeted hints
    error_lower = compact.lower()
    error_hints = ""
    if "tex_to_svg_file" in error_lower or "latex" in error_lower:
        error_hints = (
            "\n\nERROR TYPE: LaTeX compilation failure. "
            "Fix your LaTeX strings — check for missing double backslashes, unescaped characters, "
            "or undefined commands. Do NOT search for files."
        )
    elif "import" in error_lower or "modulenotfound" in error_lower:
        error_hints = (
            "\n\nERROR TYPE: Import error. "
            "Ensure you only use `from manim import *` and standard library imports."
        )
    elif "timeout" in error_lower:
        error_hints = (
            "\n\nERROR TYPE: Render timeout. "
            "Simplify geometry, reduce always_redraw complexity, shorten run_time values, "
            "and eliminate unnecessary updaters."
        )

    context_section = ""
    if original_instructions:
        context_section = f"\n\nOriginal visual instructions (for context):\n{original_instructions}\n"

    prompt = (
        "The following Manim script failed. Fix the code and return the COMPLETE corrected Python file. "
        f"You have a budget of {max_tool_calls} tool call(s) — use them to look up Manim docs or search for examples if the error is unfamiliar. "
        "Fix directly if the error is obvious (e.g. typo, missing import).\n\n"
        f"Error:\n{compact}{error_hints}\n\n"
        f"Current code:\n{code}"
        f"{context_section}"
    )

    yield "looking up docs"

    fixed = _send_and_extract(
        client, model, system, prompt,
        max_tool_calls=max_tool_calls,
        tool_call_counts=tool_call_counts,
    )
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
    segment_id: int | None = None,
):
    """Generate a Manim script, execute it, self-correct up to *max_retries*.

    Yields status dicts consumed by the CLI or Streamlit front-end.

    Args:
        complexity: "simple" or "complex" — controls which model is used.
        scene_class_name: The Manim Scene class name to generate.
        output_dir: Optional custom output directory for the rendered video.
    """
    model_label = _get_model_for_complexity(complexity)
    _seg = f"[Seg {segment_id}] " if segment_id is not None else ""
    code = ""
    tool_call_counts: dict[str, int] = {}

    def _attach_tool_usage(payload: dict) -> dict:
        counts = dict(sorted(tool_call_counts.items()))
        payload["tool_call_counts"] = counts
        payload["total_tool_calls"] = sum(counts.values())
        return payload

    yield {
        "status": f"{_seg}Generating Manim script [{complexity}] via {model_label}...",
        "phase": "generate",
    }
    for chunk in generate_manim_script(
        instructions, audio_script, audio_duration,
        complexity=complexity, scene_class_name=scene_class_name,
        tool_call_counts=tool_call_counts,
        theme_name=theme_name,
        color_palette=color_palette,
    ):
        if chunk == "looking up docs":
            yield {"status": f"{_seg}Generating with Claude...", "phase": "docs"}
            continue
        code = chunk
        yield {"status": f"{_seg}Generating initial Manim script...", "code": code, "phase": "generate"}

    if not code:
        yield _attach_tool_usage({
            "status": f"{_seg}Failed to generate the initial Manim script.",
            "error": "Empty model response.",
            "phase": "failed",
            "final": True,
        })
        return

    # Extract original visual instructions for self-correction context
    original_instructions = ""
    if isinstance(instructions, dict):
        original_instructions = instructions.get("visual_instructions", "")
    elif isinstance(instructions, str):
        original_instructions = instructions

    for attempt in range(max_retries + 1):
        class_name = extract_class_name(code)
        yield {
            "status": f"{_seg}Attempt {attempt + 1}/{max_retries + 1}: Executing code (Fast render -ql)...",
            "code": code,
            "phase": "execute",
        }

        result = run_manim_code(code, class_name, quality_flag="-ql", timeout_seconds=0, output_dir=output_dir)

        if result["success"]:
            yield _attach_tool_usage({
                "status": f"{_seg}Success! Low-res preview generated (-ql).",
                "video_path": result["video_path"],
                "code": code,
                "phase": "done",
                "final": True,
            })
            return

        if attempt < max_retries:
            corrective_hint = ""
            if result.get("error_type") == "timeout":
                corrective_hint = (
                    " Render timed out because geometry/updaters were too computationally expensive. "
                    "Simplify geometry, reduce dynamic redraw complexity, and shorten long run_time blocks."
                )
            yield {
                "status": f"{_seg}Execution failed. Self-correcting (attempt {attempt + 1}/{max_retries})...{corrective_hint}",
                "error": f"{result['error']}{corrective_hint}",
                "phase": "self_correct",
            }
            updated_code = ""
            for chunk in fix_manim_script(
                code,
                f"{result['error']}{corrective_hint}",
                complexity=complexity,
                tool_call_counts=tool_call_counts,
                original_instructions=original_instructions,
            ):
                if chunk == "looking up docs":
                    yield {"status": f"{_seg}Looking up docs for fix (attempt {attempt + 1}/{max_retries})...", "phase": "fix_docs"}
                    continue
                updated_code = chunk
                yield {
                    "status": f"{_seg}Applying fix (attempt {attempt + 1}/{max_retries})...",
                    "code": updated_code,
                    "phase": "apply_fix",
                }

            if not updated_code:
                yield _attach_tool_usage({
                    "status": f"{_seg}Failed to receive corrected code from model.",
                    "error": "Empty model response while self-correcting.",
                    "phase": "failed",
                    "final": True,
                })
                return

            code = updated_code
        else:
            yield _attach_tool_usage({
                "status": f"{_seg}Failed to generate a working script after {max_retries + 1} attempts.",
                "error": result["error"],
                "phase": "failed",
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
    segment_id: int | None = None,
    on_update=None,
) -> dict:
    """Async wrapper around ``run_coder_agent``.

    Runs the synchronous generator in a thread-pool so multiple segments
    can be generated concurrently via ``asyncio.gather()``.

    Returns the final result dict (the one with ``"final": True``).
    """
    loop = asyncio.get_running_loop()

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
            segment_id=segment_id,
        ):
            if on_update:
                try:
                    on_update(update)
                except Exception:
                    pass
            last_update = update
        return last_update

    return await loop.run_in_executor(None, _run_sync)
