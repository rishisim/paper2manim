#!/usr/bin/env python3
"""Paper2Manim CLI — modern terminal experience."""

import argparse
import logging
import os
import random
import re
import signal
import sys
import time
import itertools
import threading
from typing import Callable

from dotenv import dotenv_values
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.markup import escape
from rich import box
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich_argparse import RichHelpFormatter

from agents.coder import run_coder_agent
from agents.planner import plan_segmented_storyboard, plan_segmented_storyboard_lite
from agents.pipeline import run_segmented_pipeline
from utils.media_assembler import stitch_video_and_audio
from utils.tts_engine import generate_voiceover
from utils.project_state import (
    create_project, load_project, save_project, 
    mark_stage_done, is_stage_done, list_all_projects, delete_project,
    mark_project_complete, calculate_progress,
    list_placeholder_projects, cleanup_placeholder_projects,
)

# Search for .env in multiple locations: next to the script, cwd, and the
# canonical project directory (for pipx/installed setups where __file__ is in site-packages).
_env_candidates = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
    os.path.join(os.getcwd(), ".env"),
    os.path.expanduser("~/Documents/projects/paper2manim/.env"),
]
for _env_path in _env_candidates:
    if os.path.isfile(_env_path):
        for _k, _v in dotenv_values(_env_path).items():
            if _v and not os.environ.get(_k):
                os.environ[_k] = _v
        break
console = Console(highlight=False)

# ── Theme constants ───────────────────────────────────────────────────
ACCENT = "blue"
ACCENT_B = "bold blue"
DIM = "grey62"
SUCCESS = "green"
FAIL = "red"
WARN = "yellow"
MUTED = "grey50"

VERSION = "0.1.0"
MODEL_TAG = "claude-opus-4.6 + gemini-3.1-pro"

BRAND_ICON = "✻"

# ── Theme system ─────────────────────────────────────────────────────
THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "ACCENT": "blue", "ACCENT_B": "bold blue", "DIM": "grey62",
        "SUCCESS": "green", "FAIL": "red", "WARN": "yellow", "MUTED": "grey50",
    },
    "light": {
        "ACCENT": "dark_blue", "ACCENT_B": "bold dark_blue", "DIM": "grey37",
        "SUCCESS": "dark_green", "FAIL": "dark_red", "WARN": "dark_orange", "MUTED": "grey46",
    },
    "minimal": {
        "ACCENT": "white", "ACCENT_B": "bold white", "DIM": "white",
        "SUCCESS": "white", "FAIL": "bold white", "WARN": "white", "MUTED": "white",
    },
}


def _apply_theme(name: str) -> None:
    global ACCENT, ACCENT_B, DIM, SUCCESS, FAIL, WARN, MUTED
    t = THEMES.get(name, THEMES["dark"])
    ACCENT = t["ACCENT"]
    ACCENT_B = t["ACCENT_B"]
    DIM = t["DIM"]
    SUCCESS = t["SUCCESS"]
    FAIL = t["FAIL"]
    WARN = t["WARN"]
    MUTED = t["MUTED"]


# ── Print mode + keyboard state ──────────────────────────────────────
_print_mode: bool = False
_verbose_live: bool = False
_show_help_overlay: bool = False
_prev_verbose_live: bool = False
# Thread-safe console reference — set to progress.console while pipeline runs
# so keyboard listener can print immediately without waiting for next update
_active_console: Console | None = None

# ── Double Ctrl+C to exit ────────────────────────────────────────────
_last_sigint_time: float = 0.0


def _sigint_handler(signum: int, frame) -> None:
    """First Ctrl+C warns; second within 2s exits."""
    global _last_sigint_time
    now = time.monotonic()
    if now - _last_sigint_time < 2.0:
        console.print(f"\n  [{DIM}]Exiting...[/{DIM}]")
        sys.exit(130)
    _last_sigint_time = now
    console.print(f"\n  [{WARN}]Press Ctrl+C again to exit[/{WARN}]")


signal.signal(signal.SIGINT, _sigint_handler)
ACTION_ICON = "⏺"

TIPS = [
    "Use --quality low for faster generation",
    "Press ? during a run to see keyboard shortcuts",
    "Press Ctrl+O to toggle verbose mode live",
    "Use --output-format json for scripting",
    "Pass a concept as an argument to skip the prompt",
    "Use --model to override the Claude model",
]


def _print_banner(quality: str = "high", model: str | None = None) -> None:
    """Print Claude Code-style banner with cwd, model, and a random tip."""
    tip = random.choice(TIPS)
    cwd = os.getcwd()
    model_display = model or MODEL_TAG
    quality_label = quality.title()
    content = (
        f"[bold {ACCENT}]{BRAND_ICON}[/bold {ACCENT}] [bold white]paper2manim[/bold white]  [dim]v{VERSION}[/dim]\n"
        f"\n"
        f"  [dim]Model: {model_display}[/dim]  [dim]Quality: {quality_label}[/dim]\n"
        f"  [dim]cwd: {cwd}[/dim]\n"
        f"\n"
        f"  [dim]Tip: {tip}[/dim]"
    )
    console.print(Panel(content, border_style=ACCENT, box=box.ROUNDED, padding=(0, 2)))


def _set_terminal_title(title: str) -> None:
    """Set the terminal tab/window title."""
    if sys.stdout.isatty():
        sys.stdout.write(f"\x1b]0;{title}\x07")
        sys.stdout.flush()


def _notify(event: str, message: str = "") -> None:
    """Send terminal/OS notifications based on event type."""
    if event == "questionnaire_done":
        # Taskbar bounce (iTerm2 + compatible terminals)
        sys.stdout.write("\033]1337;RequestAttention=yes\a")
        sys.stdout.flush()
    elif event == "error":
        sys.stdout.write("\a")  # Terminal bell
        sys.stdout.write("\033]1337;RequestAttention=yes\a")
        sys.stdout.flush()
    elif event == "complete":
        sys.stdout.write("\a")  # Terminal bell
        sys.stdout.write("\033]1337;RequestAttention=yes\a")
        sys.stdout.flush()
        if sys.platform == "darwin":
            title = "paper2manim"
            body = (message or "Video generation complete!").replace('"', '\\"')
            os.system(
                f'osascript -e \'display notification "{body}" '
                f'with title "{title}" sound name "Glass"\''
            )


