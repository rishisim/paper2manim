# paper2manim — Development Guide

This file documents the architecture, workflows, and patterns for the paper2manim CLI. Read this before making changes.

## Architecture

```
cli_launcher.py
  └─ spawns Node.js → cli/dist/cli.js
       └─ Ink v5 React app (cli/src/)
            └─ spawns Python subprocess (pipeline_runner.py) via NDJSON
                 └─ agents/pipeline.py (6-stage generator)
```

**Communication:** The TypeScript CLI talks to the Python pipeline via NDJSON (newline-delimited JSON) on the child process's stdin/stdout. The pipeline emits `{"type": "pipeline", "update": {...}}` lines; the CLI sends questionnaire answers back on stdin.

**Fallback:** If Node.js or `cli/dist/cli.js` is missing, `cli_launcher.py` falls back to `cli_fallback.py` (a standalone Python CLI using Rich). Keep feature parity between them when adding major features.

## Build & Run

```bash
cd cli && npm run build      # tsc → cli/dist/ (required before running)
cd cli && npm run dev        # run directly via tsx (no compile step, for dev)
paper2manim                  # run the installed CLI
paper2manim "fourier transform"   # single-shot concept
paper2manim --workspace      # open workspace dashboard
paper2manim --print "dot product" # non-interactive output
```

After any TypeScript change, run `cd cli && npm run build` to update `cli/dist/`.

## Key Files

| File | Purpose |
|------|---------|
| `cli/src/cli.tsx` | Entry point: flag parsing (meow), session bootstrap, render() |
| `cli/src/App.tsx` | Main app: screen routing, pipeline lifecycle, all keyboard shortcuts |
| `cli/src/context/AppContext.tsx` | React Context: SettingsContext + SessionContext |
| `cli/src/lib/commands.ts` | ~35 slash commands (all `/cmd` handlers) |
| `cli/src/lib/settings.ts` | 3-tier settings loader: user / project / local |
| `cli/src/lib/types.ts` | All TypeScript interfaces and enums |
| `cli/src/lib/theme.ts` | 5 color themes, stage configs, brand constants |
| `cli/src/components/PromptBar.tsx` | Main input box with slash overlay |
| `cli/src/components/ControlledTextInput.tsx` | Custom text input with cursor/history |
| `cli/src/components/SlashCommandOverlay.tsx` | Fixed-height command palette dropdown |
| `cli/src/components/FooterStatusLine.tsx` | Bottom status bar (model · mode · tokens · branch) |
| `cli/src/components/WelcomeScreen.tsx` | Split-panel home screen |
| `agents/pipeline.py` | 6-stage orchestrator (plan→tts→code→render→stitch→concat) |
| `agents/planner_math2manim.py` | Pro planner: Claude-based 5-sub-stage enrichment |
| `agents/coder.py` | Self-correcting Manim code generator (Claude) |
| `utils/tts_engine.py` | TTS via Gemini 2.5 Flash |
| `pipeline_runner.py` | NDJSON bridge between TS CLI and Python pipeline |

## Screens

`App.tsx` routes between 10 screens via `const [screen, setScreen]`:

```
input → questionnaire → running → complete
                               → error
input → workspace
input → settings / context / doctor / keybindings (overlays)
```

**To add a screen:**
1. Add the new name to the `Screen` type in `App.tsx` line 54
2. Create a component in `cli/src/components/`
3. Add a routing block (`if (screen === 'newscreen') { return <...> }`) before the final `return` in `AppInner`
4. Add a slash command in `commands.ts` that calls `dispatch.navigate('newscreen')`

## State Management

Two React contexts (merged via `useAppContext()`):

- **`SettingsContext`** — rarely changes: `permissionMode`, `currentModel`, `verboseMode`, `quality`, `thinkingVisible`, `gitBranch`, `themeColors`, `promptColor`
- **`SessionContext`** — per-generation: `session`, `tokenUsage`, `commandHistory`

Settings persist to `~/.paper2manim/settings.json` (user scope) via `saveSettings()`.

**To add a persistent setting:**
1. Add field to `Settings` interface in `cli/src/lib/types.ts`
2. Add to `DEFAULT_SETTINGS` in `types.ts`
3. Add state + setter in `AppContext.tsx` `SettingsProvider`
4. Expose via `AppContextValue` and `useAppContext()`

## Slash Commands

All commands live in `cli/src/lib/commands.ts` as entries in the `COMMANDS` array.

