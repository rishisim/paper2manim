/**
 * Tests for theme definitions and utility functions.
 */
import { describe, it, expect } from 'vitest';
import {
  THEMES,
  PROMPT_COLORS,
  getStageConfig,
  getThemeColors,
  truncatePath,
  cleanStatus,
  segmentPhaseLabels,
  TIPS,
  VERSION,
  BRAND_ICON,
} from './theme.js';
import type { ThemeColors } from './theme.js';
import type { ThemeName } from './types.js';

// Build a stageConfig from the default dark theme for testing
const stageConfig = getStageConfig(getThemeColors('dark'));

// ── Required color fields ────────────────────────────────────────────────────

const REQUIRED_COLOR_FIELDS: (keyof ThemeColors)[] = [
  'primary', 'success', 'error', 'warn',
  'muted', 'text', 'dim', 'accent', 'bg',
];

const THEME_NAMES: ThemeName[] = ['dark', 'light', 'minimal', 'colorblind', 'ansi'];

describe('THEMES', () => {
  it('defines all expected theme names', () => {
    for (const name of THEME_NAMES) {
      expect(THEMES[name]).toBeDefined();
    }
  });

  it('every theme has all required color fields', () => {
    for (const name of THEME_NAMES) {
      const theme = THEMES[name];
      for (const field of REQUIRED_COLOR_FIELDS) {
        expect(theme[field]).toBeDefined();
        expect(typeof theme[field]).toBe('string');
        expect(theme[field].length).toBeGreaterThan(0);
      }
    }
  });

  it('hex color values are valid 7-char hex strings', () => {
    const hexRegex = /^#[0-9A-Fa-f]{6}$/;
    // Only check themes that use hex (ansi uses named colors)
    for (const name of ['dark', 'light', 'minimal', 'colorblind'] as ThemeName[]) {
      const theme = THEMES[name];
      for (const field of REQUIRED_COLOR_FIELDS) {
        expect(theme[field]).toMatch(hexRegex);
      }
    }
  });

  it('ansi theme has valid color values', () => {
    const ansi = THEMES.ansi;
    // Accept either named CSS colors or hex codes
    for (const field of REQUIRED_COLOR_FIELDS) {
      expect(ansi[field]).toMatch(/^(#[0-9A-Fa-f]{3,8}|[a-z]+)$/);
    }
  });
});

// ── getThemeColors ───────────────────────────────────────────────────────────

describe('getThemeColors', () => {
  it('returns the correct theme for each known name', () => {
    for (const name of THEME_NAMES) {
      const result = getThemeColors(name);
      expect(result).toBe(THEMES[name]);
    }
  });

  it('falls back to dark for an unknown theme name', () => {
    const result = getThemeColors('nonexistent' as ThemeName);
    expect(result).toBe(THEMES.dark);
  });
});

// ── PROMPT_COLORS ────────────────────────────────────────────────────────────

describe('PROMPT_COLORS', () => {
  it('has a default entry', () => {
    expect(PROMPT_COLORS['default']).toBeDefined();
  });

  it('all values are valid hex color strings', () => {
    const hexRegex = /^#[0-9A-Fa-f]{6}$/;
    for (const [name, hex] of Object.entries(PROMPT_COLORS)) {
      expect(hex).toMatch(hexRegex);
    }
  });

  it('contains common color names', () => {
    for (const name of ['red', 'blue', 'green', 'yellow', 'purple']) {
      expect(PROMPT_COLORS[name]).toBeDefined();
    }
  });
});

// ── stageConfig ──────────────────────────────────────────────────────────────

describe('stageConfig', () => {
  const EXPECTED_STAGES = ['plan', 'pipeline', 'tts', 'code', 'code_retry', 'verify', 'render', 'stitch', 'timing', 'concat', 'subtitles', 'overlay', 'done'];

  it('covers all expected pipeline stages', () => {
    for (const stage of EXPECTED_STAGES) {
      expect(stageConfig[stage as keyof typeof stageConfig]).toBeDefined();
    }
  });

  it('every stage has icon, color, and label', () => {
    for (const stage of EXPECTED_STAGES) {
      const cfg = stageConfig[stage as keyof typeof stageConfig];
      expect(typeof cfg.icon).toBe('string');
      expect(typeof cfg.color).toBe('string');
      expect(typeof cfg.label).toBe('string');
      expect(cfg.label.length).toBeGreaterThan(0);
    }
  });

  it('done stage has a check-mark icon', () => {
    expect(stageConfig.done.icon).toContain('\u2714'); // heavy check mark ✔
  });
});

// ── segmentPhaseLabels ───────────────────────────────────────────────────────

describe('segmentPhaseLabels', () => {
  it('has entries for common phases', () => {
    for (const phase of ['generate', 'done', 'failed', 'running']) {
      expect(segmentPhaseLabels[phase]).toBeDefined();
    }
  });
});

// ── truncatePath ─────────────────────────────────────────────────────────────

describe('truncatePath', () => {
  it('returns the path unchanged if shorter than maxLen', () => {
    expect(truncatePath('/a/b', 20)).toBe('/a/b');
  });

  it('returns the path unchanged if exactly maxLen', () => {
    expect(truncatePath('12345', 5)).toBe('12345');
  });

  it('truncates long paths with leading "..."', () => {
    const result = truncatePath('/very/long/path/to/some/file.ts', 15);
    expect(result.startsWith('...')).toBe(true);
    expect(result.length).toBe(15);
  });
});

// ── cleanStatus ──────────────────────────────────────────────────────────────

describe('cleanStatus', () => {
  it('strips "Stage X/Y: " prefixes', () => {
    expect(cleanStatus('Stage 2/6: Rendering segments')).toBe('Rendering segments');
  });

  it('strips "[Seg N] " prefixes', () => {
    expect(cleanStatus('[Seg 3] Compiling code')).toBe('Compiling code');
  });

  it('strips trailing dots', () => {
    expect(cleanStatus('Loading...')).toBe('Loading');
  });

  it('strips quality flag parentheticals', () => {
    expect(cleanStatus('Rendering (-ql)')).toBe('Rendering');
  });

  it('capitalizes the first letter', () => {
    expect(cleanStatus('loading assets')).toBe('Loading assets');
  });

  it('handles combined prefixes', () => {
    expect(cleanStatus('Stage 1/6: [Seg 1] running...')).toBe('Running');
  });

  it('returns empty string for empty input', () => {
    expect(cleanStatus('')).toBe('');
  });

  it('strips arrow prefix', () => {
    expect(cleanStatus('  \u2192 Generating code')).toBe('Generating code');
  });
});

// ── Constants ────────────────────────────────────────────────────────────────

describe('constants', () => {
  it('VERSION is a semver-like string', () => {
    expect(VERSION).toMatch(/^\d+\.\d+\.\d+$/);
  });

  it('BRAND_ICON is defined', () => {
    expect(BRAND_ICON.length).toBeGreaterThan(0);
  });

  it('TIPS is a non-empty array of strings', () => {
    expect(TIPS.length).toBeGreaterThan(0);
    for (const tip of TIPS) {
      expect(typeof tip).toBe('string');
    }
  });
});
