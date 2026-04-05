# paper2manim development tasks

# Build the CLI
build:
    cd cli && npm run build

# Run in dev mode (no compile step)
dev:
    cd cli && npm run dev

# Run the CLI
run *args:
    python cli_launcher.py {{args}}

# Run all tests
test: test-python test-typescript

# Run Python tests
test-python:
    python -m pytest tests/ -x -v

# Run TypeScript tests
test-typescript:
    cd cli && npm test || echo "No TS tests yet"

# Lint all code
lint: lint-python lint-typescript

# Lint Python
lint-python:
    ruff check agents/ utils/ tests/ pipeline_runner.py cli_launcher.py cli_fallback.py

# Lint TypeScript
lint-typescript:
    cd cli && npx tsc --noEmit

# Format Python
fmt:
    ruff format agents/ utils/ tests/ pipeline_runner.py cli_launcher.py cli_fallback.py

# Run doctor diagnostics
doctor:
    python -c "from utils.manim_runner import check_manim; print('Manim:', 'OK' if check_manim() else 'MISSING')"
    python -c "import shutil; print('FFmpeg:', 'OK' if shutil.which('ffmpeg') else 'MISSING')"
    node -e "console.log('Node:', process.version)"

# Clean build artifacts
clean:
    rm -rf cli/dist/ build/ *.egg-info
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
