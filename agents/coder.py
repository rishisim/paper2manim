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
from utils.manim_runner import run_manim_code, extract_class_name


MODEL_NAME = "gemini-3.1-pro-preview"

# ── helpers ───────────────────────────────────────────────────────────

_CODE_FENCE_RE = re.compile(r"```(?:python)?\s*\n?|```\s*$", re.MULTILINE)


def _strip_code_fences(text: str) -> str:
    return _CODE_FENCE_RE.sub("", text).strip()


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

SYSTEM_INSTRUCTION = f"""\
You are an expert Manim Community Edition developer.
You have access to two documentation tools:

1. `fetch_manim_docs(topic)` — returns the full Python source (with
   docstrings and inline examples) for a Manim concept.
2. `fetch_manim_file(file_path)` — returns any file from the Manim
   GitHub repo by its path.

{TOPIC_INDEX_TEXT}

IMPORTANT RULES:
- ALWAYS look up documentation for the main classes/animations you plan to
  use BEFORE writing the code.  For example, if you intend to use `Axes`,
  call `fetch_manim_docs("axes")` first and read the constructor signature.
- Output ONLY raw Python code.  No markdown fences, no prose.
- Import manim: `from manim import *`
- Define exactly one class inheriting from `Scene`, named `GeneratedScene`.
- Prefer robust, simple primitives: `Text`, `Circle`, `Square`, `Rectangle`,
  `Line`, `Arrow`, `VGroup`, `Axes`, `NumberPlane`.
- Prefer basic animations: `Create`, `Write`, `FadeIn`, `FadeOut`,
  `Transform`, `ReplacementTransform`, `.animate`.
- Avoid `MathTex`/`Tex` unless the visual instructions explicitly require
  LaTeX equations.  If you do use them, look up their docs first.
- No external assets (SVGs, images, audio files).
- Keep total scene runtime short (end with `self.wait(2)`).
- Keep code deterministic — no randomness.
"""


def _build_config() -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        tools=[
            fetch_manim_docs,
            fetch_manim_file,
        ],
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0.2,
    )


def _send_and_extract(chat, message: str) -> str:
    """Send a message through the chat (which handles tool calls
    automatically) and return the final text with code fences stripped."""
    response = chat.send_message(message)
    return _strip_code_fences(response.text or "")


# ── public generators ─────────────────────────────────────────────────

def generate_manim_script(instructions: str) -> Iterator[str]:
    """Yield the final generated code (single yield after tool calls resolve)."""
    client = genai.Client()
    chat = client.chats.create(model=MODEL_NAME, config=_build_config())

    prompt = (
        "Write a complete Manim script for the following visual instructions.\n"
        "Before writing any code, look up the documentation for the main "
        "classes and animations you plan to use.\n\n"
        f"Instructions:\n{instructions}"
    )

    yield "looking up docs"  # signal to caller

    code = _send_and_extract(chat, prompt)
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

def run_coder_agent(visual_instructions: str, max_retries: int = 3):
    """Generate a Manim script, execute it, self-correct up to *max_retries*.

    Yields status dicts consumed by the CLI or Streamlit front-end.
    """
    code = ""

    yield {"status": "Generating initial Manim script (consulting docs)..."}
    for chunk in generate_manim_script(visual_instructions):
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
