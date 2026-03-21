#!/usr/bin/env python3
"""Paper2Manim CLI — modern terminal experience."""

import argparse
import logging
import os
import re
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
DIM = "dim"
SUCCESS = "green"
FAIL = "red"
WARN = "yellow"
MUTED = "bright_black"

VERSION = "0.1.0"
MODEL_TAG = "claude-opus-4.6 + gemini-3.1-pro"

LOGO = f"""[bold blue]
    ╔═══════════════════════════════════════════════╗
    ║   [bold white]paper2manim[/bold white]  [dim]v{VERSION}[/dim]                       ║
    ╚═══════════════════════════════════════════════╝[/bold blue]"""


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
    console.print(f"  [{MUTED}]{branch}[/{MUTED}] [{SUCCESS}]OK[/{SUCCESS}] [{DIM}]{text}[/{DIM}]")


def _log_stage_done(name: str, elapsed: float):
    label = _format_stage_name(name)
    console.print(f"  [{SUCCESS}]OK[/{SUCCESS}]  [bold]{label:<24}[/bold]  [{DIM}]{_format_duration(elapsed)}[/{DIM}]")


def _log_stage_fail(name: str, elapsed: float):
    label = _format_stage_name(name)
    console.print(f"  [{FAIL}]ERR[/{FAIL}]  [bold]{label:<24}[/bold]  [{DIM}]{_format_duration(elapsed)}[/{DIM}]")


def _log_stage_header(name: str):
    console.print()
    console.print(f"  [{ACCENT}]*[/{ACCENT}] [bold]{name}[/bold] [{DIM}]…[/{DIM}]")


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
            "  paper2manim --skip-audio 'Linear Algebra: Dot Products'\n"
            "  paper2manim --max-retries 5 --verbose"
        ),
    )
    
    parser.add_argument("concept", nargs="*", help="Concept/topic to visualize")
    
    options = parser.add_argument_group("Options")
    options.add_argument(
        "--max-retries", type=int, default=3,
        help="Maximum self-correction attempts for Manim code (default: 3)",
    )
    options.add_argument("--skip-audio", action="store_true",
                        help="Skip TTS and stitching; render animation only")
    options.add_argument("--lite", action="store_true",
                        help="Use the faster, less detailed pipeline")
    options.add_argument("--verbose", action="store_true",
                        help="Show detailed diagnostics for failures")
    
    workspace = parser.add_argument_group("Workspace Management")
    workspace.add_argument("--workspace", action="store_true", 
                        help="Open the interactive workspace dashboard")
    workspace.add_argument("--resume", type=str, metavar="DIR",
                        help="Path to an existing output directory to resume")
    return parser.parse_args()


# ── Pipeline summary ─────────────────────────────────────────────────
def print_pipeline_summary(stages: list[tuple[str, str, float]]) -> None:
    table = Table(
        box=None,
        show_edge=False,
        show_header=True,
        header_style=f"bold {ACCENT}",
        padding=(0, 1),
        pad_edge=False,
    )
    table.add_column("Status", width=8)
    table.add_column("Stage", style="bold")
    table.add_column("Duration", justify="right", style=DIM)

    total = 0.0
    for name, status, elapsed in stages:
        total += elapsed
        icon = f"[{SUCCESS}]OK[/{SUCCESS}]" if status == "ok" else f"[{FAIL}]ERR[/{FAIL}]"
        table.add_row(icon, _format_stage_name(name), f"{_format_duration(elapsed)}")

    table.add_section()
    table.add_row("", "[bold]Total[/bold]", f"[bold]{total:.1f}s[/bold]")
    console.print()
    console.print("  [bold]Pipeline Summary[/bold]")
    console.print(table)
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
def _print_error(message: str, detail: str | None = None) -> None:
    body = f"[{FAIL}]{message}[/{FAIL}]"
    if detail:
        body += f"\n\n[{DIM}]{escape(detail)}[/{DIM}]"
    console.print(Panel(body, title="[bold red]Error[/bold red]", border_style=FAIL, padding=(1, 2), width=min(console.width, 120)))
    _notify("error")


