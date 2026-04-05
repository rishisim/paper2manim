/**
 * Theme constants — color palette and stage configuration.
 *
 * All components must use `themeColors` from `useAppContext()` — never import
 * static color values directly. The `getStageConfig(theme)` function derives
 * stage colors from the active theme.
 */

import type { ThemeName } from './types.js';

export interface ThemeColors {
  // Core palette
  primary: string;
  success: string;
  error: string;
  warn: string;
  accent: string;

  // Text hierarchy
  text: string;
  muted: string;
  dim: string;

  // Surfaces & chrome
  bg: string;
  surface: string;        // subtle panel/box background
  separator: string;      // dividers and rules

  // Progress bar
  progressFill: string;
  progressTrack: string;

  // Context usage — three-tier (Claude Code style)
  contextLow: string;     // healthy (<50k tokens)
  contextMid: string;     // warning (50-150k)
  contextHigh: string;    // critical (>150k)
}

export const THEMES: Record<ThemeName, ThemeColors> = {
  dark: {
    primary: '#D77757',      // Claude terracotta orange
    success: '#4EBA65',      // Claude green
    error: '#FF6B80',        // Claude soft pink-red
    warn: '#FFC107',         // Claude yellow
    accent: '#B1B9F9',       // Claude lavender (permission/suggestion)
    text: '#FFFFFF',
    muted: '#999999',        // Claude "inactive"
    dim: '#888888',          // Claude "promptBorder"
    bg: '#000000',
    surface: '#1A1A1A',
    separator: '#505050',    // Claude "subtle"
    progressFill: '#D77757',
    progressTrack: '#333333',
    contextLow: '#4EBA65',
    contextMid: '#FFC107',
    contextHigh: '#FF6B80',
  },
  light: {
    primary: '#D77757',      // Claude brand stays same
    success: '#2C7A39',      // Claude light-mode green
    error: '#AB2B3F',        // Claude light-mode red
    warn: '#966C1E',         // Claude light-mode yellow
    accent: '#5769F7',       // Claude light-mode suggestion
    text: '#000000',
    muted: '#666666',        // Claude light "inactive"
    dim: '#999999',          // Claude light "promptBorder"
    bg: '#FFFFFF',
    surface: '#F0EEE6',      // Claude light surface
    separator: '#AFAFAF',    // Claude light "subtle"
    progressFill: '#D77757',
    progressTrack: '#DDDDDD',
    contextLow: '#2C7A39',
    contextMid: '#966C1E',
    contextHigh: '#AB2B3F',
  },
  minimal: {
    primary: '#E0E0E0',
    success: '#AADDAA',
    error: '#FFAAAA',
    warn: '#FFDDAA',
    accent: '#AACCEE',
    text: '#FFFFFF',
    muted: '#999999',
    dim: '#777777',
    bg: '#000000',
    surface: '#1A1A1A',
    separator: '#444444',
    progressFill: '#E0E0E0',
    progressTrack: '#333333',
    contextLow: '#AADDAA',
    contextMid: '#FFDDAA',
    contextHigh: '#FFAAAA',
  },
  colorblind: {
    primary: '#0072B2',
    success: '#009E73',
    error: '#D55E00',
    warn: '#E69F00',
    accent: '#56B4E9',
    text: '#FFFFFF',
    muted: '#999999',
    dim: '#888888',
    bg: '#000000',
    surface: '#1A1A1A',
    separator: '#505050',
    progressFill: '#0072B2',
    progressTrack: '#333333',
    contextLow: '#009E73',
    contextMid: '#E69F00',
    contextHigh: '#D55E00',
  },
  ansi: {
    primary: '#CC6600',      // warm orange (ansi approx of terracotta)
    success: '#00CC00',      // bright green
    error: '#CC0000',        // bright red
    warn: '#CCCC00',         // bright yellow
    accent: '#5555FF',       // bright blue
    text: '#CCCCCC',         // white
    muted: '#888888',        // gray
    dim: '#888888',          // gray
    bg: '#000000',           // black
    surface: '#000000',      // black
    separator: '#555555',    // gray
    progressFill: '#CC6600',
    progressTrack: '#888888',
    contextLow: '#00CC00',
    contextMid: '#CCCC00',
    contextHigh: '#CC0000',
  },
};

export const PROMPT_COLORS: Record<string, string> = {
  red:    '#FF6B80',
  blue:   '#7AB4E8',
  green:  '#4EBA65',
  yellow: '#FFC107',
  purple: '#AF87FF',
  orange: '#D77757',
  pink:   '#FD5DB1',
  cyan:   '#00CCCC',
  white:  '#FFFFFF',
  default: '#888888',     // Claude Code uses gray prompt border
};

