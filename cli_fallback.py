#!/usr/bin/env python3
"""Minimal CLI fallback when Node.js / Ink CLI is unavailable.

Provides basic concept-in, video-out functionality using Rich for terminal
output.  The full interactive experience (slash commands, workspace dashboard,
themes, session history, etc.) requires the TypeScript Ink CLI.
"""
from __future__ import annotations

import argparse
import os
import re
import signal
import sys
import time

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

# -- .env loading (same search order as pipeline_runner.py) -----------------
_project_root = os.path.dirname(os.path.abspath(__file__))
try:
    from dotenv import dotenv_values
    for _p in [
        os.path.join(_project_root, ".env"),
        os.path.join(os.getcwd(), ".env"),
        os.path.expanduser("~/Documents/projects/paper2manim/.env"),
    ]:
        if os.path.isfile(_p):
            for _k, _v in dotenv_values(_p).items():
                if _v and not os.environ.get(_k):
                    os.environ[_k] = _v
            break
except ImportError:
    pass  # dotenv optional; keys must already be in the environment

console = Console(highlight=False)
VERSION = "0.1.0"

# -- Graceful Ctrl+C (double-press to exit) ---------------------------------
_last_sigint: float = 0.0

def _sigint_handler(_sig: int, _frame: object) -> None:
    global _last_sigint
    now = time.monotonic()
    if now - _last_sigint < 2.0:
        console.print("\n[dim]Exiting...[/dim]")
        sys.exit(130)
    _last_sigint = now
    console.print("\n[yellow]Press Ctrl+C again to exit[/yellow]")

signal.signal(signal.SIGINT, _sigint_handler)

# -- Helpers ----------------------------------------------------------------
_STAGE_LABELS = {
    "plan": "Plan storyboard", "tts": "Generate voiceover",
    "code": "Generate Manim code", "render": "Render HD segments",
    "stitch": "Stitch audio/video", "concat": "Assemble final video",
    "done": "Finalize",
}

def _stage_label(name: str) -> str:
    return _STAGE_LABELS.get(name, name.replace("_", " ").title())

