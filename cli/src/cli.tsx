#!/usr/bin/env node
/**
 * paper2manim CLI — primary terminal UI built with Ink.
 */

import React from 'react';
import { render } from 'ink';
import meow from 'meow';
import { App } from './App.js';
import { runPrintMode } from './lib/printMode.js';

const cli = meow(
  `
  Usage
    $ paper2manim [concept]

  Options
    --max-retries, -r    Maximum self-correction attempts (default: 3)
    --quality, -q        Generation quality: low, medium, high (default: high)
    --model              Override the Claude model (e.g. claude-sonnet-4-5)
    --theme              Terminal color theme: dark, light, minimal (default: dark)
    --output-format      Output format: text or json (default: text)
    --print, -p          Non-interactive mode: plain text output
    --skip-audio, -s     Skip TTS and audio stitching (video only)
    --workspace, -w      Open the interactive workspace dashboard
    --resume <dir>       Resume a previous project from its output directory
    --verbose, -v        Show detailed diagnostics
    --render-timeout     Per-segment render timeout in seconds (default: 300)
    --tts-timeout        Per-segment TTS timeout in seconds (default: unlimited)
    --lite, -l           (Deprecated) Use --quality low instead

  Examples
    $ paper2manim 'The Chain Rule'
    $ paper2manim -p 'Fourier Transform'
    $ paper2manim --quality low 'Linear Algebra: Dot Products'
    $ paper2manim --output-format json 'SVD'
    $ paper2manim --model claude-sonnet-4-5 'Bayes Theorem'
    $ paper2manim --skip-audio 'Fourier Transform'
    $ paper2manim --workspace
    $ paper2manim --resume output/chain_rule_1234
    $ paper2manim --render-timeout 600 'Fourier Series'
    $ paper2manim --tts-timeout 60 'Gradient Descent'
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
        default: 'dark',
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
    },
  },
);

const concept = cli.input.join(' ').trim() || undefined;

// --lite is a deprecated alias for --quality low
const effectiveQuality = cli.flags.lite ? 'low' : (cli.flags.quality as 'low' | 'medium' | 'high');

const outputFormat = (cli.flags.outputFormat === 'json' ? 'json' : 'text') as 'text' | 'json';

// --print and --output-format json both bypass Ink and run non-interactively
if (cli.flags.printMode || outputFormat === 'json') {
  const pipelineArgs = {
    concept: concept ?? '',
    max_retries: cli.flags.maxRetries,
    is_lite: effectiveQuality === 'low',
    skip_audio: cli.flags.skipAudio,
    resume_dir: cli.flags.resume,
    render_timeout: cli.flags.renderTimeout || undefined,
    tts_timeout: cli.flags.ttsTimeout || undefined,
  };
  runPrintMode(pipelineArgs, outputFormat).catch((err: Error) => {
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
      model={cli.flags.model}
      theme={cli.flags.theme as 'dark' | 'light' | 'minimal'}
      skipAudio={cli.flags.skipAudio}
      workspace={cli.flags.workspace}
      resumeDir={cli.flags.resume}
      verbose={cli.flags.verbose}
      renderTimeout={cli.flags.renderTimeout || undefined}
      ttsTimeout={cli.flags.ttsTimeout || undefined}
    />,
    { exitOnCtrlC: false },
  );
}