export function getThemeColors(theme: ThemeName): ThemeColors {
  return THEMES[theme] ?? THEMES.dark;
}

export const BRAND_ICON = '✻';
export const PROMPT_CHAR = '>';       // Claude Code uses > in success color
export const RESULT_MARKER = '⎿';    // Claude Code tool result indent marker

/** Mode indicator symbols matching Claude Code. */
export const MODE_SYMBOLS: Record<string, string> = {
  default: '',
  acceptEdits: '⏵⏵',
  auto: '⏵⏵',
  plan: '⏸',
  bypassPermissions: '⏵⏵',
};

export const TIPS = [
  'Use --quality low for faster generation',
  'Press ? during a run to see keyboard shortcuts',
  'Press Ctrl+O to toggle verbose mode live',
  'Use --output-format json for scripting',
  'Pass a concept as an argument to skip the prompt',
  'Use --model to override the Claude model',
];

export type StageName = 'plan' | 'tts' | 'code' | 'code_retry' | 'verify' | 'render' | 'timing' | 'concat' | 'overlay' | 'done';

export interface StageConfig {
  icon: string;
  color: string;
  label: string;
}

/** Derive stage colors from the active theme instead of hardcoding hex values. */
export function getStageConfig(theme: ThemeColors): Record<StageName, StageConfig> {
  return {
    plan:       { icon: '⏺', color: theme.primary,  label: 'Plan storyboard' },
    tts:        { icon: '⏺', color: theme.accent,   label: 'Generate voiceover' },
    code:       { icon: '⏺', color: theme.primary,  label: 'Generate Manim code' },
    code_retry: { icon: '⏺', color: theme.warn,     label: 'Retrying failed segments' },
    verify:      { icon: '⏺', color: theme.warn,     label: 'Verify code quality' },
    render:      { icon: '⏺', color: theme.accent,   label: 'Render HD segments' },
    timing:      { icon: '⏺', color: theme.accent,   label: 'Check audio/video timing' },
    concat:      { icon: '⏺', color: theme.success,  label: 'Assemble final video' },
    overlay:     { icon: '⏺', color: theme.success,  label: 'Overlay audio track' },
    done:        { icon: '✔', color: theme.success,  label: 'Complete' },
  };
}

export const segmentPhaseLabels: Record<string, string> = {
  generate: 'Generating initial script',
  docs: 'Looking up docs',
  execute: 'Rendering draft (-ql)',
  self_correct: 'Self-correcting',
  fix_docs: 'Fix: looking up docs',
  apply_fix: 'Applying fix',
  done: 'Complete',
  failed: 'Failed',
  running: 'Running',
  retry_queued: 'Queued for retry',
};

export function truncatePath(p: string, maxLen: number): string {
  if (p.length <= maxLen) return p;
  return '...' + p.slice(p.length - maxLen + 3);
}

export const VERSION = '0.1.0';
export const MODEL_TAG = 'claude-opus-4.6 + gemini-2.5-tts + gemini-3.1-live';

/**
 * Clean up a raw pipeline status string for user-facing display.
 * Strips internal prefixes, technical detail, and redundant info.
 */
export function cleanStatus(raw: string): string {
  let s = raw.trim();

  // Strip "Stage X/Y: " prefix — stage is already shown in the header
  s = s.replace(/^Stage \d+\/\d+:\s*/i, '');

  // Strip "[Seg N] " prefix — segment is already tracked separately
  s = s.replace(/^\[Seg \d+\]\s*/i, '');

  // Strip trailing "..." (we add our own)
  s = s.replace(/\.{2,}$/, '');

  // Strip parenthetical internal details
  s = s.replace(/\s*\(-?q[lh]\)/g, '');            // quality flags (-ql), (-qh)
  s = s.replace(/\s*\(target:.*?\)/g, '');          // (target: 90s, 2-3 segments)
  s = s.replace(/\s*\(parallel,.*?\)/g, '');        // (parallel, 2000+ tokens...)
  s = s.replace(/\s*\(Fast render.*?\)/g, '');      // (Fast render -ql)

  // Strip "→ " prefix (pipeline arrow notation)
  s = s.replace(/^\s*→\s*/, '');

  // Strip verbose phrasing
  s = s.replace(/^Composing verbose narrative/, 'Composing');

  // Capitalize first letter
  s = s.trim();
  if (s.length > 0) {
    s = s.charAt(0).toUpperCase() + s.slice(1);
  }

  return s;
}