def _truncate(text: str, max_len: int = 80) -> str:
    """Truncate text to max_len characters, adding ellipsis if needed."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def _clean_status(raw: str) -> str:
    """Clean up a raw pipeline status string for user-facing display."""
    s = raw.strip()
    # Strip "Stage X/Y: " prefix — stage is already shown in the header
    s = re.sub(r"^Stage \d+/\d+:\s*", "", s, flags=re.IGNORECASE)
    # Strip "[Seg N] " prefix
    s = re.sub(r"^\[Seg \d+\]\s*", "", s, flags=re.IGNORECASE)
    # Strip trailing dots
    s = re.sub(r"\.{2,}$", "", s)
    # Strip parenthetical internal details
    s = re.sub(r"\s*\(-?q[lh]\)", "", s)            # quality flags
    s = re.sub(r"\s*\(target:.*?\)", "", s)          # (target: 90s, ...)
    s = re.sub(r"\s*\(parallel,.*?\)", "", s)        # (parallel, 2000+ tokens...)
    s = re.sub(r"\s*\(Fast render.*?\)", "", s)      # (Fast render -ql)
    # Strip "→ " prefix (pipeline arrow notation)
    s = re.sub(r"^\s*→\s*", "", s)
    # Strip verbose phrasing
    s = re.sub(r"^Composing verbose narrative", "Composing", s)
    # Capitalize first letter
    s = s.strip()
    if s:
        s = s[0].upper() + s[1:]
    return s


def _format_duration(seconds: float) -> str:
    """Format seconds as '12.3s' or '477.1s [7m 57s]' for >=60s."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{seconds:.1f}s [{m}m {s:02d}s]"


def _format_stage_name(name: str) -> str:
    labels = {
        "plan": "Plan storyboard",
        "tts": "Generate voiceover",
        "code": "Generate Manim code",
        "render": "Render HD segments",
        "stitch": "Stitch audio/video",
        "concat": "Assemble final video",
        "done": "Finalize",
    }
    return labels.get(name, name.replace("_", " ").title())


# ── Logging helpers ───────────────────────────────────────────────────
def _log_step(text: str, last: bool = False):
    branch = "└─" if last else "├─"
    console.print(f"  [{MUTED}]{branch}[/{MUTED}] [{SUCCESS}]✓[/{SUCCESS}] [{DIM}]{text}[/{DIM}]")


def _log_stage_done(name: str, elapsed: float):
    label = _format_stage_name(name)
    console.print(f"  [{SUCCESS}]✓[/{SUCCESS}] [bold]{label}[/bold]  [{DIM}]{_format_duration(elapsed)}[/{DIM}]")


def _log_stage_fail(name: str, elapsed: float):
    label = _format_stage_name(name)
    console.print(f"  [{FAIL}]✗[/{FAIL}] [bold]{label}[/bold]  [{DIM}]{_format_duration(elapsed)}[/{DIM}]")


def _log_stage_header(name: str):
    console.print()
    console.print(f"  [{ACCENT}]{ACTION_ICON}[/{ACCENT}] [bold]{name}[/bold][{DIM}]...[/{DIM}]")


