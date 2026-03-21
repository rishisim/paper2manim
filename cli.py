#!/usr/bin/env python3
"""Paper2Manim CLI — modern terminal experience."""

import argparse
import os
import sys
import time
import itertools
import threading
from typing import Callable

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.markup import escape
from rich.text import Text
from rich.columns import Columns
from rich.rule import Rule
from rich import box

from agents.coder import run_coder_agent
from agents.planner import plan_segmented_storyboard, plan_segmented_storyboard_lite
from agents.pipeline import run_segmented_pipeline
from utils.media_assembler import stitch_video_and_audio
from utils.tts_engine import generate_voiceover
from utils.project_state import (
    create_project, load_project, save_project, 
    mark_stage_done, is_stage_done, list_all_projects, delete_project,
    mark_project_complete, calculate_progress,
)

load_dotenv()
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
MODEL_TAG = "gemini-3.1-pro"

LOGO = r"""[bold blue]
  ╔═══════════════════════════════════════════════╗
  ║   [bold white]paper2manim[/bold white]                                ║
  ╚═══════════════════════════════════════════════╝[/bold blue]"""


# ── Spinner helper ────────────────────────────────────────────────────
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class _Spinner:
    """Tiny non-blocking spinner that writes to the current line."""

    def __init__(self, text: str):
        self._text = text
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def update(self, text: str):
        self._text = text

    def _run(self):
        frames = itertools.cycle(SPINNER_FRAMES)
        while not self._stop.is_set():
            frame = next(frames)
            sys.stderr.write(f"\r  \033[34m{frame}\033[0m {self._text}\033[K")
            sys.stderr.flush()
            self._stop.wait(0.08)
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join()


# ── Logging helpers ───────────────────────────────────────────────────
def _log_step(text: str, last: bool = False):
    branch = "└─" if last else "├─"
    console.print(f"  [{MUTED}]{branch}[/{MUTED}] [{SUCCESS}]OK[/{SUCCESS}] [{DIM}]{text}[/{DIM}]")


def _log_stage_done(name: str, elapsed: float):
    console.print(f"  [{SUCCESS}]OK[/{SUCCESS}] [bold]{name}[/bold]  [{DIM}]{elapsed:.1f}s[/{DIM}]")


def _log_stage_fail(name: str, elapsed: float):
    console.print(f"  [{FAIL}]ERR[/{FAIL}] [bold]{name}[/bold]  [{DIM}]{elapsed:.1f}s[/{DIM}]")


def _log_stage_header(name: str):
    console.print()
    console.print(f"  [{ACCENT}]*[/{ACCENT}] [bold]{name}[/bold] [{DIM}]…[/{DIM}]")


# ── Stage runner ──────────────────────────────────────────────────────
def run_stage(stage_name: str, fn: Callable, *args, **kwargs) -> tuple[dict, float]:
    """Run a generator-based pipeline stage with tree-style logging."""
    started = time.perf_counter()
    _log_stage_header(stage_name)

    result = None
    steps: list[str] = []
    spinner = _Spinner("starting…")
    spinner.start()

    try:
        for update in fn(*args, **kwargs):
            status_text = update.get("status")
            if status_text:
                if steps:
                    spinner.stop()
                    _log_step(steps[-1])
                    spinner.start()
                steps.append(status_text)
                spinner.update(status_text)

            if update.get("final"):
                result = update
                break
    finally:
        spinner.stop()

    if steps:
        _log_step(steps[-1], last=True)

    elapsed = time.perf_counter() - started
    return result, elapsed


