#!/usr/bin/env python3
"""Thin NDJSON bridge between the TypeScript Ink CLI and the Python pipeline.

Protocol:
  1. Runner receives args as JSON on argv[1].
  2. If no questionnaire_answers provided, runner generates questions and
     prints {"type": "questions", "questions": [...]} then waits for
     {"type": "answers", "answers": {...}} on stdin.
  3. Pipeline updates are printed as {"type": "pipeline", "update": {...}}.
  4. Errors are printed as {"type": "error", "message": "..."}.
"""

from __future__ import annotations

import json
import os
import select
import sys

# Ensure the project root is importable
_project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _project_root)

# Load .env so API keys are available when spawned from the TS CLI
_dotenv_loaded = False
try:
    from dotenv import dotenv_values
    for _env_path in [
        os.path.join(_project_root, ".env"),
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.expanduser("~"), ".paper2manim", ".env"),
    ]:
        if os.path.isfile(_env_path):
            for _k, _v in dotenv_values(_env_path).items():
                if _v and not os.environ.get(_k):
                    os.environ[_k] = _v
            _dotenv_loaded = True
            break
except ImportError:
    # Try manual parsing as fallback when python-dotenv is not installed
    for _env_path in [
        os.path.join(_project_root, ".env"),
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.expanduser("~"), ".paper2manim", ".env"),
    ]:
        if os.path.isfile(_env_path):
            with open(_env_path) as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line and not _line.startswith("#") and "=" in _line:
                        _k, _, _v = _line.partition("=")
                        _k, _v = _k.strip(), _v.strip()
                        if _v and not os.environ.get(_k):
                            os.environ[_k] = _v
            _dotenv_loaded = True
            break


def _emit(msg: dict) -> None:
    """Print a JSON line to stdout (unbuffered).
    H10: Wrapped in try-except so a non-serializable object in `msg` never crashes stdout.
    """
    try:
        print(json.dumps(msg, default=str), flush=True)
    except Exception as e:
        # Fallback: emit a safe error message so the TS side always gets valid NDJSON
        try:
            print(json.dumps({"type": "error", "message": f"Emit error: {e}"}), flush=True)
        except Exception:
            pass  # stdout itself is broken; nothing we can do


def _read_stdin_line(timeout_seconds: float = 30.0) -> str | None:
    """C8: Read one line from stdin with a timeout.

    Returns the stripped line, or None if the timeout expired or EOF was reached.
    Uses select() on Unix; falls back to a blocking read on Windows (no select).
    """
    try:
        # select() is not available on Windows pipes; guard accordingly
        ready, _, _ = select.select([sys.stdin], [], [], timeout_seconds)
        if not ready:
            return None
    except (AttributeError, ValueError):
        # Windows or non-selectable fd — fall back to blocking read
        pass

    line = sys.stdin.readline()
    return line.strip() if line else None


def _handle_workspace_command(args: dict) -> None:
    """Handle workspace management commands (list, delete, cleanup)."""
    from utils.project_state import (
        calculate_progress,
        cleanup_placeholder_projects,
        delete_project,
        list_all_projects,
        list_placeholder_projects,
    )

    action = args.get("workspace_action", "list")

    if action == "list":
        projects = list_all_projects("output")
        placeholders = list_placeholder_projects("output")
        result = []
        for pdir, state in projects:
            done, total, desc = calculate_progress(state)
            result.append({
                "dir": pdir,
                "folder": os.path.basename(pdir),
                "concept": state.get("concept", "Unknown"),
                "status": state.get("status", "in_progress"),
                "updated_at": state.get("updated_at", "Unknown"),
                "progress_done": done,
                "progress_total": total,
                "progress_desc": desc,
            })
        _emit({
            "type": "workspace_projects",
            "projects": result,
            "placeholder_count": len(placeholders),
        })

    elif action == "delete":
        target_dir = args.get("target_dir", "")
        if not target_dir:
            _emit({"type": "error", "message": "No target_dir provided for delete."})
            return
        success = delete_project(target_dir)
        _emit({"type": "workspace_result", "action": "delete", "success": success, "dir": target_dir})

    elif action == "cleanup":
        removed = cleanup_placeholder_projects("output")
        _emit({"type": "workspace_result", "action": "cleanup", "removed": removed})

    elif action == "view_summary":
        target_dir = args.get("target_dir", "")
        summary_path = os.path.join(target_dir, "pipeline_summary.txt")
        if os.path.exists(summary_path):
            with open(summary_path, "r", encoding="utf-8") as f:
                text = f.read().strip()
            _emit({"type": "workspace_summary", "text": text, "dir": target_dir})
        else:
            _emit({"type": "workspace_summary", "text": None, "dir": target_dir})

    else:
        _emit({"type": "error", "message": f"Unknown workspace action: {action}"})


