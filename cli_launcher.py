#!/usr/bin/env python3
"""Launcher that delegates to the TypeScript Ink CLI (cli/dist/cli.js).

Falls back to the Python CLI if Node.js is not available.
"""

import os
import shutil
import subprocess
import sys


def _find_cli_js() -> str | None:
    """Locate the compiled Ink CLI entry point."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(here, "cli", "dist", "cli.js")
    if os.path.isfile(candidate):
        return candidate
    return None


def main() -> None:
    cli_js = _find_cli_js()
    node = shutil.which("node")

    if cli_js and node:
        # Launch the Ink CLI, passing through all args.
        # Pass the current Python executable so the Ink CLI spawns
        # pipeline_runner.py with the correct venv Python (not system Python).
        env = os.environ.copy()
        env["PAPER2MANIM_PYTHON"] = sys.executable

        # In non-interactive mode (--print / -p), stdin may not be a TTY.
        # Ink's useInput requires raw mode on stdin, which fails on pipes.
        # Provide /dev/null as stdin so the print-mode codepath (which
        # bypasses Ink rendering entirely) never triggers the raw-mode check.
        is_print_mode = any(
            arg in ("--print", "-p") for arg in sys.argv[1:]
        )
        stdin_arg: int | None = None
        if is_print_mode or not sys.stdin.isatty():
            stdin_arg = subprocess.DEVNULL

        result = subprocess.run(
            [node, cli_js, *sys.argv[1:]],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env=env,
            stdin=stdin_arg,
        )
        sys.exit(result.returncode)
    else:
        # Fallback to Python CLI
        if not node:
            print("Node.js not found — using Python CLI fallback.", file=sys.stderr)
        if not cli_js:
            print("Ink CLI not built — run 'cd cli && npm run build'. Using Python CLI fallback.", file=sys.stderr)
        from cli_fallback import main as python_main
        python_main()


if __name__ == "__main__":
    main()