# ── Success output ────────────────────────────────────────────────────
def _print_output(path: str) -> None:
    abs_path = os.path.abspath(path)
    console.print(Panel(
        f"[bold]{abs_path}[/bold]",
        title=f"[{SUCCESS}]Output ready[/{SUCCESS}]",
        title_align="left",
        border_style=SUCCESS,
        padding=(0, 2),
    ))


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
        console.print(LOGO)
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
                        console.print(f"  [{SUCCESS}]OK[/{SUCCESS}]  Removed {removed} stale entries.")
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
                console.print(f"  [{SUCCESS}]OK[/{SUCCESS}]  Removed {removed} stale entries.")
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
                    if Confirm.ask(f"  [{FAIL}]ERR[/{FAIL}] Confirm delete for [bold]{concept_name}[/bold]?", default=False):
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
    if not args.workspace:
        console.print()
        console.print(LOGO)
        console.print()

    output_dir = None
    project_state = None
    concept = ""

    # ── Workspace / Resume Handling ───────────────────────────────
    if args.workspace:
        if not os.getenv("GEMINI_API_KEY") or not os.getenv("ANTHROPIC_API_KEY"):
            console.print()
            _print_error(
                "GEMINI_API_KEY and/or ANTHROPIC_API_KEY not found in environment.",
                "Set them in .env:  GEMINI_API_KEY=...  ANTHROPIC_API_KEY=...",
            )
            sys.exit(1)
        selected_dir = manage_workspace()
        if not selected_dir:
            sys.exit(0)
        output_dir = selected_dir
        project_state = load_project(output_dir)
        if not project_state:
            _print_error("Failed to load project state", output_dir)
            sys.exit(1)
        concept = project_state.get("concept", "")
        console.print(f"\n  [{SUCCESS}]OK[/{SUCCESS}]  Resuming project: [bold]{concept}[/bold]")
        run_pipeline_for_concept(concept, args, output_dir=output_dir)
        
    elif args.resume:
        if not os.getenv("GEMINI_API_KEY") or not os.getenv("ANTHROPIC_API_KEY"):
            console.print()
            _print_error(
                "GEMINI_API_KEY and/or ANTHROPIC_API_KEY not found in environment.",
                "Set them in .env:  GEMINI_API_KEY=...  ANTHROPIC_API_KEY=...",
            )
            sys.exit(1)
        output_dir = os.path.abspath(args.resume)
        project_state = load_project(output_dir)
        if not project_state:
            _print_error(f"Cannot resume: {output_dir} does not contain a valid project state.")
            sys.exit(1)
        concept = project_state.get("concept", "")
        console.print(f"\n  [{SUCCESS}]OK[/{SUCCESS}]  Resuming project: [bold]{concept}[/bold]")
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
    """Run an interactive questionnaire with hardcoded + dynamically generated questions.

    Always asks video length and target audience. Generates 2-3 concept-specific
    questions via Claude Sonnet and presents them with arrow-key selection.
    """
    import json
    import questionary
    from questionary import Style as QStyle

    # Style visible on dark terminals
    q_style = QStyle([
        ("qmark", "fg:cyan bold"),
        ("question", "fg:white bold"),
        ("pointer", "fg:cyan bold"),          # » marker
        ("highlighted", "fg:cyan bold"),       # currently focused option
        ("selected", "fg:cyan"),               # after selection
        ("answer", "fg:cyan bold"),            # confirmed answer
        ("text", "fg:white"),                  # option text
    ])

    answers: dict = {}
    console.print()
    console.print(f"  [{ACCENT}]?[/{ACCENT}] [bold]Let's customize your video for:[/bold] {escape(concept)}")
    console.print()

    # ── Hardcoded questions ────────────────────────────────────────
    answers["video_length"] = questionary.select(
        "Video length:",
        choices=["Short (1-2 min)", "Medium (3-5 min)", "Long (5-10 min)"],
        default="Medium (3-5 min)",
        style=q_style,
        qmark="  ?",
    ).ask()

    answers["target_audience"] = questionary.select(
        "Target audience:",
        choices=["High school student", "Undergraduate", "Graduate / Professional", "General audience"],
        default="Undergraduate",
        style=q_style,
        qmark="  ?",
    ).ask()

    # ── Dynamic questions via Claude Sonnet ──────────────────────
    try:
        import anthropic as _anthropic
        client = _anthropic.Anthropic()
        prompt = (
            f"You are helping create an educational math video about: \"{concept}\"\n"
            f"Target audience: {answers['target_audience']}\n"
            f"Video length: {answers['video_length']}\n\n"
            "Generate exactly 2 specific multiple-choice questions that would help customize "
            "this video. Each question should be relevant to the concept and help decide what "
            "content to include. Return ONLY valid JSON in this format:\n"
            '[\n'
            '  {"question": "...", "options": ["option1", "option2", "option3"]},\n'
            '  {"question": "...", "options": ["option1", "option2", "option3"]}\n'
            ']\n'
            "Keep questions concise. Keep options short (under 8 words each). "
            "Make questions specific to the topic, not generic."
        )
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = re.sub(r"```(?:json)?\s*\n?", "", raw).strip().rstrip("`").strip()
        dynamic_questions = json.loads(raw)

        answers["custom_preferences"] = {}
        for q in dynamic_questions:
            question_text = q.get("question", "")
            options = q.get("options", [])
            if not question_text or not options:
                continue

            selected = questionary.select(
                question_text,
                choices=options,
                style=q_style,
                qmark="  ?",
            ).ask()
            if selected:
                answers["custom_preferences"][question_text] = selected

    except Exception as e:
        # If dynamic generation fails, continue without custom questions
        console.print(f"  [{DIM}]Skipping custom questions ({e})[/{DIM}]")
        answers.setdefault("custom_preferences", {})

    _notify("questionnaire_done")
    console.print(f"  [{SUCCESS}]OK[/{SUCCESS}] Preferences saved. Starting pipeline...\n")
    return answers


