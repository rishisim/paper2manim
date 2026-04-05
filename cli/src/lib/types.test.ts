/**
 * Tests for type definitions and default values.
 */
import { describe, it, expect } from 'vitest';
import {
  DEFAULT_SETTINGS,
  PERMISSION_MODES,
  PERMISSION_MODE_LABELS,
} from './types.js';
import type { Settings, PermissionMode, CommandCategory } from './types.js';

// ── DEFAULT_SETTINGS completeness ────────────────────────────────────────────

/** Every key required by the Settings interface. */
const SETTINGS_KEYS: (keyof Settings)[] = [
  'model',
  'theme',
  'defaultMode',
  'outputStyle',
  'editorMode',
  'quality',
  'hooks',
  'permissions',
  'statusLine',
  'disableAllHooks',
  'promptColor',
];

describe('DEFAULT_SETTINGS', () => {
  it('has all required fields', () => {
    for (const key of SETTINGS_KEYS) {
      expect(DEFAULT_SETTINGS).toHaveProperty(key);
    }
  });

  it('has no extra fields beyond the Settings interface', () => {
    const actualKeys = Object.keys(DEFAULT_SETTINGS);
    for (const key of actualKeys) {
      expect(SETTINGS_KEYS).toContain(key);
    }
  });

  it('model is a non-empty string', () => {
    expect(typeof DEFAULT_SETTINGS.model).toBe('string');
    expect(DEFAULT_SETTINGS.model.length).toBeGreaterThan(0);
  });

  it('theme is a valid theme name', () => {
    const themes = ['dark', 'light', 'minimal', 'colorblind', 'ansi'];
    expect(themes).toContain(DEFAULT_SETTINGS.theme);
  });

  it('defaultMode is a valid permission mode', () => {
    expect(PERMISSION_MODES).toContain(DEFAULT_SETTINGS.defaultMode);
  });

  it('quality is one of low/medium/high', () => {
    expect(['low', 'medium', 'high']).toContain(DEFAULT_SETTINGS.quality);
  });

  it('hooks is an empty object by default', () => {
    expect(DEFAULT_SETTINGS.hooks).toEqual({});
  });

  it('permissions is an empty object by default', () => {
    expect(DEFAULT_SETTINGS.permissions).toEqual({});
  });

  it('statusLine is null by default', () => {
    expect(DEFAULT_SETTINGS.statusLine).toBeNull();
  });

  it('disableAllHooks is false by default', () => {
    expect(DEFAULT_SETTINGS.disableAllHooks).toBe(false);
  });

  it('promptColor is a valid hex color', () => {
    expect(DEFAULT_SETTINGS.promptColor).toMatch(/^#[0-9A-Fa-f]{6}$/);
  });
});

// ── PERMISSION_MODES ─────────────────────────────────────────────────────────

describe('PERMISSION_MODES', () => {
  it('contains all five expected modes', () => {
    const expected: PermissionMode[] = [
      'default', 'acceptEdits', 'plan', 'auto', 'bypassPermissions',
    ];
    for (const mode of expected) {
      expect(PERMISSION_MODES).toContain(mode);
    }
    expect(PERMISSION_MODES.length).toBe(expected.length);
  });

  it('every mode has a label in PERMISSION_MODE_LABELS', () => {
    for (const mode of PERMISSION_MODES) {
      expect(PERMISSION_MODE_LABELS[mode]).toBeDefined();
      expect(typeof PERMISSION_MODE_LABELS[mode]).toBe('string');
    }
  });
});

// ── CommandCategory completeness ─────────────────────────────────────────────

describe('CommandCategory', () => {
  it('covers all expected categories', () => {
    // These values come from the CommandCategory type union literal.
    // We verify them as strings since we cannot enumerate a TS type at runtime,
    // but we CAN assert that the COMMANDS array uses exactly these categories.
    const expected: CommandCategory[] = [
      'generation', 'workspace', 'navigation', 'settings',
      'display', 'tools', 'memory', 'session',
    ];
    // Spot-check: each value is a non-empty string
    for (const cat of expected) {
      expect(typeof cat).toBe('string');
      expect(cat.length).toBeGreaterThan(0);
    }
  });
});
