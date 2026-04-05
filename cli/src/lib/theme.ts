/**
 * Theme constants — Claude Code-inspired color palette and stage configuration.
 */

import type { ThemeName } from './types.js';

export interface ThemeColors {
  primary: string;
  success: string;
  error: string;
  warn: string;
  muted: string;
  text: string;
  dim: string;
  accent: string;
  bg: string;
}

export const colors: ThemeColors = {
  primary: '#64B4FF',
  success: '#00C853',
  error: '#F44336',
  warn: '#FF9800',
  muted: '#999999',
  text: '#FFFFFF',
  dim: '#888888',
  accent: '#5B9DFF',
  bg: '#000000',
} as const;

export const THEMES: Record<ThemeName, ThemeColors> = {
  dark: {
    primary: '#64B4FF',
    success: '#00C853',
    error: '#F44336',
    warn: '#FF9800',
    muted: '#999999',
    text: '#FFFFFF',
    dim: '#888888',
    accent: '#5B9DFF',
    bg: '#000000',
  },
  light: {
    primary: '#0066CC',
    success: '#00873C',
    error: '#CC0000',
    warn: '#CC6600',
    muted: '#666666',
    text: '#000000',
    dim: '#555555',
    accent: '#0052A3',
    bg: '#FFFFFF',
  },
  minimal: {
    primary: '#AAAAAA',
    success: '#AAAAAA',
    error: '#AAAAAA',
    warn: '#AAAAAA',
    muted: '#888888',
    text: '#FFFFFF',
    dim: '#666666',
    accent: '#AAAAAA',
    bg: '#000000',
  },
  colorblind: {
    primary: '#0072B2',  // Blue
    success: '#009E73',  // Teal
    error: '#D55E00',    // Vermillion
    warn: '#E69F00',     // Orange
    muted: '#999999',
    text: '#FFFFFF',
    dim: '#888888',
    accent: '#56B4E9',   // Sky blue
    bg: '#000000',
  },
  ansi: {
    primary: 'cyan',
    success: 'green',
    error: 'red',
    warn: 'yellow',
    muted: 'gray',
    text: 'white',
    dim: 'gray',
    accent: 'blue',
    bg: 'black',
  },
};

export const PROMPT_COLORS: Record<string, string> = {
  red:    '#F44336',
  blue:   '#64B4FF',
  green:  '#00C853',
  yellow: '#FFD600',
  purple: '#9C78FF',
  orange: '#FF9800',
  pink:   '#FF6496',
  cyan:   '#00B4D8',
  white:  '#FFFFFF',
  default: '#64B4FF',
};

export function getThemeColors(theme: ThemeName): ThemeColors {
  return THEMES[theme] ?? THEMES.dark;
}

export const BRAND_ICON = '✻';

export const TIPS = [
  'Use --quality low for faster generation',
  'Press ? during a run to see keyboard shortcuts',
  'Press Ctrl+O to toggle verbose mode live',
  'Use --output-format json for scripting',
  'Pass a concept as an argument to skip the prompt',
  'Use --model to override the Claude model',
];

export type StageName = 'plan' | 'tts' | 'code' | 'verify' | 'render' | 'stitch' | 'concat' | 'done';

export interface StageConfig {
  icon: string;
  color: string;
  label: string;
}

export const stageConfig: Record<StageName, StageConfig> = {
  plan:   { icon: '⏺', color: '#64B4FF', label: 'Plan storyboard' },
  tts:    { icon: '⏺', color: '#9C78FF', label: 'Generate voiceover' },
  code:   { icon: '⏺', color: '#00B4D8', label: 'Generate Manim code' },
  verify: { icon: '⏺', color: '#E0A040', label: 'Verify code quality' },
  render: { icon: '⏺', color: '#FF6496', label: 'Render HD segments' },
  stitch: { icon: '⏺', color: '#FFB432', label: 'Stitch audio/video' },
  concat: { icon: '⏺', color: '#00C853', label: 'Assemble final video' },
  done:   { icon: '✓', color: '#00C853', label: 'Complete' },
};

export const segmentPhaseLabels: Record<string, string> = {
  generate: 'Generating initial script',
  docs: 'Looking up docs',
  execute: 'Rendering draft (-ql)',
  self_correct: 'Self-correcting',
  fix_docs: 'Fix: looking up docs',
  apply_fix: 'Applying fix',
  verify: 'Verifying code quality',
  verify_fix: 'Fixing verification issues',
  done: 'Complete',
  failed: 'Failed',
  running: 'Running',
};

export function truncatePath(p: string, maxLen: number): string {
  if (p.length <= maxLen) return p;
  return '...' + p.slice(p.length - maxLen + 3);
}

export const VERSION = '0.1.0';
export const MODEL_TAG = 'claude-opus-4.6 + gemini-3.1-pro';

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