def run_pipeline_for_concept(concept: str, args: argparse.Namespace, output_dir: str | None = None, questionnaire_answers: dict | None = None) -> None:
    mode_label = "Lite" if args.lite else "Pro"
    console.print(f"  [bright_black]{'─' * 62}[/bright_black]")
    console.print(
        f"  [dim]Concept:[/dim] {escape(concept)}   [dim]Pipeline:[/dim] {mode_label}   "
        f"[dim]Model:[/dim] {MODEL_TAG}"
    )
    console.print("  [dim]Status:[/dim] Running segmented pipeline")
    console.print()

    stages: list[tuple[str, str, float]] = []

    # ── Segmented Pipeline Runner ─────────────────────────────────
    pipeline_generator = run_segmented_pipeline(concept, output_base="output", max_retries=args.max_retries, is_lite=args.lite, questionnaire_answers=questionnaire_answers)
    
    final_video_path = None
    total_segments_expected = 0
    
    last_stage = None
    stage_start_time = time.perf_counter()
    segment_phase_labels = {
        "generate": "Generating Initial Script",
        "docs": "Looking up Docs",
        "execute": "Rendering Draft (-ql)",
        "self_correct": "Self-Correcting",
        "fix_docs": "Fix: Looking up Docs",
        "apply_fix": "Applying Fix",
        "done": "Done",
        "failed": "Failed",
        "running": "Running",
    }
    code_segment_state: dict[int, str] = {}
    code_segment_attempts: dict[int, int] = {}
    
    with Progress(
        SpinnerColumn(style="bold cyan"),
        TextColumn("[progress.description]{task.description}", table_column=None),
        BarColumn(bar_width=20, style="bright_black", complete_style="cyan"),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        
        main_task = progress.add_task("[bold cyan]Starting...", total=100)
        
        try:
            for update in pipeline_generator:
                current_stage = update.get("stage", "unknown")
                if update.get("num_segments"):
                    total_segments_expected = int(update.get("num_segments", 0) or 0)
                
                # Update progress based on the stage mapping heuristics
                stage_weights = {
                    "plan": 10,
                    "tts": 20,
                    "code": 50,
                    "render": 80,
                    "stitch": 90,
                    "concat": 95,
                    "done": 100,
                }
                
                target_pct = stage_weights.get(current_stage, progress.tasks[main_task].percentage)
                progress.update(main_task, completed=target_pct)

                status = update.get("status", "")
                segment_id = update.get("segment_id")
                segment_phase = update.get("segment_phase")
                if current_stage == "code" and segment_id:
                    seg = int(segment_id)
                    pretty_phase = segment_phase_labels.get(segment_phase or "", update.get("segment_status") or status or "Running")

                    # Track attempt number from status messages like "[Seg 3] Attempt 2/4: ..."
                    seg_status = update.get("status", "")
                    attempt_match = re.search(r"Attempt (\d+)/", seg_status)
                    if attempt_match:
                        code_segment_attempts[seg] = int(attempt_match.group(1))

                    prev = code_segment_state.get(seg)
                    if prev != pretty_phase:
                        code_segment_state[seg] = pretty_phase
                        attempt_str = f" (attempt {code_segment_attempts.get(seg, 1)})" if code_segment_attempts.get(seg, 1) > 1 else ""

                        # Prominent completion/failure line
                        if pretty_phase == "Done":
                            progress.console.print(
                                f"  [bold {SUCCESS}]v Segment {seg} completed{attempt_str}[/bold {SUCCESS}]"
                            )
                        elif pretty_phase == "Failed":
                            progress.console.print(
                                f"  [bold {FAIL}]x Segment {seg} FAILED{attempt_str}[/bold {FAIL}]"
                            )
                        else:
                            progress.console.print(
                                f"  [{MUTED}]|[/{MUTED}] [bold cyan]Segment {seg}[/bold cyan]: [{DIM}]{pretty_phase}{attempt_str}[/{DIM}]"
                            )

                    done_count = sum(1 for s in code_segment_state.values() if s in {"Done", "Failed"})
                    ok_count = sum(1 for s in code_segment_state.values() if s == "Done")
                    fail_count = sum(1 for s in code_segment_state.values() if s == "Failed")
                    total_for_display = total_segments_expected or max(len(code_segment_state), 1)

                    # Build compact status: "3/7 done (2 ok, 1 failed) | Seg 4: Generating, Seg 5: Self-Correcting"
                    in_progress_parts = [
                        f"Seg {s}: {st}" for s, st in sorted(code_segment_state.items())
                        if st not in {"Done", "Failed"}
                    ]
                    detail = f"{done_count}/{total_for_display} done"
                    if fail_count:
                        detail += f" [{FAIL}]({fail_count} failed)[/{FAIL}]"
                    if in_progress_parts:
                        detail += f" | {', '.join(in_progress_parts[:3])}"

                    progress.update(
                        main_task,
                        description=(
                            f"[bold cyan]Code[/bold cyan]  [dim]{_truncate(detail, 50)}[/dim]"
                        ),
                    )
                elif status:
                    short_status = _truncate(status, 60)
                    progress.update(main_task, description=f"[bold cyan]{current_stage.title()}[/bold cyan]  [dim]{short_status}[/dim]")
                    progress.console.print(f"  [{MUTED}]├─[/{MUTED}] [{SUCCESS}]OK[/{SUCCESS}] [{DIM}]{_truncate(status)}[/{DIM}]")

                if current_stage != last_stage:
                    if last_stage:
                        elapsed = time.perf_counter() - stage_start_time
                        progress.console.print(f"\n  [{SUCCESS}]OK[/{SUCCESS}]  [bold]{_format_stage_name(last_stage):<24}[/bold]  [{DIM}]{_format_duration(elapsed)}[/{DIM}]\n")
                        stages.append((last_stage, "ok", elapsed))
                    last_stage = current_stage
                    stage_start_time = time.perf_counter()
                    
                if update.get("final"):
                    final_video_path = update.get("video_path")
                    output_dir = update.get("project_dir", output_dir)
                    if "error" in update and update["error"]:
                        elapsed = time.perf_counter() - stage_start_time
                        stages.append((last_stage, "failed", elapsed))
                        progress.console.print(f"\n  [{FAIL}]ERR[/{FAIL}]  [bold]{_format_stage_name(last_stage):<24}[/bold]  [{DIM}]{_format_duration(elapsed)}[/{DIM}]\n")
                        _print_error("Pipeline failed", update["error"])
                        return
        except Exception as e:
            _print_error(f"Unexpected pipeline error: {str(e)}")
            return

    if last_stage and last_stage != "done":
        elapsed = time.perf_counter() - stage_start_time
        console.print(f"\n  [{SUCCESS}]OK[/{SUCCESS}]  [bold]{_format_stage_name(last_stage):<24}[/bold]  [{DIM}]{_format_duration(elapsed)}[/{DIM}]\n")
        stages.append((last_stage, "ok", elapsed))

    if not final_video_path:
        _print_error("Pipeline completed but no final video was produced.")
        return

    print_pipeline_summary(stages)
    _print_output(final_video_path)
    _notify("complete", f"Video for '{concept}' is ready!")
    _open_file(final_video_path)


def interactive_repl(args: argparse.Namespace) -> None:
    """Interactive command-line loop."""
    console.print()
    console.print("  [bold]Interactive Mode[/bold]")
    console.print("  Type your prompt to generate a video, or press Ctrl+C to quit.\n")
    
    while True:
        try:
            concept = Prompt.ask(f"  [{ACCENT}]>[/{ACCENT}] [bold]What concept would you like to visualize?[/bold]")
            concept = concept.strip()
            if not concept:
                continue
            
            if not os.getenv("GEMINI_API_KEY"):
                console.print()
                _print_error(
                    "GEMINI_API_KEY not found in environment.",
                    "Set it in .env as  GEMINI_API_KEY=your_key_here",
                )
                continue
                
            questionnaire_answers = _run_questionnaire(concept)
            run_pipeline_for_concept(concept, args, questionnaire_answers=questionnaire_answers)
            console.print()

        except (KeyboardInterrupt, EOFError):
            console.print("\n  [dim]Exiting interactive mode.[/dim]")
            break


def _open_file(path: str) -> None:
    abs_path = os.path.abspath(path)
    if sys.platform == "darwin":
        os.system(f"open '{abs_path}'")
    elif os.name == "nt":
        os.system(f'start "" "{abs_path}"')
    else:
        os.system(f"xdg-open '{abs_path}'")


if __name__ == "__main__":
    main()

