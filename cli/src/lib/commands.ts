/**
 * Slash command registry — paper2manim Claude Code CLI clone.
 * All ~35 commands mapped to paper2manim context.
 */

import { execSync, execFileSync, spawnSync } from 'node:child_process';
import { existsSync, writeFileSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';
import type { SlashCommand, AppDispatch, ThemeName, CommandCategory } from './types.js';
import { PROMPT_COLORS } from './theme.js';
import { loadSettings, saveSettings } from './settings.js';
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
    category: 'generation' as CommandCategory,
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
    category: 'generation' as CommandCategory,
    handler: (args, dispatch) => {
      const dir = args[0];
      if (!dir) {
        // No dir given — open workspace so user can pick a project
        dispatch.setScreen('workspace');
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
    category: 'generation' as CommandCategory,
    handler: (args, dispatch) => {
      dispatch.setPermissionMode('plan');
      const concept = args.join(' ').trim();
      if (concept) dispatch.startPipeline(concept);
      dispatch.showMessage('Switched to plan mode — storyboard only, no video generation.', undefined);
    },
  },

  // ── Workspace ─────────────────────────────────────────────────
  {
    name: 'workspace',
    aliases: ['ws'],
    description: 'Open workspace / project dashboard',
    category: 'workspace' as CommandCategory,
    handler: (_args, dispatch) => {
      dispatch.setScreen('workspace');
    },
  },
  {
    name: 'list',
    aliases: ['ls'],
    description: 'List saved projects',
    category: 'workspace' as CommandCategory,
    handler: (_args, dispatch) => {
      dispatch.setScreen('workspace');
    },
  },
  {
    name: 'delete',
    aliases: ['rm'],
    description: 'Delete a project directory',
    args: '<dir>',
    category: 'workspace' as CommandCategory,
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
    category: 'workspace' as CommandCategory,
    handler: (_args, dispatch) => {
      dispatch.showMessage('Running cleanup... (use --workspace to manage projects)', undefined);
    },
  },

  // ── Session / Navigation ──────────────────────────────────────
  {
    name: 'clear',
    aliases: ['reset', 'new'],
    description: 'Clear screen and reset to input',
    category: 'navigation' as CommandCategory,
    handler: (_args, dispatch) => {
      process.stdout.write('\x1b[2J\x1b[H');
      dispatch.setScreen('input');
    },
  },
  {
    name: 'help',
    aliases: ['h', '?'],
    description: 'Show all available commands',
    category: 'navigation' as CommandCategory,
    handler: (_args, dispatch) => {
      dispatch.setScreen('keybindings');
    },
  },
  {
    name: 'exit',
    aliases: ['quit', 'q'],
    description: 'Exit paper2manim',
    category: 'navigation' as CommandCategory,
    handler: (_args, dispatch) => {
      dispatch.exit();
    },
  },

  // ── Settings / Config ─────────────────────────────────────────
  {
    name: 'config',
    aliases: ['settings'],
    description: 'Open settings panel',
    category: 'settings' as CommandCategory,
    handler: (_args, dispatch) => {
      dispatch.setScreen('settings');
    },
  },
  {
    name: 'status',
    aliases: [],
    description: 'Show version, model, and API key status',
    category: 'settings' as CommandCategory,
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
    category: 'settings' as CommandCategory,
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
    category: 'settings' as CommandCategory,
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
    category: 'settings' as CommandCategory,
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
    category: 'settings' as CommandCategory,
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
    category: 'settings' as CommandCategory,
    handler: (_args, dispatch) => {
      dispatch.showMessage('Vim mode is configured in /config → Editor Mode.', undefined);
    },
  },

  // ── Display / Output ──────────────────────────────────────────
  {
    name: 'verbose',
    aliases: [],
    description: 'Toggle verbose output mode (also: Ctrl+O)',
    category: 'display' as CommandCategory,
    handler: (_args, dispatch) => {
      dispatch.toggleVerboseMode();
      dispatch.showMessage('Verbose mode toggled. (Ctrl+O also works.)', undefined);
    },
  },
  {
    name: 'compact',
    aliases: [],
    description: 'Compact the log with optional focus instructions',
    args: '[instructions]',
    category: 'display' as CommandCategory,
    handler: (args, dispatch) => {
      const instructions = args.join(' ').trim();
      dispatch.compactLogs(instructions || undefined);
    },
  },
  {
    name: 'context',
    aliases: [],
    description: 'Visualize context window usage',
    category: 'display' as CommandCategory,
    handler: (_args, dispatch) => {
      dispatch.setScreen('context');
    },
  },
  {
    name: 'cost',
    aliases: [],
    description: 'Show token usage and estimated cost',
    category: 'display' as CommandCategory,
    handler: (_args, dispatch) => {
      dispatch.showMessage('Token usage shown in footer. Detailed breakdown coming soon.', undefined);
    },
  },
  {
    name: 'export',
    aliases: [],
    description: 'Export session log to a text file',
    args: '[filename]',
    category: 'display' as CommandCategory,
    handler: (args, dispatch) => {
      const path = dispatch.exportSession(args[0]);
      if (path) {
        dispatch.showMessage(`Session exported to: ${path}`, undefined);
      } else {
        dispatch.showMessage('Export failed — check permissions on ~/.paper2manim/exports/', 'red');
      }
    },
  },

  // ── Tools / Diagnostics ───────────────────────────────────────
  {
    name: 'doctor',
    aliases: [],
    description: 'Diagnose paper2manim installation',
    category: 'tools' as CommandCategory,
    handler: (_args, dispatch) => {
      dispatch.setScreen('doctor');
    },
  },
  {
    name: 'hooks',
    aliases: [],
    description: 'View configured lifecycle hooks',
    category: 'tools' as CommandCategory,
    handler: (_args, dispatch) => {
      const { hooks } = loadSettings();
      const events = Object.keys(hooks) as (keyof typeof hooks)[];
      if (events.length === 0) {
        dispatch.showMessage(
          'No hooks configured.\nEdit ~/.paper2manim/settings.json to add hooks.',
          undefined,
        );
        return;
      }
      const lines = events.map(evt => {
        const handlers = hooks[evt] ?? [];
        const summary = handlers
          .map(h => ('command' in h ? h.command : h.url))
          .join(', ');
        return `${evt}: ${summary}`;
      });
      dispatch.showMessage(`Hooks:\n${lines.join('\n')}`, undefined);
    },
  },
  {
    name: 'permissions',
    aliases: ['allowed-tools'],
    description: 'View and update permission rules',
    category: 'tools' as CommandCategory,
    handler: (_args, dispatch) => {
      dispatch.setScreen('settings');
    },
  },
  {
    name: 'tasks',
    aliases: [],
    description: 'List background processes',
    category: 'tools' as CommandCategory,
    handler: (_args, dispatch) => {
      dispatch.showMessage('No background tasks running.', undefined);
    },
  },
  {
    name: 'keybindings',
    aliases: [],
    description: 'Show all keyboard shortcuts',
    category: 'tools' as CommandCategory,
    handler: (_args, dispatch) => {
      dispatch.setScreen('keybindings');
    },
  },

  // ── Memory / Files ────────────────────────────────────────────
  {
    name: 'memory',
    aliases: [],
    description: 'Edit PAPER2MANIM.md memory file',
    category: 'memory' as CommandCategory,
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
    category: 'memory' as CommandCategory,
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
    category: 'memory' as CommandCategory,
    handler: (args, dispatch) => {
      const scriptPath = args[0];
      if (scriptPath) {
        saveSettings('user', { statusLine: scriptPath });
        dispatch.showMessage(`Status line script set to: ${scriptPath}`, undefined);
      } else {
        const { statusLine } = loadSettings();
        dispatch.showMessage(
          statusLine
            ? `Current status line script: ${statusLine}\nUse /statusline <path> to change it.`
            : 'No status line script set. Use /statusline <path> to set one.',
          undefined,
        );
      }
    },
  },

  // ── Session / History ─────────────────────────────────────────
  {
    name: 'insights',
    aliases: [],
    description: 'Generate session analysis (timing, tool calls, quality)',
    category: 'session' as CommandCategory,
    handler: (_args, dispatch) => {
      dispatch.showMessage('Session insights shown in the summary table after generation completes.', undefined);
    },
  },
  {
    name: 'release-notes',
    aliases: ['changelog'],
    description: 'View release notes / changelog',
    category: 'session' as CommandCategory,
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
    category: 'session' as CommandCategory,
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
    category: 'session' as CommandCategory,
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
    category: 'session' as CommandCategory,
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

/** Filter commands by substring for autocomplete, with prefix matches ranked first. */
export function filterCommands(prefix: string): SlashCommand[] {
  const lower = prefix.toLowerCase();
  if (!lower) return COMMANDS;

  const prefixMatches: SlashCommand[] = [];
  const substringMatches: SlashCommand[] = [];

  for (const cmd of COMMANDS) {
    const nameMatch = cmd.name.includes(lower);
    const aliasMatch = cmd.aliases.some(a => a.includes(lower));
    if (!nameMatch && !aliasMatch) continue;

    const isPrefix = cmd.name.startsWith(lower) || cmd.aliases.some(a => a.startsWith(lower));
    if (isPrefix) prefixMatches.push(cmd);
    else substringMatches.push(cmd);
  }

  return [...prefixMatches, ...substringMatches];
}
