/**
 * Multi-scope settings loader for paper2manim.
 *
 * Scope priority (highest → lowest): local > project > user
 *   User:    ~/.paper2manim/settings.json
 *   Project: .paper2manim/settings.json  (cwd)
 *   Local:   .paper2manim/settings.local.json  (cwd, gitignored)
 */

import { existsSync, readFileSync, writeFileSync, mkdirSync, unlinkSync, statSync } from 'node:fs';
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

/** H7: Acquire a simple file lock (create lock file, retry up to 3 times).
 *  Stale locks older than 5s are removed automatically. */
function withFileLock(filePath: string, fn: () => void): void {
  const lockPath = filePath + '.lock';
  const maxRetries = 3;
  const retryDelayMs = 200;
  const staleAgeMs = 5000;

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    // Remove stale lock
    if (existsSync(lockPath)) {
      try {
        const age = Date.now() - statSync(lockPath).mtimeMs;
        if (age > staleAgeMs) unlinkSync(lockPath);
      } catch { /* lock already gone */ }
    }

    try {
      // O_EXCL-style: writeFileSync fails if lock already exists via 'wx' flag
      writeFileSync(lockPath, String(process.pid), { flag: 'wx' });
      try {
        fn();
      } finally {
        try { unlinkSync(lockPath); } catch { /* ignore */ }
      }
      return;
    } catch {
      // Lock contention — wait and retry
      const start = Date.now();
      while (Date.now() - start < retryDelayMs) { /* busy wait — short enough */ }
    }
  }
  // Fall back to unlocked write rather than silently dropping the save
  fn();
}

/** Save a partial settings update to a specific scope. */
export function saveSettings(scope: SettingsScope, partial: Partial<Settings>): void {
  const path = getSettingsPath(scope);
  const dir = resolve(path, '..');
  ensureDir(dir);

  withFileLock(path, () => {
    const existing = readJsonSafe(path);
    const merged = { ...existing, ...partial };
    try {
      writeFileSync(path, JSON.stringify(merged, null, 2) + '\n', 'utf8');
    } catch (err) {
      process.stderr.write(`[warn] Failed to save settings (${scope}): ${err}\n`);
    }
  });
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