def _fmt_dur(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{seconds:.1f}s [{m}m {s:02d}s]"

def _clean_status(raw: str) -> str:
    """Strip internal prefixes from a pipeline status string."""
    s = re.sub(r"^Stage \d+/\d+:\s*", "", raw.strip(), flags=re.IGNORECASE)
    s = re.sub(r"^\[Seg \d+\]\s*", "", s)
    s = re.sub(r"\.{2,}$", "", s).strip()
    return (s[0].upper() + s[1:]) if s else s

# Default questionnaire answers (auto-answered in fallback mode)
_DEFAULT_ANSWERS = {
    "video_length": "Medium (3-5 min)", "target_audience": "Undergraduate",
    "visual_style": "Let the AI decide", "pacing": "Balanced",
}

# -- Banner -----------------------------------------------------------------
def _print_banner() -> None:
    console.print(Panel(
        f"[bold blue]paper2manim[/bold blue]  [dim]v{VERSION}[/dim]\n\n"
        "  [yellow]Running in fallback mode[/yellow]\n"
        "  [dim]Install Node.js and run 'cd cli && npm run build' for the full CLI[/dim]",
        border_style="blue", padding=(0, 2),
    ))

# -- Error display ----------------------------------------------------------
_ERROR_HINTS = {
    "credit balance": "Visit console.anthropic.com/settings/billing to add credits.",
    "invalid api key": "Check ANTHROPIC_API_KEY in .env.",
    "authentication": "Verify ANTHROPIC_API_KEY and GEMINI_API_KEY in .env.",
    "rate limit": "Wait 30-60s and retry. Consider --quality low.",
    "missing api key": "Create a .env file with ANTHROPIC_API_KEY and GEMINI_API_KEY.",
    "manim": "Ensure Manim is installed: pip install manim",
}

def _print_error(message: str) -> None:
    hint = ""
    lower = message.lower()
    for key, text in _ERROR_HINTS.items():
        if key in lower:
            hint = f"\n\n[yellow]Suggestion:[/yellow] {text}"
            break
    console.print(Panel(
        f"[red]{message}[/red]{hint}",
        title="[bold red]Error[/bold red]", border_style="red", padding=(1, 2),
    ))

# -- Arg parsing ------------------------------------------------------------
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="paper2manim",
        description="Generate an educational Manim video from a concept (fallback mode).",
    )
    p.add_argument("concept", nargs="*", help="Concept/topic to visualize")
    p.add_argument("--max-retries", type=int, default=3, help="Max self-correction attempts (default: 3)")
    p.add_argument("--skip-audio", action="store_true", help="Skip TTS; render animation only")
    p.add_argument("--quality", "-q", choices=["low", "medium", "high"], default="high",
                    help="Generation quality (default: high)")
    p.add_argument("--model", default=None, help="Override the Claude model")
    p.add_argument("--verbose", action="store_true", help="Verbose diagnostics")
    # Flags accepted by full CLI -- silently ignored in fallback
    for flag in ("--workspace", "--lite"):
        p.add_argument(flag, action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--resume", type=str, help=argparse.SUPPRESS)
    p.add_argument("-p", "--print", dest="print_mode", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--output-format", default="text", help=argparse.SUPPRESS)
    p.add_argument("--theme", default="dark", help=argparse.SUPPRESS)
    return p.parse_args()

# -- Pipeline execution with Rich progress ----------------------------------
def _run_pipeline(concept: str, args: argparse.Namespace) -> None:
    """Run the segmented pipeline in-process and display Rich progress."""
    from agents.pipeline import run_segmented_pipeline

    is_lite = args.quality == "low" or getattr(args, "lite", False)
    if args.model:
        os.environ["PAPER2MANIM_MODEL_OVERRIDE"] = args.model

    console.print(f"\n  [dim]Concept:[/dim]  [bold]{concept}[/bold]")
    console.print(f"  [dim]Quality:[/dim]  {args.quality.title()}")
    console.print("  [dim]Answers:[/dim]  (auto-answered in fallback mode)\n")

    stages: list[tuple[str, str, float]] = []
    last_stage: str | None = None
    stage_start = time.perf_counter()
    final_video: str | None = None
    stage_pcts = {"plan": 10, "tts": 25, "code": 55, "render": 80,
                  "stitch": 90, "concat": 98, "done": 100}

    with Progress(
        SpinnerColumn(style="bold cyan"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=20, style="bright_black", complete_style="cyan"),
        TaskProgressColumn(), TimeElapsedColumn(),
        console=console, transient=False,
    ) as prog:
        task = prog.add_task("[bold cyan]Starting...", total=100)
        try:
            for update in run_segmented_pipeline(
                concept=concept, output_base="output",
                max_retries=args.max_retries, is_lite=is_lite,
                questionnaire_answers=_DEFAULT_ANSWERS,
                skip_audio=args.skip_audio,
            ):
                cur_stage = update.get("stage", "unknown")
                status = update.get("status", "")

                # Stage transition
                if cur_stage != last_stage:
                    if last_stage:
                        elapsed = time.perf_counter() - stage_start
                        stages.append((last_stage, "ok", elapsed))
                        prog.console.print(
                            f"  [green]OK[/green] {_stage_label(last_stage):<26} "
                            f"[dim]{_fmt_dur(elapsed)}[/dim]")
                    last_stage = cur_stage
                    stage_start = time.perf_counter()

                # Progress bar
                tgt = stage_pcts.get(cur_stage, int(prog.tasks[task].completed))
                prog.update(task, completed=max(int(prog.tasks[task].completed), tgt))

                # Description
                if status:
                    prog.update(task, description=(
                        f"[bold cyan]{cur_stage.title()}[/bold cyan]  "
                        f"[dim]{_clean_status(status)[:60]}[/dim]"))

                # Final update
                if update.get("final"):
                    final_video = update.get("video_path")
                    if update.get("error"):
                        elapsed = time.perf_counter() - stage_start
                        stages.append((last_stage or cur_stage, "failed", elapsed))
                        _print_error(str(update["error"]))
                        return
        except Exception as exc:
            _print_error(f"Pipeline error: {exc}")
            return

    # Record last stage
    if last_stage and last_stage != "done":
        stages.append((last_stage, "ok", time.perf_counter() - stage_start))

    # Summary
    console.print("\n  [bold]Pipeline Summary[/bold]\n")
    total_t = 0.0
    for name, st, elapsed in stages:
        total_t += elapsed
        icon = "[green]OK[/green]" if st == "ok" else "[red]FAIL[/red]"
        console.print(f"  {icon}  {_stage_label(name):<26} [dim]{_fmt_dur(elapsed)}[/dim]")
    console.print(f"  [dim]{'_' * 42}[/dim]")
    console.print(f"       {'Total':<26} [bold]{_fmt_dur(total_t)}[/bold]\n")

    if final_video:
        console.print(f"  [green]Output ready:[/green]  [bold]{os.path.abspath(final_video)}[/bold]\n")
    else:
        _print_error("Pipeline completed but no final video was produced.")

# -- Entry points -----------------------------------------------------------

def run_fallback(concept: str | None = None, **kwargs: object) -> None:
    """Programmatic entry point (can be called by cli_launcher or scripts)."""
    _print_banner()
    console.print()
    if not concept:
        concept = console.input("[bold]Enter a concept: [/]").strip()
        if not concept:
            console.print("[red]No concept provided.[/red]")
            return
    ns = argparse.Namespace(
        concept=[concept], max_retries=int(kwargs.get("max_retries", 3)),
        skip_audio=bool(kwargs.get("skip_audio", False)),
        quality=str(kwargs.get("quality", "high")),
        model=kwargs.get("model"), verbose=bool(kwargs.get("verbose", False)),
        lite=False,
    )
    _run_pipeline(concept, ns)

def main() -> None:
    """Entry point when invoked as a script or by cli_launcher.main()."""
    args = _parse_args()
    _print_banner()
    console.print()

    # API key preflight
    missing = []
    if not os.environ.get("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")
    if not args.skip_audio and not os.environ.get("GEMINI_API_KEY"):
        missing.append("GEMINI_API_KEY")
    if missing:
        _print_error(f"Missing API keys: {', '.join(missing)}.  Set them in a .env file.")
        sys.exit(1)

    os.makedirs("output", exist_ok=True)

    if args.workspace:
        console.print("[yellow]Workspace dashboard requires the full CLI. Ignoring --workspace.[/yellow]\n")
    if getattr(args, "resume", None):
        console.print("[yellow]Resume requires the full CLI. Ignoring --resume.[/yellow]\n")

    concept = " ".join(args.concept).strip() if args.concept else ""
    if not concept:
        concept = console.input("[bold]Enter a concept: [/]").strip()
    if not concept:
        console.print("[red]No concept provided.[/red]")
        sys.exit(1)

    _run_pipeline(concept, args)

if __name__ == "__main__":
    main()
