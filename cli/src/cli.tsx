#!/usr/bin/env node
/**
 * paper2manim CLI — primary terminal UI built with Ink.
 */

import React from 'react';
import { render } from 'ink';
import meow from 'meow';
import { App } from './App.js';
import { runPrintMode } from './lib/printMode.js';
import { loadSettings, flagsToSettingsOverrides } from './lib/settings.js';
import { createSession, loadSession, getMostRecentSession } from './lib/session.js';

const cli = meow(
  `
  Usage
    $ paper2manim [concept]

  Options
    --max-retries, -r    Maximum self-correction attempts (default: 3)
    --quality, -q        Generation quality: low, medium, high (default: high)
    --model              Override the model profile or stage model (e.g. openai-default, gpt-5.4)
    --theme              Color theme: dark, light, minimal, colorblind, ansi (default: dark)
    --output-format      Output format: text, json, stream-json (default: text)
    --print, -p          Non-interactive mode: plain text output
    --skip-audio, -s     Skip TTS and audio stitching (video only)
    --workspace, -w      Open the interactive workspace dashboard
    --resume <dir>       Resume a previous project from its output directory
    --verbose, -v        Show detailed diagnostics
    --render-timeout     Per-segment render timeout in seconds (default: 300)
    --tts-timeout        Per-segment TTS timeout in seconds (default: unlimited)
    --lite, -l           (Deprecated) Use --quality low instead
    --name, -n           Set a display name for this session
    --continue, -c       Continue the most recent session
    --no-session-persistence  Skip writing session state to disk
    --permission-mode    Permission mode: default, acceptEdits, plan, auto, bypassPermissions
    --settings           Path or JSON string of settings overrides
    --system-prompt      Prepend text to the pipeline system prompt
    --max-turns          Limit the number of generation/correction turns
    --fallback-model     Fallback model if primary is overloaded
    --color              Prompt bar color: red, blue, green, yellow, purple, orange, pink, cyan

  Examples
    $ paper2manim 'The Chain Rule'
    $ paper2manim -p 'Fourier Transform'
    $ paper2manim --quality low 'Linear Algebra: Dot Products'
    $ paper2manim --output-format json 'SVD'
    $ paper2manim --model openai-default 'Bayes Theorem'
    $ paper2manim --skip-audio 'Fourier Transform'
    $ paper2manim --workspace
    $ paper2manim --resume output/chain_rule_1234
    $ paper2manim --render-timeout 600 'Fourier Series'
    $ paper2manim --name 'my-session' 'Gradient Descent'
    $ paper2manim --continue
    $ paper2manim --permission-mode plan 'Euler Identity'
`,
  {
    importMeta: import.meta,
    flags: {
      maxRetries: {
        type: 'number',
        shortFlag: 'r',
        default: 3,
      },
      quality: {
        type: 'string' as const,
        shortFlag: 'q',
        default: 'high',
      },
      model: {
        type: 'string' as const,
      },
      theme: {
        type: 'string' as const,
      },
      outputFormat: {
        type: 'string' as const,
        default: 'text',
      },
      printMode: {
        type: 'boolean' as const,
        shortFlag: 'p',
        default: false,
      },
      lite: {
        type: 'boolean',
        shortFlag: 'l',
        default: false,
      },
      skipAudio: {
        type: 'boolean',
        shortFlag: 's',
        default: false,
      },
      workspace: {
        type: 'boolean',
        shortFlag: 'w',
        default: false,
      },
      resume: {
        type: 'string',
      },
      verbose: {
        type: 'boolean',
        shortFlag: 'v',
        default: false,
      },
      renderTimeout: {
        type: 'number',
        default: 0,
      },
      ttsTimeout: {
        type: 'number',
        default: 0,
      },
      // New flags
      name: {
        type: 'string' as const,
        shortFlag: 'n',
      },
      continue: {
        type: 'boolean' as const,
        shortFlag: 'c',
        default: false,
      },
      noSessionPersistence: {
        type: 'boolean' as const,
        default: false,
      },
      permissionMode: {
        type: 'string' as const,
      },
      settings: {
        type: 'string' as const,
      },
      systemPrompt: {
        type: 'string' as const,
      },
      maxTurns: {
        type: 'number' as const,
      },
      fallbackModel: {
        type: 'string' as const,
      },
      color: {
        type: 'string' as const,
      },
    },
  },
);