```typescript
{
  name: 'mycommand',
  aliases: ['mc'],
  description: 'What it does',
  category: 'navigation',   // generation|workspace|navigation|settings|display|tools|memory|session
  args: '[optional-arg]',   // undefined if no args required
  handler: (args, dispatch) => {
    // dispatch.navigate(screen), dispatch.showMessage(text, color),
    // dispatch.startGeneration(concept), dispatch.clearHistory(), etc.
  },
},
```

## Ink-Specific Gotchas

### 1. Never call I/O inside React state updaters
`saveSettings()` uses a synchronous busy-wait file lock. Calling it inside a state updater (the callback passed to `setState(prev => ...)`) blocks the render cycle.

```typescript
// BAD — I/O inside updater
setPermissionModeState(current => {
  saveSettings('user', { defaultMode: next });  // blocks render
  return next;
});

// GOOD — defer with queueMicrotask
setPermissionModeState(current => {
  const next = computeNext(current);
  queueMicrotask(() => saveSettings('user', { defaultMode: next }));
  return next;
});
```

### 2. All `useInput` hooks fire for every keypress
Ink calls every active `useInput` handler for each keypress. Use `isActive` or early-return guards to control which handler responds:

```typescript
useInput((_input, key) => {
  if (!isActive) return;         // component-level guard
  if (slashModeActive && key.upArrow) return;  // context-specific guard
});
```

When the slash overlay is open, `ControlledTextInput` suppresses Enter (`!slashModeActive` check at line 131) so only the overlay handles it.

### 3. `<Static>` items never re-render
`<Static>` is for immutable, completed log entries only (concept headers, finished stages). Never put live-updating content in `<Static>`.

### 4. Slash overlay has fixed height
`SlashCommandOverlay` always renders exactly `MAX_VISIBLE=9` rows (padded with nulls). This prevents Ink's live-render region from changing size, which would cause stale content from the welcome box to bleed through. Do not make the overlay's height dynamic.

### 5. One-shot callbacks need ref guards everywhere
Permission/confirmation components must guard against double-firing in BOTH the `useEffect` (auto-allow) AND the `useInput` (manual key) paths:

```typescript
const called = useRef(false);

React.useEffect(() => {
  if (called.current) return;
  if (shouldAutoAllow) { called.current = true; onAllow(); }
}, [...]);

useInput((_input, key) => {
  if (called.current) return;  // guard here too
  if (key.return) { called.current = true; onAllow(); }
});
```

### 6. Welcome box hides (actually unmounts) during slash overlay
When `slashActive` is true, `WelcomeScreen` conditionally renders `{!slashActive && <Box ...>}`. Despite the comment saying "hiding", this IS an unmount. The `PromptBar` (which holds the important state) is always rendered outside the conditional block, so this is safe.

### 7. Terminal resize flash
`useTerminalWidth` triggers a state update on resize. A `\x1b[2J\x1b[H` escape was historically written to prevent Ink from appending below the old render. This causes a visible flash. Ink v5 should handle reflows — the escape may be removable.

## Python Pipeline Models

| Stage | Model |
|-------|-------|
| Planning (Pro/default) | `claude-opus-4-6` |
| Planning (Lite) | `gemini-3.1-pro-preview` |
| Code generation | `claude-opus-4-6` (complex) / `claude-sonnet-4-6` (simple) |
| TTS | `gemini-2.5-flash-preview-tts` |

Override the Claude model via `--model` flag or `Alt+P` in the CLI.
Override via env: `PAPER2MANIM_MODEL_OVERRIDE`, `PAPER2MANIM_MAX_TURNS`.

## Settings Files

```
~/.paper2manim/settings.json        # user-level (persisted by CLI)
.paper2manim/settings.json          # project-level (checked into git)
.paper2manim/settings.local.json    # local overrides (gitignored)
~/.paper2manim/sessions/<id>.json   # session history
```

## Common Issues

**CLI not reflecting my changes:** Run `cd cli && npm run build` — you're editing source, not the compiled output.

**"Unknown command" for a new slash command:** Make sure the command is exported in the `COMMANDS` array in `commands.ts` and the build is current.

**Pipeline hangs on questionnaire:** The Python `_read_stdin_line()` in `pipeline_runner.py` has a 30-second timeout via `select.select()`. If the TS side doesn't answer in time, the pipeline aborts.

**Stale test file:** `tests/test_api.py` imports `_build_config` and `MODEL_NAME` from `agents.coder` which no longer exist — this test will fail on import. The working automated test is `tests/test_pipeline_progress_streaming.py`.
