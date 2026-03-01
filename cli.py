#!/usr/bin/env python3
"""Paper2Manim CLI."""

import argparse
import os
import sys
import time
from typing import Callable, TypeVar

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agents.coder import run_coder_agent
from agents.planner import plan_video_concept
from utils.media_assembler import stitch_video_and_audio
from utils.tts_engine import generate_voiceover


load_dotenv()
console = Console()
T = TypeVar("T")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="paper2manim",
        description="Generate an educational video from a concept.",
    )
    parser.add_argument("concept", nargs="+", help="Concept/topic to visualize")
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum self-correction attempts for Manim code (default: 3)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed diagnostics for failures",
    )
    parser.add_argument(
        "--skip-audio",
        action="store_true",
        help="Skip TTS and stitching; render animation only",
    )
    return parser.parse_args()


def run_stage(label: str, fn: Callable[..., T], *args, **kwargs) -> tuple[T, float]:
    started = time.perf_counter()
    with console.status(f"{label}...", spinner="dots"):
        result = fn(*args, **kwargs)
    elapsed = time.perf_counter() - started
    return result, elapsed


def print_pipeline_summary(stages: list[tuple[str, str, float]]) -> None:
    table = Table(title="Pipeline Summary", show_lines=False)
    table.add_column("Stage", style="bold")
    table.add_column("Status")
    table.add_column("Duration", justify="right")
    for stage, status, elapsed in stages:
        table.add_row(stage, status, f"{elapsed:.1f}s")
    console.print(table)


def main() -> None:
    args = parse_args()
    concept = " ".join(args.concept).strip()

    if not os.getenv("GEMINI_API_KEY"):
        console.print("[bold red]Error:[/bold red] GEMINI_API_KEY not found.")
        console.print("Set it in .env as GEMINI_API_KEY=your_key_here")
        sys.exit(1)

    os.makedirs("output", exist_ok=True)
    console.print(Panel.fit("Paper2Manim CLI", subtitle=f"Concept: {concept}"))

    stages: list[tuple[str, str, float]] = []

    try:
        storyboard, elapsed = run_stage("Planning storyboard", plan_video_concept, concept)
    except Exception as exc:
        stages.append(("Plan", "failed", 0.0))
        print_pipeline_summary(stages)
        console.print(f"[bold red]Planning failed:[/bold red] {exc}")
        sys.exit(1)
    stages.append(("Plan", "ok", elapsed))

    audio_path = os.path.join("output", "voiceover.wav")
    if not args.skip_audio:
        tts_result, elapsed = run_stage(
            "Generating voiceover",
            generate_voiceover,
            storyboard["audio_script"],
            audio_path,
        )
        if not tts_result.get("success"):
            stages.append(("Voiceover", "failed", elapsed))
            print_pipeline_summary(stages)
            console.print("[bold red]Voiceover generation failed.[/bold red]")
            if args.verbose and tts_result.get("error"):
                console.print(tts_result["error"])
            sys.exit(1)
        audio_path = tts_result.get("audio_path", audio_path)
        stages.append(("Voiceover", "ok", elapsed))

    code_started = time.perf_counter()
    final_video_path = None
    final_error = None
    last_status = ""
    last_error = ""
    codegen_table = Table(show_header=True, header_style="bold")
    codegen_table.add_column("Attempt", justify="right")
    codegen_table.add_column("State")
    codegen_table.add_column("Details")
    attempt_no = 0

    with console.status("Generating and validating Manim code...", spinner="line"):
        for update in run_coder_agent(
            storyboard["visual_instructions"],
            max_retries=max(0, args.max_retries),
        ):
            status = update.get("status", "")
            if status and status != last_status:
                last_status = status
                if status.startswith("Attempt "):
                    attempt_no += 1
                    codegen_table.add_row(str(attempt_no), "execute", status)
                elif "Self-correcting" in status or "Applying fix" in status:
                    codegen_table.add_row(str(max(1, attempt_no)), "repair", status)
                else:
                    codegen_table.add_row(str(max(1, attempt_no)), "progress", status)

            if update.get("error"):
                last_error = update["error"]

            if update.get("final"):
                final_video_path = update.get("video_path")
                final_error = update.get("error")
                break

    code_elapsed = time.perf_counter() - code_started
    if not final_video_path:
        stages.append(("Code + Render", "failed", code_elapsed))
        print_pipeline_summary(stages)
        console.print(codegen_table)
        console.print("[bold red]Manim generation failed after retries.[/bold red]")
        if args.verbose and (final_error or last_error):
            console.print(final_error or last_error)
        sys.exit(1)

    stages.append(("Code + Render", "ok", code_elapsed))
    console.print(codegen_table)

    if args.skip_audio:
        print_pipeline_summary(stages)
        console.print(f"[bold green]Done.[/bold green] Output: {final_video_path}")
        sys.exit(0)

    final_output = os.path.join("output", "final_output.mp4")
    stitch_result, elapsed = run_stage(
        "Stitching audio and video",
        stitch_video_and_audio,
        final_video_path,
        audio_path,
        final_output,
    )
    if stitch_result.get("success"):
        stages.append(("Stitch", "ok", elapsed))
        print_pipeline_summary(stages)
        console.print(f"[bold green]Done.[/bold green] Output: {final_output}")
    else:
        stages.append(("Stitch", "failed", elapsed))
        print_pipeline_summary(stages)
        console.print("[bold yellow]Stitching failed; returning raw animation.[/bold yellow]")
        console.print(f"Raw video: {final_video_path}")
        if args.verbose and stitch_result.get("error"):
            console.print(stitch_result["error"])


if __name__ == "__main__":
    main()