// ── Bootstrap settings ────────────────────────────────────────────────────────

const flagOverrides = flagsToSettingsOverrides({
  permissionMode: cli.flags.permissionMode,
  model: cli.flags.model,
  theme: cli.flags.theme,
  quality: cli.flags.lite ? 'low' : cli.flags.quality,
  verbose: cli.flags.verbose,
  color: cli.flags.color,
});

// Parse --settings flag (path or inline JSON)
let extraSettingsOverrides = {};
if (cli.flags.settings) {
  try {
    extraSettingsOverrides = JSON.parse(cli.flags.settings);
  } catch {
    // Treat as file path
    try {
      const { readFileSync } = await import('node:fs');
      extraSettingsOverrides = JSON.parse(readFileSync(cli.flags.settings, 'utf8'));
    } catch { /* ignore */ }
  }
}

const settings = loadSettings({ ...flagOverrides, ...extraSettingsOverrides });

// ── Bootstrap session ─────────────────────────────────────────────────────────

let session = createSession(cli.flags.name, settings.defaultMode);

if (cli.flags.continue) {
  const recent = getMostRecentSession();
  if (recent) session = recent;
}

// ── Resolve effective quality and concept ─────────────────────────────────────

const concept = cli.input.join(' ').trim() || undefined;
const effectiveQuality = cli.flags.lite ? 'low' : (settings.quality as 'low' | 'medium' | 'high');
const outputFormat = (['json', 'stream-json'].includes(cli.flags.outputFormat) ? cli.flags.outputFormat : 'text') as 'text' | 'json' | 'stream-json';

// ── Git branch (read synchronously for use in initial render) ─────────────────

let initialGitBranch: string | null = null;
try {
  const { execSync } = await import('node:child_process');
  const b = execSync('git rev-parse --abbrev-ref HEAD', {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
    timeout: 2000,
  }).trim();
  if (b && b !== 'HEAD') initialGitBranch = b;
} catch { /* not a git repo */ }

// ── Non-interactive mode ──────────────────────────────────────────────────────

if (cli.flags.printMode || outputFormat === 'json' || outputFormat === 'stream-json') {
  const pipelineArgs = {
    concept: concept ?? '',
    max_retries: cli.flags.maxRetries,
    is_lite: effectiveQuality === 'low',
    skip_audio: cli.flags.skipAudio,
    resume_dir: cli.flags.resume,
    render_timeout: cli.flags.renderTimeout || undefined,
    tts_timeout: cli.flags.ttsTimeout || undefined,
    system_prompt_prefix: cli.flags.systemPrompt,
    max_turns: cli.flags.maxTurns,
    model: settings.model,
  };
  runPrintMode(pipelineArgs, outputFormat === 'stream-json' ? 'json' : outputFormat).catch((err: Error) => {
    process.stderr.write(`error: ${err.message}\n`);
    process.exit(1);
  });
} else {
  render(
    <App
      initialConcept={concept}
      maxRetries={cli.flags.maxRetries}
      isLite={effectiveQuality === 'low'}
      quality={effectiveQuality}
      skipAudio={cli.flags.skipAudio}
      workspace={cli.flags.workspace}
      resumeDir={cli.flags.resume}
      verbose={cli.flags.verbose}
      renderTimeout={cli.flags.renderTimeout || undefined}
      ttsTimeout={cli.flags.ttsTimeout || undefined}
      settings={settings}
      session={session}
      gitBranch={initialGitBranch}
      systemPrompt={cli.flags.systemPrompt}
      maxTurns={cli.flags.maxTurns}
      noSessionPersistence={cli.flags.noSessionPersistence}
    />,
    { exitOnCtrlC: false },
  );
}
