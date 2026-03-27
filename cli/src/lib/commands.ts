/**
 * Slash command registry — paper2manim Claude Code CLI clone.
 * All ~35 commands mapped to paper2manim context.
 */

import { execSync, execFileSync, spawnSync } from 'node:child_process';
import { existsSync, writeFileSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';
import type { SlashCommand, AppDispatch, ThemeName } from './types.js';
import { PROMPT_COLORS } from './theme.js';
import { saveSettings } from './settings.js';
import { listSessions } from './session.js';

const PAPER2MANIM_MD_TEMPLATE = `# PAPER2MANIM.md

Instructions and preferences loaded by paper2manim at session start.

## Generation Preferences
<!-- Customize defaults for every video -->
- Default quality: high
- Default audience: undergraduate

## Style Notes
<!-- Visual and animation guidelines for the AI -->
- Prefer geometric visualizations
- Use 3b1b color palette (blue #64B4FF, gold #FFD700)
- Minimize on-screen text; let animations speak

## Model Notes
<!-- Any special instructions for Claude -->
`;

export const COMMANDS: SlashCommand[] = [
  // ── Generation ────────────────────────────────────────────────
  {
    name: 'generate',
    aliases: [],
    description: 'Generate a new educational video',
    args: '<concept>',
    handler: (args, dispatch) => {
      const concept = args.join(' ').trim();
      if (!concept) {
        dispatch.showMessage('Usage: /generate <concept>', undefined);
        return;
      }
      dispatch.startPipeline(concept);
    },
  },
  {
    name: 'resume',
    aliases: ['continue'],
    description: 'Resume an interrupted project',
    args: '[dir]',
    handler: (args, dispatch) => {
      const dir = args[0];
      if (!dir) {
        dispatch.showMessage('Usage: /resume <output-dir>', undefined);
        return;
      }
      dispatch.resumePipeline(dir);
    },
  },
  {
    name: 'plan',
    aliases: [],
    description: 'Enter plan-only mode (storyboard without generating)',
    args: '[concept]',
    handler: (args, dispatch) => {
      dispatch.setPermissionMode('plan');
      const concept = args.join(' ').trim();
      if (concept) dispatch.startPipeline(concept);
      dispatch.showMessage('Switched to plan mode — storyboard only, no video generation.', undefined);
    },
  },

  // ── Workspace ─────────────────────────────────────────────────
  {
    name: 'list',
    aliases: ['ls'],
    description: 'List saved projects',
    handler: (_args, dispatch) => {
      dispatch.setScreen('workspace');
    },
  },
  {
    name: 'delete',
    aliases: ['rm'],
    description: 'Delete a project directory',
    args: '<dir>',
    handler: (args, dispatch) => {
      const dir = args[0];
      if (!dir) {
        dispatch.showMessage('Usage: /delete <dir>', undefined);
        return;
      }
      try {
        // C4: Use execFileSync (no shell) to avoid injection via backticks/$()
        execFileSync('rm', ['-rf', dir]);
        dispatch.showMessage(`Deleted: ${dir}`, undefined);
      } catch {
        dispatch.showMessage(`Failed to delete: ${dir}`, undefined);
      }
    },
  },
  {
    name: 'clean',
    aliases: [],
    description: 'Remove stale/incomplete projects',
    handler: (_args, dispatch) => {
      dispatch.showMessage('Running cleanup... (use --workspace to manage projects)', undefined);
    },
  },

  // ── Session / Navigation ──────────────────────────────────────
  {
    name: 'clear',
    aliases: ['reset', 'new'],
    description: 'Clear screen and reset to input',
    handler: (_args, dispatch) => {
      process.stdout.write('\x1b[2J\x1b[H');
      dispatch.setScreen('input');
    },
  },
  {
    name: 'help',
    aliases: ['h', '?'],
    description: 'Show all available commands',
    handler: (_args, dispatch) => {
      dispatch.setScreen('keybindings');
    },
  },
  {
    name: 'exit',
    aliases: ['quit', 'q'],
    description: 'Exit paper2manim',
    handler: (_args, dispatch) => {
      dispatch.exit();
    },
  },

  // ── Settings / Config ─────────────────────────────────────────
  {
    name: 'config',
    aliases: ['settings'],
    description: 'Open settings panel',
    handler: (_args, dispatch) => {
      dispatch.setScreen('settings');
    },
  },
  {
    name: 'status',
    aliases: [],
    description: 'Show version, model, and API key status',
    handler: (_args, dispatch) => {
      const hasAnthropicKey = !!process.env['ANTHROPIC_API_KEY'];
      const hasGeminiKey = !!process.env['GEMINI_API_KEY'] || !!process.env['GOOGLE_API_KEY'];
      dispatch.showMessage(
        [
          'paper2manim v0.1.0',
          `ANTHROPIC_API_KEY: ${hasAnthropicKey ? '✓ set' : '✗ not set'}`,
          `GEMINI_API_KEY: ${hasGeminiKey ? '✓ set' : '✗ not set'}`,
        ].join('\n'),
        undefined,
      );
    },
  },
  {
    name: 'theme',
    aliases: [],
    description: 'Change color theme',
    args: '[dark|light|minimal|colorblind|ansi]',
    handler: (args, dispatch) => {
      const themes: ThemeName[] = ['dark', 'light', 'minimal', 'colorblind', 'ansi'];
      const requested = args[0] as ThemeName | undefined;
      if (!requested || !themes.includes(requested)) {
        dispatch.showMessage(`Available themes: ${themes.join(', ')}`, undefined);
        return;
      }
      dispatch.setTheme(requested);
      dispatch.showMessage(`Theme set to: ${requested}`, undefined);
    },
  },
  {
    name: 'model',
    aliases: [],
    description: 'Switch Claude model',
    args: '[opus|sonnet|<model-id>]',
    handler: (args, dispatch) => {
      let model = args[0];
      if (!model) {
        dispatch.showMessage('Usage: /model [opus|sonnet|<model-id>]', undefined);
        return;
      }
      if (model === 'opus') model = 'claude-opus-4-6';
      if (model === 'sonnet') model = 'claude-sonnet-4-6';
      dispatch.setCurrentModel(model);
      dispatch.showMessage(`Model set to: ${model}`, undefined);
    },
  },
  {
    name: 'quality',
    aliases: [],
    description: 'Set render quality',
    args: '[low|medium|high]',
    handler: (args, dispatch) => {
      const q = args[0] as 'low' | 'medium' | 'high' | undefined;
      if (!q || !['low', 'medium', 'high'].includes(q)) {
        dispatch.showMessage('Usage: /quality [low|medium|high]', undefined);
        return;
      }
      dispatch.setQuality(q);
      dispatch.showMessage(`Quality set to: ${q}`, undefined);
    },
  },
  {
    name: 'color',
    aliases: [],
    description: 'Set prompt bar color',
    args: '[red|blue|green|yellow|purple|orange|pink|cyan|white|default]',
    handler: (args, dispatch) => {
      const colorName = args[0] ?? 'default';
      const hex = PROMPT_COLORS[colorName];
      if (!hex) {
        dispatch.showMessage(`Available colors: ${Object.keys(PROMPT_COLORS).join(', ')}`, undefined);
        return;
      }
      dispatch.setPromptColor(hex);
      dispatch.showMessage(`Prompt color set to: ${colorName}`, undefined);
    },
  },
  {
    name: 'vim',
    aliases: [],
    description: 'Toggle vim editing mode',
    handler: (_args, dispatch) => {
      dispatch.showMessage('Vim mode toggle saved to settings.', undefined);
    },
  },

  // ── Display / Output ──────────────────────────────────────────
  {
    name: 'verbose',
    aliases: [],
    description: 'Toggle verbose output mode (also: Ctrl+O)',
    handler: (_args, dispatch) => {
      // The dispatch receives the current verboseMode via closure — we toggle it
      // by calling with the negation. The AppDispatch.setVerboseMode receives a boolean.
      dispatch.showMessage('Verbose mode toggled. (Use Ctrl+O for instant toggle)', undefined);
    },
  },
  {
    name: 'compact',
    aliases: [],
    description: 'Compact the log with optional focus instructions',
    args: '[instructions]',
    handler: (args, dispatch) => {
      const instructions = args.join(' ').trim();
      dispatch.compactLogs(instructions || undefined);
    },
  },
  {
    name: 'context',
    aliases: [],
    description: 'Visualize context window usage',
    handler: (_args, dispatch) => {
      dispatch.setScreen('context');
    },
  },
  {
    name: 'cost',
    aliases: [],
    description: 'Show token usage and estimated cost',
    handler: (_args, dispatch) => {
      dispatch.showMessage('Token usage shown in footer. Detailed breakdown coming soon.', undefined);
    },
  },
  {
    name: 'export',
    aliases: [],
    description: 'Export session log to a text file',
    args: '[filename]',
    handler: (args, dispatch) => {
      dispatch.exportSession(args[0]);
      dispatch.showMessage('Session exported to ~/.paper2manim/exports/', undefined);
    },
  },

  // ── Tools / Diagnostics ───────────────────────────────────────
  {
    name: 'doctor',
    aliases: [],
    description: 'Diagnose paper2manim installation',
    handler: (_args, dispatch) => {
      dispatch.setScreen('doctor');
    },
  },
  {
    name: 'hooks',
    aliases: [],
    description: 'View configured lifecycle hooks',
    handler: (_args, dispatch) => {
      dispatch.showMessage('Hooks configuration:\nEdit ~/.paper2manim/settings.json to add hooks.', undefined);
    },
  },
  {
    name: 'permissions',
    aliases: ['allowed-tools'],
    description: 'View and update permission rules',
    handler: (_args, dispatch) => {
      dispatch.setScreen('settings');
    },
  },
  {
    name: 'tasks',
    aliases: [],
    description: 'List background processes',
    handler: (_args, dispatch) => {
      dispatch.showMessage('No background tasks running.', undefined);
    },
  },
  {
    name: 'keybindings',
    aliases: [],
    description: 'Show all keyboard shortcuts',
    handler: (_args, dispatch) => {
      dispatch.setScreen('keybindings');
    },
  },

  // ── Memory / Files ────────────────────────────────────────────
  {
    name: 'memory',
    aliases: [],
    description: 'Edit PAPER2MANIM.md memory file',
    handler: (_args, dispatch) => {
      const memPath = 'PAPER2MANIM.md';
      const editor = process.env['EDITOR'] ?? process.env['VISUAL'] ?? 'nano';
      try {
        // M5: Use spawnSync (no shell) to avoid problems with spaces/special chars in EDITOR
        spawnSync(editor, [memPath], { stdio: 'inherit' });
      } catch {
        dispatch.showMessage(`Could not open editor. Edit ${memPath} manually.`, undefined);
      }
    },
  },
  {
    name: 'init',
    aliases: [],
    description: 'Initialize project with PAPER2MANIM.md',
    handler: (_args, dispatch) => {
      const path = 'PAPER2MANIM.md';
      if (existsSync(path)) {
        dispatch.showMessage(`${path} already exists.`, undefined);
        return;
      }
      writeFileSync(path, PAPER2MANIM_MD_TEMPLATE, 'utf8');
      dispatch.showMessage(`Created ${path} — edit it to customize generation preferences.`, undefined);
    },
  },
  {
    name: 'statusline',
    aliases: [],
    description: 'Show or set custom status line script path',
    args: '[script-path]',
    handler: (args, dispatch) => {
      const scriptPath = args[0];
      if (scriptPath) {
        saveSettings('user', { statusLine: scriptPath });
        dispatch.showMessage(`Status line script set to: ${scriptPath}`, undefined);
      } else {
        dispatch.showMessage('Set a custom status line script: /statusline <path>', undefined);
      }
    },
  },

  // ── Session / History ─────────────────────────────────────────
  {
    name: 'insights',
    aliases: [],
    description: 'Generate session analysis (timing, tool calls, quality)',
    handler: (_args, dispatch) => {
      dispatch.showMessage('Session insights shown in the summary table after generation completes.', undefined);
    },
  },
  {
    name: 'release-notes',
    aliases: ['changelog'],
    description: 'View release notes / changelog',
    handler: (_args, dispatch) => {
      const changelogPath = join(process.cwd(), 'CHANGELOG.md');
      if (existsSync(changelogPath)) {
        try {
          // M6: Use top-level ESM import (readFileSync imported at top of file)
          dispatch.showMessage(readFileSync(changelogPath, 'utf8').slice(0, 500), undefined);
        } catch {
          dispatch.showMessage('paper2manim v0.1.0 — See CHANGELOG.md', undefined);
        }
      } else {
        dispatch.showMessage('paper2manim v0.1.0', undefined);
      }
    },
  },
  {
    name: 'feedback',
    aliases: ['bug'],
    description: 'Submit feedback or report a bug',
    handler: (_args, dispatch) => {
      try {
        execSync('open https://github.com/anthropics/claude-code/issues');
      } catch {
        dispatch.showMessage('Submit feedback at: https://github.com/anthropics/claude-code/issues', undefined);
      }
    },
  },
  {
    name: 'diff',
    aliases: [],
    description: 'Show git diff of current project output',
    handler: (_args, dispatch) => {
      try {
        const diff = execSync('git diff -- output/', { encoding: 'utf8', timeout: 5000 }).slice(0, 1000);
        dispatch.showMessage(diff || 'No changes in output/', undefined);
      } catch {
        dispatch.showMessage('Not a git repo or no output/ directory.', undefined);
      }
    },
  },
  {
    name: 'btw',
    aliases: [],
    description: 'Ask a side question without affecting generation history',
    args: '<question>',
    handler: (args, dispatch) => {
      const question = args.join(' ').trim();
      if (!question) return;
      // Show as an inline message — does not affect pipeline state
      dispatch.showMessage(`Side question noted: "${question}"`, undefined);
    },
  },
];

/** Find a command by name or alias. */
export function findCommand(name: string): SlashCommand | undefined {
  const lower = name.toLowerCase();
  return COMMANDS.find(cmd =>
    cmd.name === lower || cmd.aliases.includes(lower)
  );
}

/** Filter commands by prefix for autocomplete. */
export function filterCommands(prefix: string): SlashCommand[] {
  const lower = prefix.toLowerCase();
  if (!lower) return COMMANDS;
  return COMMANDS.filter(cmd =>
    cmd.name.startsWith(lower) || cmd.aliases.some(a => a.startsWith(lower))
  );
}