# ── CLI args ──────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="paper2manim",
        description="Generate an educational video from a concept.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  paper2manim \"The Chain Rule\"\n"
            "  paper2manim --skip-audio \"Linear Algebra: Dot Products\"\n"
            "  paper2manim --max-retries 5 --verbose"
        ),
    )
    parser.add_argument("concept", nargs="*", help="Concept/topic to visualize")
    parser.add_argument(
        "--max-retries", type=int, default=3,
        help="Maximum self-correction attempts for Manim code (default: 3)",
    )
    parser.add_argument("--verbose", action="store_true",
                        help="Show detailed diagnostics for failures")
    parser.add_argument("--skip-audio", action="store_true",
                        help="Skip TTS and stitching; render animation only")
    parser.add_argument("--lite", action="store_true",
                        help="Use the faster, less detailed original pipeline instead of the Math-To-Manim structured pipeline")
    parser.add_argument("--workspace", action="store_true", 
                        help="Open the interactive workspace dashboard to view, resume or delete projects.")
    parser.add_argument("--resume", type=str, metavar="DIR",
                        help="Path to an existing project output directory to resume from.")
    return parser.parse_args()


# ── Pipeline summary ─────────────────────────────────────────────────
def print_pipeline_summary(stages: list[tuple[str, str, float]]) -> None:
    console.print()
    table = Table(
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold",
        padding=(0, 2),
        title="[bold]Pipeline Summary[/bold]",
        title_style="",
        min_width=40,
    )
    table.add_column("", width=3, justify="center")
    table.add_column("Stage", style="bold")
    table.add_column("Time", justify="right", style=DIM)

    total = 0.0
    for name, status, elapsed in stages:
        total += elapsed
        icon = f"[{SUCCESS}]OK[/{SUCCESS}]" if status == "ok" else f"[{FAIL}]ERR[/{FAIL}]"
        table.add_row(icon, name, f"{elapsed:.1f}s")

    table.add_section()
    table.add_row("", "[bold]Total[/bold]", f"[bold]{total:.1f}s[/bold]")
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
    lines.append(f"{'Status':<8} {'Stage':<25} {'Time':>8}")
    lines.append("-" * 50)
    for name, status, elapsed in stages:
        tag = "OK" if status == "ok" else "ERR"
        lines.append(f"{tag:<8} {name:<25} {elapsed:>7.1f}s")
    lines.append("-" * 50)
    lines.append(f"{'':8} {'Total':<25} {total:>7.1f}s")
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
    console.print(Panel(body, title="[bold red]Error[/bold red]", border_style=FAIL, padding=(1, 2)))


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
        console.print("\n  [bold]🗂️  Project Workspace[/bold]")
        console.print(f"  [{DIM}]Resume or delete existing video projects.[/{DIM}]\n")
        
        projects = list_all_projects("output")
        if not projects:
            console.print(f"  [{WARN}]No projects found in the workspace yet.[/{WARN}]\n")
            return None

        table = Table(
            box=box.SIMPLE_HEAVY,
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
        
        choice = Prompt.ask(f"  [{ACCENT}]>[/{ACCENT}] Select project ID to manage, or [dim](q)[/dim]uit", default="q")
        if choice.lower() in ("q", "quit", "exit"):
            return None
            
        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(projects):
                target_dir, state = projects[choice_idx]
                concept_name = state.get("concept", target_dir)
                
                action = Prompt.ask(
                    f"  [{ACCENT}]>[/{ACCENT}] Project: [bold]{concept_name}[/bold]. Choose action: ([bold]v[/bold])iew info, ([bold]r[/bold])esume, ([bold]d[/bold])elete, or ([bold]c[/bold])ancel", 
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
                    if Confirm.ask(f"  [{FAIL}]![/{FAIL}] Are you sure you want to delete [bold]{concept_name}[/bold]?", default=False):
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

    # ── API key check ─────────────────────────────────────────────
    if not os.getenv("GEMINI_API_KEY"):
        console.print()
        _print_error(
            "GEMINI_API_KEY not found in environment.",
            "Set it in .env as  GEMINI_API_KEY=your_key_here",
        )
        sys.exit(1)

    os.makedirs("output", exist_ok=True)

    # ── Banner ────────────────────────────────────────────────────
    if not args.workspace:
        console.print(LOGO)
        console.print()

    output_dir = None
    project_state = None
    concept = ""
    concept_slug = ""

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
        concept_slug = project_state.get("slug", os.path.basename(output_dir))
        console.print(f"\n  [{SUCCESS}]✔[/{SUCCESS}] Resuming project: [bold]{concept}[/bold]")
        
    elif args.resume:
        output_dir = os.path.abspath(args.resume)
        project_state = load_project(output_dir)
        if not project_state:
            _print_error(f"Cannot resume: {output_dir} does not contain a valid project state.")
            sys.exit(1)
        concept = project_state.get("concept", "")
        concept_slug = project_state.get("slug", os.path.basename(output_dir))
        console.print(f"\n  [{SUCCESS}]✔[/{SUCCESS}] Resuming project: [bold]{concept}[/bold]")

    else:
        # ── Concept input ─────────────────────────────────────────────
        concept = " ".join(args.concept).strip()
        if not concept:
            concept = Prompt.ask(f"  [{ACCENT}]>[/{ACCENT}] [bold]What concept would you like to visualize?[/bold]")
            console.print()

        import re
        import time
        from google import genai
        try:
            client = genai.Client()
            response = client.models.generate_content(
                model="gemini-flash-latest",
                contents=f"Generate a short (2-4 words), clean, snake_case filename slug for this topic: {concept}. Return ONLY the snake_case string, nothing else."
            )
            concept_slug = response.text.strip().lower()
            # Failsafe local sanitize
            concept_slug = re.sub(r'[^\w\s-]', '', concept_slug).strip()
            concept_slug = re.sub(r'[-\s]+', '_', concept_slug)
            if not concept_slug:
                concept_slug = "video"
        except Exception:
            concept_slug = "video"
            
        output_dir = os.path.join("output", f"{concept_slug}_{int(time.time())}")
        project_state = create_project(output_dir, concept, concept_slug)

    console.print(Rule(style=MUTED))

    stages: list[tuple[str, str, float]] = []

    # ── Segmented Pipeline Runner ─────────────────────────────────
    _log_stage_header(f"Running {'Lite' if args.lite else 'Pro'} Segmented Pipeline")
    pipeline_generator = run_segmented_pipeline(concept, output_base="output", max_retries=args.max_retries, is_lite=args.lite)
    
    final_video_path = None
    output_dir = None
    
    spinner = _Spinner("starting…")
    spinner.start()
    
    last_stage = None
    stage_start_time = time.perf_counter()
    
    try:
        for update in pipeline_generator:
            current_stage = update.get("stage", "unknown")
            if current_stage != last_stage:
                if last_stage:
                    elapsed = time.perf_counter() - stage_start_time
                    spinner.stop()
                    _log_stage_done(f"Stage: {last_stage}", elapsed)
                    stages.append((last_stage, "ok", elapsed))
                    spinner.start()
                last_stage = current_stage
                stage_start_time = time.perf_counter()

            status = update.get("status", "")
            if status:
                spinner.update(status)
                
            if update.get("final"):
                final_video_path = update.get("video_path")
                output_dir = update.get("project_dir", output_dir)
                if "error" in update and update["error"]:
                    spinner.stop()
                    elapsed = time.perf_counter() - stage_start_time
                    _log_stage_fail(f"Stage: {last_stage}", elapsed)
                    stages.append((last_stage, "failed", elapsed))
                    _print_error("Pipeline failed", update["error"])
                    sys.exit(1)
    finally:
        spinner.stop()

    if last_stage:
        elapsed = time.perf_counter() - stage_start_time
        _log_stage_done(f"Stage: {last_stage}", elapsed)
        stages.append((last_stage, "ok", elapsed))

    if not final_video_path:
        _print_error("Pipeline completed but no final video was produced.")
        sys.exit(1)

    print_pipeline_summary(stages)
    _print_output(final_video_path)
    _open_file(final_video_path)


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
