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
from agents.planner import plan_video_concept
from utils.media_assembler import stitch_video_and_audio
from utils.tts_engine import generate_voiceover

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
    console.print(LOGO)
    console.print()

    # ── Concept input ─────────────────────────────────────────────
    concept = " ".join(args.concept).strip()
    if not concept:
        concept = Prompt.ask(f"  [{ACCENT}]>[/{ACCENT}] [bold]What concept would you like to visualize?[/bold]")
        console.print()

    console.print(Rule(style=MUTED))

    stages: list[tuple[str, str, float]] = []

    # ── Planning ──────────────────────────────────────────────────
    storyboard = None
    previous_storyboard = None
    feedback = None
    plan_elapsed_total = 0.0

    while True:
        try:
            result, elapsed = run_stage(
                "Planning storyboard",
                plan_video_concept,
                concept,
                previous_storyboard=previous_storyboard,
                feedback=feedback,
            )
            plan_elapsed_total += elapsed
            if result and "error" in result:
                _log_stage_fail("Planning storyboard", plan_elapsed_total)
                stages.append(("Plan", "failed", plan_elapsed_total))
                print_pipeline_summary(stages)
                _print_error(result["error"])
                sys.exit(1)
            storyboard = result.get("storyboard") if result else None
        except Exception as exc:
            _log_stage_fail("Planning storyboard", plan_elapsed_total)
            stages.append(("Plan", "failed", plan_elapsed_total))
            print_pipeline_summary(stages)
            _print_error(str(exc))
            sys.exit(1)

        _log_stage_done("Planning storyboard", plan_elapsed_total)
        console.print()

        # Show storyboard in panels
        _print_storyboard(storyboard)

        if storyboard.get("clarifying_questions"):
            console.print()
            console.print(Panel(
                "\n".join(f"  [white]•[/white] {q}" for q in storyboard["clarifying_questions"]),
                title="[bold yellow]Clarifying Questions[/bold yellow]",
                title_align="left",
                border_style=WARN,
                padding=(1, 2),
            ))

        ok = Confirm.ask(f"  [{ACCENT}]?[/{ACCENT}] [bold]Proceed with this storyboard?[/bold]", default=True)
        if ok:
            break

        feedback = Prompt.ask(f"  [{ACCENT}]>[/{ACCENT}] [bold]What should be changed?[/bold]")
        previous_storyboard = storyboard
        console.print()

    stages.append(("Plan", "ok", plan_elapsed_total))

    # ── Voiceover ─────────────────────────────────────────────────
    audio_path = os.path.join("output", "voiceover.wav")
    if not args.skip_audio:
        tts_result, elapsed = run_stage(
            "Generating voiceover",
            generate_voiceover,
            storyboard["audio_script"],
            audio_path,
        )
        if not tts_result or not tts_result.get("success"):
            _log_stage_fail("Generating voiceover", elapsed)
            stages.append(("Voiceover", "failed", elapsed))
            print_pipeline_summary(stages)
            detail = tts_result.get("error") if args.verbose and tts_result else None
            _print_error("Voiceover generation failed.", detail)
            sys.exit(1)
        _log_stage_done("Generating voiceover", elapsed)
        audio_path = tts_result.get("audio_path", audio_path)
        stages.append(("Voiceover", "ok", elapsed))

    # ── Code Generation + Render ──────────────────────────────────
    _log_stage_header("Generating Manim code")
    code_started = time.perf_counter()
    final_video_path = None
    final_error = None
    coder_steps: list[str] = []
    spinner = _Spinner("starting…")
    spinner.start()

    audio_duration = 0.0
    if not args.skip_audio and 'tts_result' in locals() and tts_result:
        audio_duration = tts_result.get("duration", 0.0)

    try:
        for update in run_coder_agent(
            storyboard["visual_instructions"],
            max_retries=max(0, args.max_retries),
            audio_script=storyboard.get("audio_script", ""),
            audio_duration=audio_duration
        ):
            status = update.get("status", "")
            if status:
                if coder_steps:
                    spinner.stop()
                    _log_step(coder_steps[-1])
                    spinner.start()
                coder_steps.append(status)
                spinner.update(status)

            if update.get("final"):
                final_video_path = update.get("video_path")
                final_error = update.get("error")
                break
    finally:
        spinner.stop()

    if coder_steps:
        _log_step(coder_steps[-1], last=True)

    code_elapsed = time.perf_counter() - code_started

    if not final_video_path:
        _log_stage_fail("Generating Manim code", code_elapsed)
        stages.append(("Code + Render", "failed", code_elapsed))
        print_pipeline_summary(stages)
        detail = final_error if args.verbose else None
        _print_error("Manim generation failed after retries.", detail)
        sys.exit(1)

    _log_stage_done("Generating Manim code", code_elapsed)
    stages.append(("Code + Render", "ok", code_elapsed))

    # ── Skip-audio shortcut ───────────────────────────────────────
    if args.skip_audio:
        print_pipeline_summary(stages)
        _print_output(final_video_path)
        _open_file(final_video_path)
        return

    # ── Stitching ─────────────────────────────────────────────────
    final_output = os.path.join("output", "final_output.mp4")
    stitch_result, elapsed = run_stage(
        "Stitching video + audio",
        stitch_video_and_audio,
        final_video_path,
        audio_path,
        final_output,
    )
    if stitch_result and stitch_result.get("success"):
        _log_stage_done("Stitching video + audio", elapsed)
        stages.append(("Stitch", "ok", elapsed))
        print_pipeline_summary(stages)
        _print_output(final_output)
        _open_file(final_output)
    else:
        _log_stage_fail("Stitching video + audio", elapsed)
        stages.append(("Stitch", "failed", elapsed))
        print_pipeline_summary(stages)
        console.print(f"  [{WARN}]⚠  Stitching failed — opening raw animation instead.[/{WARN}]")
        if args.verbose and stitch_result and stitch_result.get("error"):
            console.print(f"  [{DIM}]{stitch_result['error']}[/{DIM}]")
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