# ── CLI args ──────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    RichHelpFormatter.styles["argparse.args"] = "bold cyan"
    RichHelpFormatter.styles["argparse.groups"] = "bold blue"
    RichHelpFormatter.styles["argparse.help"] = "dim"
    RichHelpFormatter.styles["argparse.metavar"] = "bold yellow"

    parser = argparse.ArgumentParser(
        prog="paper2manim",
        description="Generate an educational video from a concept.",
        formatter_class=RichHelpFormatter,
        epilog=(
            "examples:\n"
            "  paper2manim 'The Chain Rule'\n"
            "  paper2manim -p 'Fourier Transform'              # non-interactive\n"
            "  paper2manim --quality low 'Dot Products'        # fast run\n"
            "  paper2manim --output-format json 'SVD'          # JSON output\n"
            "  paper2manim --model claude-sonnet-4-5 'Bayes Theorem'\n"
            "  paper2manim --skip-audio 'Linear Algebra: Dot Products'\n"
            "  paper2manim --max-retries 5 --verbose"
        ),
    )

    parser.add_argument("--version", action="version", version=f"paper2manim {VERSION}")
    parser.add_argument("concept", nargs="*", help="Concept/topic to visualize")

    options = parser.add_argument_group("Options")
    options.add_argument(
        "--max-retries", type=int, default=3,
        help="Maximum self-correction attempts for Manim code (default: 3)",
    )
    options.add_argument("--skip-audio", action="store_true",
                        help="Skip TTS and stitching; render animation only")
    options.add_argument("--quality", "-q",
                        choices=["low", "medium", "high"], default="high", metavar="LEVEL",
                        help="Generation quality: low (fast), medium, high (default: high)")
    options.add_argument("--model", default=None, metavar="MODEL",
                        help="Override the Claude model (e.g. claude-sonnet-4-5)")
    options.add_argument("--theme",
                        choices=["dark", "light", "minimal"], default="dark", metavar="THEME",
                        help="Terminal color theme (default: dark)")
    options.add_argument("--output-format",
                        choices=["text", "json"], default="text", metavar="FORMAT",
                        help="Output format: text (default) or json (for scripting)")
    options.add_argument("-p", "--print", dest="print_mode", action="store_true",
                        help="Non-interactive mode: plain text output, no Rich widgets")
    options.add_argument("--verbose", action="store_true",
                        help="Show detailed diagnostics for failures")

    workspace = parser.add_argument_group("Workspace Management")
    workspace.add_argument("--workspace", action="store_true",
                        help="Open the interactive workspace dashboard")
    workspace.add_argument("--resume", type=str, metavar="DIR",
                        help="Path to an existing output directory to resume")

    deprecated = parser.add_argument_group("Deprecated")
    deprecated.add_argument("--lite", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()

    # --lite is a backward-compat alias for --quality low
    if getattr(args, "lite", False):
        args.quality = "low"
        console.print(f"  [{WARN}]--lite is deprecated; use --quality low[/{WARN}]")

    return args


# ── Pipeline summary ─────────────────────────────────────────────────
def print_pipeline_summary(stages: list[tuple[str, str, float]]) -> None:
    console.print()
    console.print("  [bold]Pipeline Summary[/bold]")
    console.print()
    total = 0.0
    for name, status, elapsed in stages:
        total += elapsed
        icon = f"[{SUCCESS}]✓[/{SUCCESS}]" if status == "ok" else f"[{FAIL}]✗[/{FAIL}]"
        label = _format_stage_name(name)
        console.print(f"  {icon} {label:<28} [{DIM}]{_format_duration(elapsed)}[/{DIM}]")
    console.print(f"  [{DIM}]{'─' * 40}[/{DIM}]")
    console.print(f"    [bold]{'Total':<27}{_format_duration(total)}[/bold]")
    console.print()


def save_pipeline_summary(
    stages: list[tuple[str, str, float]],
    output_dir: str,
    concept: str = "",
    tool_call_counts: dict[str, int] | None = None,
) -> str:
    """Write a plain-text pipeline summary to ``output_dir/pipeline_summary.txt``."""
    total = sum(e for _, _, e in stages)
    lines: list[str] = []
    lines.append("Pipeline Summary")
    lines.append("=" * 50)
    if concept:
        lines.append(f"Concept : {concept}")
    lines.append(f"Date    : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append(f"{'Status':<8} {'Stage':<25} {'Time':>16}")
    lines.append("-" * 58)
    for name, status, elapsed in stages:
        tag = "OK" if status == "ok" else "ERR"
        lines.append(f"{tag:<8} {name:<25} {_format_duration(elapsed):>16}")
    lines.append("-" * 58)
    lines.append(f"{'':8} {'Total':<25} {_format_duration(total):>16}")
    lines.append("")

    lines.append("Tool Calls")
    lines.append("=" * 50)
    tool_call_counts = tool_call_counts or {}
    total_tool_calls = sum(tool_call_counts.values())
    lines.append(f"Total  : {total_tool_calls}")
    lines.append("")
    if tool_call_counts:
        for tool_name, count in sorted(tool_call_counts.items()):
            lines.append(f"- {tool_name}")
            lines.append(f"  Calls : {count}")
            lines.append("")
    else:
        lines.append("No tool calls recorded.")
        lines.append("")

    os.makedirs(output_dir, exist_ok=True)
    summary_path = os.path.join(output_dir, "pipeline_summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return summary_path


# ── Storyboard display ───────────────────────────────────────────────
def _print_storyboard(storyboard: dict) -> None:
    """Render storyboard in styled panels."""
    visual_lines: list[str] = []
    for line in storyboard["visual_instructions"].split(". "):
        line = line.strip()
        if line:
            if not line.endswith("."):
                line += "."
            visual_lines.append(f"  [white]•[/white] {line}")

    visual_text = "\n".join(visual_lines) if visual_lines else storyboard["visual_instructions"]
    console.print(Panel(
        visual_text,
        title="[bold]Visual Instructions[/bold]",
        title_align="left",
        border_style=ACCENT,
        padding=(1, 2),
    ))

    console.print(Panel(
        f"[italic]{escape(storyboard['audio_script'])}[/italic]",
        title="[bold]Audio Script[/bold]",
        title_align="left",
        border_style=ACCENT,
        padding=(1, 2),
    ))


# ── Error panels ─────────────────────────────────────────────────────
ERROR_HINTS: dict[str, tuple[str, str]] = {
    "credit balance":   ("API credits exhausted",  "Visit console.anthropic.com/settings/billing to add credits."),
    "invalid api key":  ("Invalid API key",         "Check ANTHROPIC_API_KEY in .env — it may be expired or incorrect."),
    "authentication":   ("API auth failed",         "Verify ANTHROPIC_API_KEY and GEMINI_API_KEY in your .env file."),
    "401":              ("API auth failed",         "Verify ANTHROPIC_API_KEY and GEMINI_API_KEY in your .env file."),
    "rate limit":       ("Rate limited",            "Wait 30–60 seconds and retry. Consider --quality low to use fewer tokens."),
    "429":              ("Rate limited",            "Wait 30–60 seconds and retry. Consider --quality low."),
    "timeout":          ("Network timeout",         "Check your internet connection and try again."),
    "missing api key":  ("Missing API key",         "Create a .env file:\n    ANTHROPIC_API_KEY=...\n    GEMINI_API_KEY=..."),
    "manim":            ("Manim rendering error",   "Ensure Manim is installed: pip install manim\nUse --max-retries 5 for more self-correction attempts."),
}


def _print_error(message: str, detail: str | None = None) -> None:
    combined = f"{message} {detail or ''}".lower()
    hint_title, hint_text = None, None
    for key, (title, text) in ERROR_HINTS.items():
        if key in combined:
            hint_title, hint_text = title, text
            break

    body = f"[{FAIL}]{escape(message)}[/{FAIL}]"
    if detail:
        body += f"\n\n[{DIM}]{escape(detail[:400])}[/{DIM}]"
    if hint_text:
        body += f"\n\n[{WARN}]Suggestion:[/{WARN}] {hint_text}"

    subtitle = f"[bold red]{hint_title}[/bold red]" if hint_title else None
    console.print(Panel(
        body,
        title="[bold red]Error[/bold red]",
        subtitle=subtitle,
        border_style=FAIL,
        padding=(1, 2),
        width=min(console.width, 120),
    ))
    _notify("error")


# ── Success output ────────────────────────────────────────────────────
def _print_output(path: str) -> None:
    abs_path = os.path.abspath(path)
    console.print(f"\n  [{SUCCESS}]✓ Output ready[/{SUCCESS}]  [bold]{abs_path}[/bold]")


def _load_pipeline_summary_text(project_dir: str) -> str | None:
    """Load a project's plain-text pipeline summary if present."""
    summary_path = os.path.join(project_dir, "pipeline_summary.txt")
    if not os.path.exists(summary_path):
        return None
    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None

# ── Workspace Dashboard ─────────────────────────────────────────────
def manage_workspace() -> str | None:
    """Displays the interactive workspace dashboard and returns a directory to resume, or None."""
    while True:
        console.clear()
        _print_banner()
        console.print("\n  [bold]Project Workspace[/bold]")
        console.print(f"  [{DIM}]Resume or delete existing video projects.[/{DIM}]\n")
        
        placeholders = list_placeholder_projects("output")
        projects = list_all_projects("output")

        if placeholders:
            console.print(f"  [{MUTED}]Hidden stale entries: {len(placeholders)} (press [bold]x[/bold] to clean)[/{MUTED}]\n")

        if not projects:
            if placeholders:
                console.print(f"  [{WARN}]No active projects to show.[/{WARN}]\n")
                choice = Prompt.ask(
                    f"  [{ACCENT}]Action[/{ACCENT}] [dim][x: clean stale | q: quit][/dim]",
                    default="q",
                )
                if choice.lower() in ("x", "clean", "cleanup"):
                    if Confirm.ask(f"  [{WARN}]Clean {len(placeholders)} stale workspace entries?[/{WARN}]", default=True):
                        removed = cleanup_placeholder_projects("output")
                        console.print(f"  [{SUCCESS}]✓[/{SUCCESS}]  Removed {removed} stale entries.")
                        time.sleep(1)
                        continue
                return None

            console.print(f"  [{WARN}]No projects found in the workspace yet.[/{WARN}]\n")
            return None

        table = Table(
            box=box.MINIMAL,
            show_header=True,
            header_style="bold",
            padding=(0, 2),
        )
        table.add_column("ID", justify="right", style=ACCENT_B)
        table.add_column("Concept", style="bold white")
        table.add_column("Status", justify="left")
        table.add_column("Directory Name", style=DIM)
        table.add_column("Last Updated", style=DIM)

        for idx, (pdir, state) in enumerate(projects, 1):
            concept = state.get("concept", "Unknown")
            folder = os.path.basename(pdir)
            updated = state.get("updated_at", "Unknown")
            
            done, total, desc = calculate_progress(state)
            if state.get("status") == "completed":
                status_text = f"[{SUCCESS}]Completed[/{SUCCESS}]"
                progress = ""
            else:
                pct = int(100 * done / max(1, total))
                status_text = f"[{WARN}]In Progress[/{WARN}]"
                progress = f"({pct}% — {desc})"
            
            table.add_row(str(idx), concept, f"{status_text} {progress}", folder, updated)

        console.print(table)
        console.print()
        
        console.print(f"  [{DIM}]Commands: enter [bold]ID[/bold] to manage, [bold]x[/bold] clean stale, [bold]q[/bold] quit[/{DIM}]")
        choice = Prompt.ask(
            f"  [{ACCENT}]Action[/{ACCENT}] [dim][ID | x | q][/dim]",
            default="q",
        )
        if choice.lower() in ("x", "clean", "cleanup"):
            if not placeholders:
                console.print(f"  [{WARN}]No stale entries to clean.[/{WARN}]")
                time.sleep(1)
                continue
            if Confirm.ask(f"  [{WARN}]Clean {len(placeholders)} stale workspace entries?[/{WARN}]", default=True):
                removed = cleanup_placeholder_projects("output")
                console.print(f"  [{SUCCESS}]✓[/{SUCCESS}]  Removed {removed} stale entries.")
            else:
                console.print(f"  [{DIM}]Cleanup cancelled.[/{DIM}]")
            time.sleep(1)
            continue

        if choice.lower() in ("q", "quit", "exit"):
            return None
            
        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(projects):
                target_dir, state = projects[choice_idx]
                concept_name = state.get("concept", target_dir)
                
                action = Prompt.ask(
                    f"  [{ACCENT}]Project action[/{ACCENT}] [dim][v: view | r: resume | d: delete | c: cancel][/dim]", 
                    choices=["v", "r", "d", "c"], 
                    default="c"
                )

                if action == "v":
                    summary_text = _load_pipeline_summary_text(target_dir)
                    if summary_text:
                        console.print()
                        console.print(Panel(
                            summary_text,
                            title="[bold]Pipeline Summary[/bold]",
                            title_align="left",
                            border_style=ACCENT,
                            padding=(1, 2),
                        ))
                    else:
                        console.print(f"  [{WARN}]No pipeline summary found for this project yet.[/{WARN}]")
                    Prompt.ask(f"  [{ACCENT}]>[/{ACCENT}] Press Enter to return")
                
                elif action == "r":
                    return target_dir
                elif action == "d":
                    if Confirm.ask(f"  [{FAIL}]✗[/{FAIL}] Confirm delete for [bold]{concept_name}[/bold]?", default=False):
                        if delete_project(target_dir):
                            console.print(f"  [{SUCCESS}]Deleted successfully.[/{SUCCESS}]")
                        else:
                            console.print(f"  [{FAIL}]Failed to delete.[/{FAIL}]")
                        time.sleep(1)
            else:
                console.print(f"  [{FAIL}]Invalid ID.[/{FAIL}]")
                time.sleep(1)
        except ValueError:
            console.print(f"  [{FAIL}]Invalid input.[/{FAIL}]")
            time.sleep(1)


# ── Main ──────────────────────────────────────────────────────────────
def main() -> None:
    args = parse_args()

    # Apply theme and print mode early
    _apply_theme(getattr(args, "theme", "dark"))
    global _print_mode
    _print_mode = getattr(args, "print_mode", False) or not sys.stdout.isatty()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="  %(levelname)s  %(name)s: %(message)s",
    )

    # ── API key check ─────────────────────────────────────────────
    _missing_keys = []
    if not os.getenv("GEMINI_API_KEY"):
        _missing_keys.append("GEMINI_API_KEY")
    if not os.getenv("ANTHROPIC_API_KEY"):
        _missing_keys.append("ANTHROPIC_API_KEY")
    if _missing_keys:
        console.print()
        _print_error(
            f"{', '.join(_missing_keys)} not found in environment.",
            "Set them in .env:  GEMINI_API_KEY=...  ANTHROPIC_API_KEY=...",
        )
        sys.exit(1)

    os.makedirs("output", exist_ok=True)

    # ── Banner ────────────────────────────────────────────────────
    _quality = getattr(args, "quality", "high")
    _model = getattr(args, "model", None)
    if not args.workspace and not _print_mode:
        console.print()
        _print_banner(quality=_quality, model=_model)
        console.print()
    _set_terminal_title("paper2manim")

    output_dir = None
    project_state = None
    concept = ""

    # ── Workspace / Resume Handling ───────────────────────────────
    if args.workspace:
        selected_dir = manage_workspace()
        if not selected_dir:
            sys.exit(0)
        output_dir = selected_dir
        project_state = load_project(output_dir)
        if not project_state:
            _print_error("Failed to load project state", output_dir)
            sys.exit(1)
        concept = project_state.get("concept", "")
        console.print(f"\n  [{SUCCESS}]✓[/{SUCCESS}]  Resuming project: [bold]{concept}[/bold]")
        run_pipeline_for_concept(concept, args, output_dir=output_dir)
        
    elif args.resume:
        output_dir = os.path.abspath(args.resume)
        project_state = load_project(output_dir)
        if not project_state:
            _print_error(f"Cannot resume: {output_dir} does not contain a valid project state.")
            sys.exit(1)
        concept = project_state.get("concept", "")
        console.print(f"\n  [{SUCCESS}]✓[/{SUCCESS}]  Resuming project: [bold]{concept}[/bold]")
        run_pipeline_for_concept(concept, args, output_dir=output_dir)

    else:
        # ── Concept input ─────────────────────────────────────────────
        concept = " ".join(args.concept).strip()
        if concept:
            if not os.getenv("GEMINI_API_KEY"):
                console.print()
                _print_error(
                    "GEMINI_API_KEY not found in environment.",
                    "Set it in .env as  GEMINI_API_KEY=your_key_here",
                )
                sys.exit(1)
            questionnaire_answers = _run_questionnaire(concept)
            run_pipeline_for_concept(concept, args, questionnaire_answers=questionnaire_answers)
        else:
            interactive_repl(args)


def _run_questionnaire(concept: str) -> dict:
    """Single-screen checkbox questionnaire — all options at once, grouped by category."""
    import questionary
    from questionary import Style as QStyle, Choice, Separator

    q_style = QStyle([
        ("qmark",       "fg:cyan bold"),
        ("question",    "fg:white bold"),
        ("pointer",     "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected",    "fg:green"),
        ("answer",      "fg:cyan bold"),
        ("text",        "fg:white"),
        ("instruction", "fg:grey italic"),
        ("separator",   "fg:grey"),
    ])

    choices = [
        Separator("  ── Video Length ─────────────────────────────────────"),
        Choice("Short  (1–2 min)  ·  2–3 segments, fast overview",          value="vl:Short (1-2 min)"),
        Choice("Medium (3–5 min)  ·  4–5 segments, balanced depth",         value="vl:Medium (3-5 min)",         checked=True),
        Choice("Long   (5–10 min) ·  6–8 segments, comprehensive coverage", value="vl:Long (5-10 min)"),
        Separator("  ── Target Audience ──────────────────────────────────"),
        Choice("High school student",        value="ta:High school student"),
        Choice("Undergraduate",              value="ta:Undergraduate",              checked=True),
        Choice("Graduate / Professional",    value="ta:Graduate / Professional"),
        Choice("General audience",           value="ta:General audience"),
        Separator("  ── Visual Approach ──────────────────────────────────"),
        Choice("Geometric intuition    ·  build from shapes and diagrams", value="vs:Geometric intuition"),
        Choice("Step-by-step derivation ·  follow the math carefully",     value="vs:Step-by-step derivation"),
        Choice("Real-world applications ·  connect to concrete examples",  value="vs:Real-world applications"),
        Choice("Let the AI decide",                                         value="vs:Let the AI decide",         checked=True),
        Separator("  ── Pacing ───────────────────────────────────────────"),
        Choice("Fast and dense",      value="pa:Fast and dense"),
        Choice("Balanced",            value="pa:Balanced",            checked=True),
        Choice("Slow and exploratory", value="pa:Slow and exploratory"),
    ]

    _KEY_NAMES = {
        "vl": "Video Length",
        "ta": "Audience",
        "vs": "Visual Approach",
        "pa": "Pacing",
    }
    _KEY_MAP = {
        "vl": "video_length",
        "ta": "target_audience",
        "vs": "visual_style",
        "pa": "pacing",
    }

    def _validate(selected: list) -> bool | str:
        counts: dict[str, int] = {p: 0 for p in _KEY_NAMES}
        for item in selected:
            p = item.split(":")[0]
            if p in counts:
                counts[p] += 1
        for p, n in counts.items():
            if n > 1:
                return f"Pick exactly one {_KEY_NAMES[p]}"
            if n == 0:
                return f"Pick at least one {_KEY_NAMES[p]}"
        return True

    console.print()
    selected = questionary.checkbox(
        f"Configure your video for: {concept}",
        choices=choices,
        style=q_style,
        qmark="  ?",
        validate=_validate,
        instruction="  (space to toggle · ↑↓ navigate · enter to confirm)",
    ).ask()

    _notify("questionnaire_done")

    # Decode answers; fall back to defaults if cancelled
    _defaults = {
        "video_length":    "Medium (3-5 min)",
        "target_audience": "Undergraduate",
        "visual_style":    "Let the AI decide",
        "pacing":          "Balanced",
    }
    if not selected:
        return _defaults

    answers: dict = {}
    for item in selected:
        prefix, _, val = item.partition(":")
        if prefix in _KEY_MAP:
            answers[_KEY_MAP[prefix]] = val
    for k, v in _defaults.items():
        answers.setdefault(k, v)

    # Show preference summary
    console.print()
    console.print(f"  [{SUCCESS}]✓[/{SUCCESS}] {answers['video_length']} video for {answers['target_audience']} | {answers['visual_style']} | {answers['pacing']}")
    console.print(f"  [{DIM}]Starting pipeline...[/{DIM}]\n")
    return answers


def _keyboard_listener(stop_event: threading.Event) -> None:
    """Background thread: read single keystrokes and give immediate feedback.

    Rich's Console is thread-safe, so we can call _active_console.print()
    directly from here without waiting for the next pipeline update.
    """
    if sys.platform == "win32" or not sys.stdin.isatty() or _print_mode:
        return
    try:
        import tty
        import termios
        import select
    except ImportError:
        return
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while not stop_event.is_set():
            ready, _, _ = select.select([sys.stdin], [], [], 0.1)
            if not ready:
                continue
            ch = sys.stdin.read(1)
            global _show_help_overlay, _verbose_live
            ac = _active_console  # snapshot — thread safe read

            if ch == "?":
                _show_help_overlay = True
                if ac:
                    ac.print(Panel(
                        f"  [bold]?[/bold]       Toggle this help\n"
                        f"  [bold]Ctrl+O[/bold]  Toggle verbose mode\n"
                        f"  [bold]Ctrl+L[/bold]  Clear screen\n"
                        f"  [bold]Ctrl+C[/bold]  Cancel (press twice to exit)\n"
                        f"\n  [{DIM}]Verbose: {'ON' if _verbose_live else 'OFF'}[/{DIM}]",
                        title="[bold]Keyboard Shortcuts[/bold]",
                        border_style=ACCENT,
                        padding=(0, 2),
                    ))

            elif ch == "\x0f":  # Ctrl+O — toggle verbose
                _verbose_live = not _verbose_live
                label = "ON" if _verbose_live else "OFF"
                if ac:
                    ac.print(f"  [{ACCENT}]Verbose: {label}[/{ACCENT}]")

            elif ch == "\x0c":  # Ctrl+L — clear screen
                if ac:
                    ac.clear()
                else:
                    console.clear()

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _run_pipeline_print_mode(concept: str, pipeline_generator, stages: list) -> str | None:
    """Run the pipeline in plain-text mode (no Rich widgets)."""
    _strip_markup = re.compile(r"\[/?[^\]]+\]")
    final_video_path = None
    last_stage = None
    stage_start_time = time.perf_counter()

    for update in pipeline_generator:
        current_stage = update.get("stage", "unknown")
        status = update.get("status", "")
        if status:
            clean = _strip_markup.sub("", status).strip()
            if clean:
                print(f"[{current_stage}] {clean}", flush=True)

        if current_stage != last_stage:
            if last_stage:
                elapsed = time.perf_counter() - stage_start_time
                stages.append((last_stage, "ok", elapsed))
                print(f"[done] {_format_stage_name(last_stage)} ({_format_duration(elapsed)})", flush=True)
            last_stage = current_stage
            stage_start_time = time.perf_counter()

        if update.get("final"):
            final_video_path = update.get("video_path")
            if update.get("error"):
                elapsed = time.perf_counter() - stage_start_time
                stages.append((last_stage, "failed", elapsed))
                print(f"[error] {update['error']}", flush=True)
                return None

    if last_stage and last_stage != "done":
        elapsed = time.perf_counter() - stage_start_time
        stages.append((last_stage, "ok", elapsed))

    return final_video_path


def run_pipeline_for_concept(
    concept: str,
    args: argparse.Namespace,
    output_dir: str | None = None,
    questionnaire_answers: dict | None = None,
    _out_stages: list | None = None,
) -> None:
    is_lite = (getattr(args, "quality", "high") == "low") or getattr(args, "lite", False)
    quality_label = getattr(args, "quality", "high").title()
    model_override = getattr(args, "model", None)
    model_display = model_override or MODEL_TAG

    _set_terminal_title(f"paper2manim: {concept[:50]}")
    if not _print_mode:
        console.print(f"\n  [{DIM}]Concept:[/{DIM}] [bold]{escape(concept)}[/bold]")
        console.print(f"  [{DIM}]Quality:[/{DIM}] {quality_label}   [{DIM}]Model:[/{DIM}] {model_display}")
        console.print()
    else:
        print(f"[paper2manim] concept={concept!r} quality={quality_label} model={model_display}", flush=True)

    stages: list[tuple[str, str, float]] = []

    # ── Segmented Pipeline Runner ─────────────────────────────────
    pipeline_generator = run_segmented_pipeline(concept, output_base="output", max_retries=args.max_retries, is_lite=is_lite, questionnaire_answers=questionnaire_answers)
    
    # ── Print mode — no Rich progress bar ────────────────────────────
    if _print_mode:
        final_video_path = _run_pipeline_print_mode(concept, pipeline_generator, stages)
        if _out_stages is not None:
            _out_stages.extend(stages)
        if getattr(args, "output_format", "text") == "json":
            import json as _json
            result = {
                "status": "complete" if final_video_path else "error",
                "concept": concept,
                "video_path": os.path.abspath(final_video_path) if final_video_path else None,
                "stages": [{"name": n, "status": s, "elapsed": e} for n, s, e in stages],
            }
            print(_json.dumps(result), flush=True)
        elif final_video_path:
            abs_path = os.path.abspath(final_video_path)
            print(f"[complete] output={abs_path}", flush=True)
        return

    final_video_path = None
    total_segments_expected = 0

    last_stage = None
    stage_start_time = time.perf_counter()
    segment_phase_labels = {
        "generate": "Generating",
        "docs": "Looking up Docs",
        "execute": "Validating",
        "self_correct": "Self-Correcting",
        "fix_docs": "Fix: Docs",
        "apply_fix": "Applying Fix",
        "done": "Done",
        "failed": "Failed",
        "running": "Running",
    }
    code_segment_state: dict[int, str] = {}
    code_segment_attempts: dict[int, int] = {}
    stitch_done_count = 0

    # ── Segment progress grid ─────────────────────────────────────────
    _SEGMENT_ICONS: dict[str, tuple[str, str]] = {
        "Generating":      ("◌", ACCENT),
        "Looking up Docs": ("◌", ACCENT),
        "Validating":      ("◌", WARN),
        "Self-Correcting": ("◌", WARN),
        "Fix: Docs":       ("◌", WARN),
        "Applying Fix":    ("◌", WARN),
        "Done":            ("●", SUCCESS),
        "Failed":          ("✗", FAIL),
        "Running":         ("◌", DIM),
    }

    def _render_segment_grid(state: dict[int, str], attempts: dict[int, int], total: int) -> str:
        cells = []
        for i in range(1, total + 1):
            icon, color = _SEGMENT_ICONS.get(state.get(i, "Running"), ("◌", DIM))
            mark = "+" if attempts.get(i, 1) > 1 else ""
            cells.append(f"[{color}]{icon}[/{color}]{mark}")
        return " ".join(cells)

    # ── Start keyboard listener thread ───────────────────────────────
    global _verbose_live, _show_help_overlay
    _verbose_live = False
    _show_help_overlay = False
    _kb_stop = threading.Event()
    _kb_thread = threading.Thread(target=_keyboard_listener, args=(_kb_stop,), daemon=True)
    _kb_thread.start()

    with Progress(
        SpinnerColumn(style="bold cyan"),
        TextColumn("[progress.description]{task.description}", table_column=None),
        BarColumn(bar_width=20, style="bright_black", complete_style="cyan"),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        # Make progress.console available to keyboard listener thread immediately
        global _active_console
        _active_console = progress.console

        main_task = progress.add_task("[bold cyan]Starting...", total=100)
        seg_task = progress.add_task("[dim]  └ Segments[/dim]", total=1, visible=False)

        def _target_pct(stage: str) -> int:
            """Compute target % completion based on current stage + per-segment progress."""
            total = total_segments_expected or max(len(code_segment_state), 1)
            if stage == "plan":
                return max(int(progress.tasks[main_task].completed), 2)
            if stage == "tts":
                return 20
            if stage in ("code", "code_retry"):
                done = sum(1 for s in code_segment_state.values() if s in {"Done", "Failed"})
                return 20 + int(done / total * 30)
            if stage == "render":
                return 80
            if stage == "stitch":
                return 80 + int(stitch_done_count / total * 10)
            if stage == "concat":
                return 95
            if stage == "done":
                return 100
            return int(progress.tasks[main_task].completed)

        try:
            for update in pipeline_generator:
                current_stage = update.get("stage", "unknown")
                if update.get("num_segments"):
                    total_segments_expected = int(update.get("num_segments", 0) or 0)

                status = update.get("status", "")
                segment_id = update.get("segment_id")
                segment_phase = update.get("segment_phase")

                # ── Verbose tool call display (checked on each update) ──────
                if _verbose_live and update.get("tool_call_counts"):
                    tc = update["tool_call_counts"]
                    total_tc = sum(tc.values())
                    if total_tc:
                        progress.console.print(f"  [{DIM}]Tool calls this update: {total_tc}[/{DIM}]")

                # ── Segment state tracking (code + code_retry stages) ──────
                if current_stage in ("code", "code_retry") and segment_id:
                    seg = int(segment_id)
                    pretty_phase = segment_phase_labels.get(
                        segment_phase or "", update.get("segment_status") or status or "Running"
                    )

                    seg_status = update.get("status", "")
                    attempt_match = re.search(r"Attempt (\d+)/", seg_status)
                    if attempt_match:
                        code_segment_attempts[seg] = int(attempt_match.group(1))

                    prev = code_segment_state.get(seg)
                    if prev != pretty_phase:
                        code_segment_state[seg] = pretty_phase
                        attempt_str = (
                            f" (attempt {code_segment_attempts.get(seg, 1)})"
                            if code_segment_attempts.get(seg, 1) > 1
                            else ""
                        )
                        if pretty_phase == "Done":
                            progress.console.print(
                                f"    [{SUCCESS}]✓[/{SUCCESS}] [bold]Segment {seg} completed{attempt_str}[/bold]"
                            )
                        elif pretty_phase == "Failed":
                            progress.console.print(
                                f"    [{FAIL}]✗[/{FAIL}] [bold]Segment {seg} FAILED{attempt_str}[/bold]"
                            )

                # ── Stitch completion tracking ─────────────────────────────
                elif current_stage == "stitch" and "stitched" in status.lower():
                    stitch_done_count += 1

                # ── Plan sub-stage progress nudge ──────────────────────────
                if current_stage == "plan" and status:
                    m = re.search(r"[Ss]tage\s+(\d)/5", status)
                    if m:
                        n = int(m.group(1))
                        cur = int(progress.tasks[main_task].completed)
                        progress.update(main_task, completed=max(cur, 2 * n))

                # ── Update main progress bar ───────────────────────────────
                cur = int(progress.tasks[main_task].completed)
                new_pct = max(cur, _target_pct(current_stage))
                progress.update(main_task, completed=new_pct)

                # ── Update descriptions + seg_task visibility ──────────────
                total_for_display = total_segments_expected or max(len(code_segment_state), 1)
                done_count = sum(1 for s in code_segment_state.values() if s in {"Done", "Failed"})
                ok_count = sum(1 for s in code_segment_state.values() if s == "Done")
                fail_count = sum(1 for s in code_segment_state.values() if s == "Failed")

                if current_stage in ("code", "code_retry"):
                    grid = _render_segment_grid(code_segment_state, code_segment_attempts, total_for_display)
                    fail_tag = f" [{FAIL}]({fail_count}✗)[/{FAIL}]" if fail_count else ""
                    seg_detail = f"{ok_count}/{total_for_display} validated{fail_tag}"
                    progress.update(
                        seg_task,
                        visible=True,
                        total=total_for_display,
                        completed=done_count,
                        description=f"[dim]  └[/dim] {grid}  [{DIM}]{seg_detail}[/{DIM}]",
                    )
                    progress.update(
                        main_task,
                        description=f"[bold cyan]Code[/bold cyan]  [{DIM}]{ok_count}/{total_for_display} segs validated[/{DIM}]",
                    )
                elif status:
                    progress.update(seg_task, visible=False)
                    short_status = _truncate(_clean_status(status), 50)
                    progress.update(
                        main_task,
                        description=f"[bold cyan]{current_stage.title()}[/bold cyan]  [{DIM}]{short_status}[/{DIM}]",
                    )

                if current_stage != last_stage:
                    if last_stage:
                        elapsed = time.perf_counter() - stage_start_time
                        progress.console.print(f"\n  [{SUCCESS}]✓[/{SUCCESS}] [bold]{_format_stage_name(last_stage)}[/bold]  [{DIM}]{_format_duration(elapsed)}[/{DIM}]\n")
                        stages.append((last_stage, "ok", elapsed))
                    last_stage = current_stage
                    stage_start_time = time.perf_counter()
                    
                if update.get("final"):
                    final_video_path = update.get("video_path")
                    output_dir = update.get("project_dir", output_dir)
                    if "error" in update and update["error"]:
                        elapsed = time.perf_counter() - stage_start_time
                        stages.append((last_stage, "failed", elapsed))
                        progress.console.print(f"\n  [{FAIL}]✗[/{FAIL}] [bold]{_format_stage_name(last_stage)}[/bold]  [{DIM}]{_format_duration(elapsed)}[/{DIM}]\n")
                        _kb_stop.set()
                        _print_error("Pipeline failed", update["error"])
                        return
        except Exception as e:
            _kb_stop.set()
            _active_console = None
            _print_error(f"Unexpected pipeline error: {str(e)}")
            return
        finally:
            _kb_stop.set()
            _active_console = None

    if last_stage and last_stage != "done":
        elapsed = time.perf_counter() - stage_start_time
        console.print(f"\n  [{SUCCESS}]✓[/{SUCCESS}] [bold]{_format_stage_name(last_stage)}[/bold]  [{DIM}]{_format_duration(elapsed)}[/{DIM}]\n")
        stages.append((last_stage, "ok", elapsed))

    if _out_stages is not None:
        _out_stages.extend(stages)

    if not final_video_path:
        _print_error("Pipeline completed but no final video was produced.")
        return

    if getattr(args, "output_format", "text") == "json":
        import json as _json
        result = {
            "status": "complete",
            "concept": concept,
            "video_path": os.path.abspath(final_video_path),
            "stages": [{"name": n, "status": s, "elapsed": e} for n, s, e in stages],
        }
        print(_json.dumps(result), flush=True)
        return

    _set_terminal_title("paper2manim ✓")
    print_pipeline_summary(stages)
    _print_output(final_video_path)
    _notify("complete", f"Video for '{concept}' is ready!")
    _open_file(final_video_path)


REPL_COMMANDS: dict[str, str] = {
    "/help":      "Show available commands",
    "/settings":  "Show current settings (quality, model, theme)",
    "/workspace": "Open the workspace dashboard",
    "/status":    "Show last pipeline summary",
    "/clear":     "Clear the screen",
    "/quit":      "Exit interactive mode",
}


def _repl_help() -> None:
    table = Table(box=box.MINIMAL, show_header=False, padding=(0, 2))
    table.add_column(style=ACCENT_B)
    table.add_column(style=DIM)
    for cmd, desc in REPL_COMMANDS.items():
        table.add_row(cmd, desc)
    console.print()
    console.print("  [bold]Commands[/bold]")
    console.print(table)
    console.print(f"  [{DIM}]Or type any concept to generate a video.[/{DIM}]\n")


def _repl_settings(args: argparse.Namespace) -> None:
    quality = getattr(args, "quality", "high")
    model = getattr(args, "model", None) or MODEL_TAG
    theme = getattr(args, "theme", "dark")
    verbose = "on" if getattr(args, "verbose", False) else "off"
    skip_audio = "yes" if getattr(args, "skip_audio", False) else "no"
    console.print()
    console.print(Panel(
        f"  Quality    : [bold]{quality}[/bold]\n"
        f"  Model      : [bold]{model}[/bold]\n"
        f"  Theme      : [bold]{theme}[/bold]\n"
        f"  Verbose    : [bold]{verbose}[/bold]\n"
        f"  Skip audio : [bold]{skip_audio}[/bold]",
        title="[bold]Current Settings[/bold]",
        border_style=ACCENT,
        padding=(0, 2),
    ))
    console.print()


def interactive_repl(args: argparse.Namespace) -> None:
    """Interactive command-line REPL with /command support."""
    console.print()
    console.print("  [bold]Interactive Mode[/bold]")
    console.print(f"  [{DIM}]Type a concept or /help for commands. Ctrl+C to quit.[/{DIM}]\n")

    last_stages: list[tuple[str, str, float]] = []

    while True:
        try:
            raw = Prompt.ask(f"  [{ACCENT}]>[/{ACCENT}]")
            raw = raw.strip()
            if not raw:
                continue

            if raw.startswith("/"):
                cmd = raw.lower().split()[0]

                if cmd in ("/help", "/?"):
                    _repl_help()
                elif cmd == "/settings":
                    _repl_settings(args)
                elif cmd == "/workspace":
                    selected = manage_workspace()
                    if selected:
                        project_state = load_project(selected)
                        concept = project_state.get("concept", "") if project_state else ""
                        if concept:
                            console.print(f"\n  [{SUCCESS}]✓[/{SUCCESS}]  Resuming: [bold]{concept}[/bold]")
                            last_stages = []
                            run_pipeline_for_concept(concept, args, output_dir=selected, _out_stages=last_stages)
                elif cmd == "/status":
                    if last_stages:
                        print_pipeline_summary(last_stages)
                    else:
                        console.print(f"  [{WARN}]No pipeline has run yet in this session.[/{WARN}]")
                elif cmd == "/clear":
                    console.clear()
                elif cmd in ("/quit", "/exit", "/q"):
                    break
                else:
                    console.print(f"  [{WARN}]Unknown command: {cmd}. Type /help for commands.[/{WARN}]")
                continue

            concept = raw
            if not os.getenv("GEMINI_API_KEY"):
                console.print()
                _print_error(
                    "GEMINI_API_KEY not found in environment.",
                    "Set it in .env as  GEMINI_API_KEY=your_key_here",
                )
                continue

            questionnaire_answers = _run_questionnaire(concept)
            last_stages = []
            run_pipeline_for_concept(concept, args, questionnaire_answers=questionnaire_answers, _out_stages=last_stages)
            console.print()

        except (KeyboardInterrupt, EOFError, SystemExit):
            console.print(f"\n  [{DIM}]Exiting interactive mode.[/{DIM}]")
            break


def _open_file(path: str) -> None:
    abs_path = os.path.abspath(path)
    if sys.platform == "darwin":
        os.system(f"open -a 'QuickTime Player' '{abs_path}'")
    elif os.name == "nt":
        os.system(f'start "" "{abs_path}"')
    else:
        os.system(f"xdg-open '{abs_path}'")


if __name__ == "__main__":
    main()

