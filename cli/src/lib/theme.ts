/**
 * Theme constants — Claude Code-inspired color palette and stage configuration.
 */

export const colors = {
  primary: '#64B4FF',
  success: '#00C853',
  error: '#F44336',
  warn: '#FF9800',
  muted: '#999999',
  text: '#FFFFFF',
  dim: '#888888',
  accent: '#5B9DFF',
} as const;

export const BRAND_ICON = '✻';

export const TIPS = [
  'Use --quality low for faster generation',
  'Press ? during a run to see keyboard shortcuts',
  'Press Ctrl+O to toggle verbose mode live',
  'Use --output-format json for scripting',
  'Pass a concept as an argument to skip the prompt',
  'Use --model to override the Claude model',
];

export type StageName = 'plan' | 'tts' | 'code' | 'render' | 'stitch' | 'concat' | 'done';

export interface StageConfig {
  icon: string;
  color: string;
  label: string;
}

export const stageConfig: Record<StageName, StageConfig> = {
  plan:   { icon: '⏺', color: '#64B4FF', label: 'Plan storyboard' },
  tts:    { icon: '⏺', color: '#9C78FF', label: 'Generate voiceover' },
  code:   { icon: '⏺', color: '#00B4D8', label: 'Generate Manim code' },
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
