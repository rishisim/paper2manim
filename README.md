# paper2manim

Turn concepts into narrated Manim animations with AI.

Takes a topic (like "fourier transform") and produces an educational video with animations and voiceover, using an OpenAI-first planning/coding stack plus Gemini for text-to-speech.

## Architecture

```
paper2manim (CLI entry)
  └── cli_launcher.py
        └── Node.js ─ cli/dist/cli.js (TypeScript/Ink v5 interactive UI)
              │
              └── NDJSON ──► pipeline_runner.py (bridge)
                                └── agents/pipeline.py (6-stage orchestrator)
                                      ├── Plan     ─ GPT-5.4 storyboard planning
                                      ├── TTS      ─ Gemini voiceover (parallel)
                                      ├── Code     ─ GPT-5.3-Codex Manim generation (parallel)
                                      ├── Verify   ─ GPT-5.4-mini validation / critique
                                      ├── Render   ─ Manim HD rendering (parallel)
                                      └── Concat   ─ FFmpeg final assembly
```

The TypeScript CLI communicates with the Python pipeline over NDJSON (newline-delimited JSON) on stdin/stdout. A Python fallback CLI (`cli_fallback.py`) is used when Node.js is not available.

## Quick Start

### Prerequisites

- Python 3.9+
- Node.js 18+
- [Manim](https://docs.manim.community/en/stable/installation.html) (Community Edition)
- FFmpeg
- LaTeX (required by Manim for math rendering)

### Installation

```bash
git clone https://github.com/user/paper2manim.git
cd paper2manim

# Install the Python package (editable mode recommended)
pipx install -e .
# or: pip install -e .

# Build the TypeScript CLI
cd cli && npm install && npm run build && cd ..
```

### API Keys

Create a `.env` file in the project root:

```
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
GOOGLE_API_KEY=your_google_key
```

- **OPENAI_API_KEY** -- required for the default `openai-default` profile
- **ANTHROPIC_API_KEY** -- optional fallback provider key for the default profile, required only for `anthropic-legacy`
- **GOOGLE_API_KEY** -- required for text-to-speech (Gemini)

## Usage

```bash
# Interactive mode (recommended)
paper2manim

# Single-shot generation
paper2manim "dot product"

# High quality output
paper2manim --quality high "neural networks"

# Workspace dashboard (view past projects)
paper2manim --workspace

# Non-interactive / print mode
paper2manim --print "the chain rule"
```

In interactive mode you get a prompt with slash commands, questionnaire preferences, live progress, and keyboard shortcuts.

## Pipeline Stages

| Stage | What happens | Model |
|-------|-------------|-------|
| **Plan** | Generates a segmented storyboard with visual instructions and audio scripts | GPT-5.4 |
| **TTS** | Produces voiceover audio for each segment in parallel | Gemini 2.5 Flash |
| **Code** | Self-correcting agent generates working Manim code per segment in parallel | GPT-5.3-Codex |
| **Verify** | Validates generated code compiles and critiques frames / transitions | GPT-5.4-mini |
| **Render** | HD Manim rendering of each segment in parallel | -- |
| **Concat** | Stitches audio + video per segment, then concatenates all into one video | FFmpeg |

Failed segments are automatically retried with few-shot examples from successful segments.

## Project Structure

```
paper2manim/
├── cli_launcher.py          # Entry point: delegates to TS CLI or fallback
├── cli_fallback.py          # Pure-Python fallback CLI (Rich)
├── pipeline_runner.py       # NDJSON bridge between TS CLI and Python pipeline
├── cli/                     # TypeScript Ink v5 interactive terminal UI
│   └── src/
│       ├── cli.tsx          # Flag parsing, session bootstrap
│       ├── App.tsx          # Screen routing, pipeline lifecycle
│       ├── components/      # UI components (prompt, status, panels)
│       ├── context/         # React contexts (settings, session)
│       └── lib/             # Commands, types, themes
├── agents/
│   ├── pipeline.py          # 6-stage parallel orchestrator
│   ├── planner_math2manim.py # Profile-aware storyboard planner
│   ├── coder.py             # Self-correcting Manim code generator
│   └── validation.py        # Input validation
├── utils/
│   ├── llm_provider.py      # OpenAI/Anthropic provider adapters and caching
│   ├── tts_engine.py        # TTS via Gemini
│   ├── manim_runner.py      # Manim execution and error handling
│   ├── media_assembler.py   # Video + audio stitching, concatenation
│   ├── parallel_renderer.py # Multiprocess HD rendering
│   └── project_state.py     # Project persistence and state tracking
├── output/                  # Generated projects and videos
└── pyproject.toml           # Package metadata and dependencies
```

## Development

```bash
# Build the TypeScript CLI after changes
cd cli && npm run build

# Run in dev mode (no compile step)
cd cli && npm run dev

# Run the pipeline progress streaming test
python -m pytest tests/test_pipeline_progress_streaming.py
```

### Environment Overrides

| Variable | Purpose |
|----------|---------|
| `PAPER2MANIM_MODEL_PROFILE` | Select `openai-default` or `anthropic-legacy` |
| `PAPER2MANIM_MODEL_OVERRIDE` | Deprecated compatibility alias for overriding plan/code model IDs |
| `PAPER2MANIM_STAGE_MODEL_PLAN` | Override the planning model |
| `PAPER2MANIM_STAGE_MODEL_CODE` | Override the coding model |
| `PAPER2MANIM_STAGE_MODEL_VERIFY` | Override the verification model |
| `PAPER2MANIM_STAGE_MODEL_VISION` | Override the vision critique model |
| `PAPER2MANIM_MAX_TURNS` | Limit the number of self-correction turns |
| `PAPER2MANIM_SYSTEM_PROMPT_PREFIX` | Prepend text to the system prompt |

### Settings

Settings are loaded in three tiers (later overrides earlier):

```
~/.paper2manim/settings.json          # User-level
.paper2manim/settings.json            # Project-level
.paper2manim/settings.local.json      # Local overrides (gitignored)
```

## License

MIT