def main() -> None:
    if len(sys.argv) < 2:
        _emit({"type": "error", "message": "Usage: pipeline_runner.py '<json_args>'"})
        sys.exit(1)

    try:
        args = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        _emit({"type": "error", "message": f"Invalid JSON args: {e}"})
        sys.exit(1)

    # ── Workspace commands (no pipeline) ─────────────────────────────
    mode = args.get("mode")
    if mode == "workspace":
        _handle_workspace_command(args)
        return

    concept: str = args.get("concept", "")
    max_retries: int = args.get("max_retries", 3)
    is_lite: bool = args.get("is_lite", False)
    skip_audio: bool = args.get("skip_audio", False)
    questionnaire_answers: dict | None = args.get("questionnaire_answers")
    render_timeout: int = int(args.get("render_timeout") or 0)
    tts_timeout: int = int(args.get("tts_timeout") or 0)
    force_restart: bool = args.get("force_restart", False)
    # Phase 5-6 extensions (new optional args — fully backward-compatible)
    system_prompt_prefix: str = args.get("system_prompt_prefix") or ""
    max_turns: int = int(args.get("max_turns") or 0)
    model_override: str = args.get("model") or ""

    # ── Resume mode: load concept from existing project ──────────────
    resume_dir: str | None = args.get("resume_dir")
    if resume_dir:
        from utils.project_state import load_project
        state = load_project(resume_dir)
        if not state:
            _emit({"type": "error", "message": f"Cannot resume: no valid project at {resume_dir}"})
            sys.exit(1)
        concept = state.get("concept", "")
        _emit({"type": "resume_info", "concept": concept, "dir": resume_dir})

    if not concept:
        _emit({"type": "error", "message": "No concept provided."})
        sys.exit(1)

    # ── Questionnaire phase (single round, no LLM calls) ────────────
    if questionnaire_answers is None:
        questions: list[dict] = [
            {
                "id": "video_length",
                "question": "Video length:",
                "options": ["Short (1-2 min)", "Medium (3-5 min)", "Long (5-10 min)"],
                "default": "Medium (3-5 min)",
            },
            {
                "id": "target_audience",
                "question": "Target audience:",
                "options": [
                    "High school student",
                    "Undergraduate",
                    "Graduate / Professional",
                    "General audience",
                ],
                "default": "Undergraduate",
            },
            {
                "id": "visual_style",
                "question": "Visual approach:",
                "options": [
                    "Geometric intuition",
                    "Step-by-step derivation",
                    "Real-world applications",
                    "Let the AI decide",
                ],
                "default": "Let the AI decide",
            },
            {
                "id": "pacing",
                "question": "Pacing:",
                "options": [
                    "Fast and dense",
                    "Balanced",
                    "Slow and exploratory",
                ],
                "default": "Balanced",
            },
        ]

        _emit({"type": "questions", "questions": questions})

        # C8: Wait for answers on stdin with a 30-second timeout
        line = _read_stdin_line(timeout_seconds=30.0)
        if not line:
            _emit({"type": "error", "message": "Timeout waiting for questionnaire answers (30s). Is the CLI still running?"})
            sys.exit(1)
        try:
            msg = json.loads(line)
            questionnaire_answers = msg.get("answers", {})
        except Exception as e:
            _emit({"type": "error", "message": f"Failed to parse questionnaire answers: {e}"})
            sys.exit(1)

        # Emit preference summary for the UI to display
        vl = questionnaire_answers.get("video_length", "Medium (3-5 min)")
        ta = questionnaire_answers.get("target_audience", "Undergraduate")
        vs = questionnaire_answers.get("visual_style", "Let the AI decide")
        pa = questionnaire_answers.get("pacing", "Balanced")
        _emit({
            "type": "preferences_summary",
            "summary": f"Creating a {vl} video for {ta} | Style: {vs} | Pacing: {pa}",
        })

    # ── Preflight: verify API keys are usable ────────────────────────
    missing_keys = []
    if not os.environ.get("ANTHROPIC_API_KEY"):
        missing_keys.append("ANTHROPIC_API_KEY")
    if not skip_audio and not os.environ.get("GEMINI_API_KEY"):
        missing_keys.append("GEMINI_API_KEY")
    if missing_keys:
        _emit({"type": "error", "message": f"Missing API keys: {', '.join(missing_keys)}. Set them in .env in the project root."})
        sys.exit(1)

    # ── Pipeline phase ───────────────────────────────────────────────
    from agents.pipeline import run_segmented_pipeline

    # If system_prompt_prefix or model_override provided, inject via env so agents can read it
    if system_prompt_prefix:
        os.environ["PAPER2MANIM_SYSTEM_PROMPT_PREFIX"] = system_prompt_prefix
    if model_override:
        os.environ["PAPER2MANIM_MODEL_OVERRIDE"] = model_override
    if max_turns:
        os.environ["PAPER2MANIM_MAX_TURNS"] = str(max_turns)

    try:
        for update in run_segmented_pipeline(
            concept=concept,
            output_base="output",
            max_retries=max_retries,
            is_lite=is_lite,
            questionnaire_answers=questionnaire_answers,
            skip_audio=skip_audio,
            render_timeout_seconds=render_timeout,
            tts_timeout_seconds=tts_timeout,
            force_restart=force_restart,
        ):
            _emit({"type": "pipeline", "update": update})

            # Emit real token_usage when the final update includes a token_summary
            token_summary = update.get("token_summary")
            if token_summary and update.get("final"):
                _emit({
                    "type": "token_usage",
                    "input": token_summary.get("total_input_tokens", 0),
                    "output": token_summary.get("total_output_tokens", 0),
                })

    except Exception as e:
        _emit({"type": "error", "message": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    main()
