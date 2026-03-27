/**
 * Multi-scope settings loader for paper2manim.
 *
 * Scope priority (highest → lowest): local > project > user
 *   User:    ~/.paper2manim/settings.json
 *   Project: .paper2manim/settings.json  (cwd)
 *   Local:   .paper2manim/settings.local.json  (cwd, gitignored)
 */

import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { homedir } from 'node:os';
import type { Settings, ThemeName, PermissionMode } from './types.js';
import { DEFAULT_SETTINGS } from './types.js';

export type SettingsScope = 'user' | 'project' | 'local';

function getUserSettingsDir(): string {
  return join(homedir(), '.paper2manim');
}

function getSessionsDir(): string {
  return join(homedir(), '.paper2manim', 'sessions');
}

function getExportsDir(): string {
  return join(homedir(), '.paper2manim', 'exports');
}

export function getSettingsPath(scope: SettingsScope): string {
  switch (scope) {
    case 'user':
      return join(getUserSettingsDir(), 'settings.json');
    case 'project':
      return join(process.cwd(), '.paper2manim', 'settings.json');
    case 'local':
      return join(process.cwd(), '.paper2manim', 'settings.local.json');
  }
}

function readJsonSafe(path: string): Partial<Settings> {
  try {
    if (!existsSync(path)) return {};
    const raw = readFileSync(path, 'utf8');
    return JSON.parse(raw) as Partial<Settings>;
  } catch {
    return {};
  }
}

function ensureDir(dir: string): void {
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true });
  }
}

/** Load and merge settings from all scopes (local overrides project overrides user). */
export function loadSettings(overrides?: Partial<Settings>): Settings {
  const user = readJsonSafe(getSettingsPath('user'));
  const project = readJsonSafe(getSettingsPath('project'));
  const local = readJsonSafe(getSettingsPath('local'));

  // Ensure user settings dir exists with default file on first run
  const userDir = getUserSettingsDir();
  ensureDir(userDir);
  ensureDir(getSessionsDir());
  ensureDir(getExportsDir());

  const userSettingsPath = getSettingsPath('user');
  if (!existsSync(userSettingsPath)) {
    try {
      writeFileSync(userSettingsPath, JSON.stringify(DEFAULT_SETTINGS, null, 2) + '\n', 'utf8');
    } catch { /* ignore write errors */ }
  }

  return {
    ...DEFAULT_SETTINGS,
    ...user,
    ...project,
    ...local,
    ...(overrides ?? {}),
    // Deep-merge hooks (don't let one scope fully replace another scope's hooks)
    hooks: {
      ...(DEFAULT_SETTINGS.hooks),
      ...(user.hooks ?? {}),
      ...(project.hooks ?? {}),
      ...(local.hooks ?? {}),
      ...(overrides?.hooks ?? {}),
    },
    permissions: {
      ...(DEFAULT_SETTINGS.permissions),
      ...(user.permissions ?? {}),
      ...(project.permissions ?? {}),
      ...(local.permissions ?? {}),
      ...(overrides?.permissions ?? {}),
    },
  };
}

/** Save a partial settings update to a specific scope. */
export function saveSettings(scope: SettingsScope, partial: Partial<Settings>): void {
  const path = getSettingsPath(scope);
  const dir = resolve(path, '..');
  ensureDir(dir);

  const existing = readJsonSafe(path);
  const merged = { ...existing, ...partial };
  writeFileSync(path, JSON.stringify(merged, null, 2) + '\n', 'utf8');
}

/** Parse CLI flags into settings overrides. */
export function flagsToSettingsOverrides(flags: {
  permissionMode?: string;
  model?: string;
  theme?: string;
  quality?: string;
  verbose?: boolean;
  color?: string;
}): Partial<Settings> {
  const overrides: Partial<Settings> = {};
  if (flags.permissionMode) overrides.defaultMode = flags.permissionMode as PermissionMode;
  if (flags.model) overrides.model = flags.model;
  if (flags.theme) overrides.theme = flags.theme as ThemeName;
  if (flags.quality) overrides.quality = flags.quality as 'low' | 'medium' | 'high';
  if (flags.verbose) overrides.outputStyle = 'verbose';
  if (flags.color) overrides.promptColor = flags.color;
  return overrides;
}

export { getUserSettingsDir, getSessionsDir, getExportsDir };
