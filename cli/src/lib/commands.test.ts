/**
 * Tests for the slash command registry.
 */
import { describe, it, expect, vi } from 'vitest';
import { COMMANDS, findCommand, filterCommands } from './commands.js';
import type { AppDispatch, CommandCategory } from './types.js';

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Build a mock AppDispatch where every method is a vi.fn(). */
function mockDispatch(): AppDispatch {
  return {
    setScreen: vi.fn(),
    setPermissionMode: vi.fn(),
    setVerboseMode: vi.fn(),
    toggleVerboseMode: vi.fn(),
    setThinkingVisible: vi.fn(),
    setPromptColor: vi.fn(),
    setCurrentModel: vi.fn(),
    setTheme: vi.fn(),
    setQuality: vi.fn(),
    startPipeline: vi.fn(),
    resumePipeline: vi.fn(),
    retryPipeline: vi.fn(),
    compactLogs: vi.fn(),
    exportSession: vi.fn(() => null),
    killPipeline: vi.fn(),
    exit: vi.fn(),
    showMessage: vi.fn(),
    setPromptText: vi.fn(),
  };
}

const VALID_CATEGORIES: CommandCategory[] = [
  'generation', 'workspace', 'navigation', 'settings',
  'display', 'tools', 'memory', 'session',
];

// ── Registry integrity ───────────────────────────────────────────────────────

describe('COMMANDS registry integrity', () => {
  it('has at least one command', () => {
    expect(COMMANDS.length).toBeGreaterThan(0);
  });

  it('all command names are unique', () => {
    const names = COMMANDS.map(c => c.name);
    expect(new Set(names).size).toBe(names.length);
  });

  it('all aliases are unique across the entire registry', () => {
    const seen = new Set<string>();
    for (const cmd of COMMANDS) {
      for (const alias of cmd.aliases) {
        expect(seen.has(alias)).toBe(false);
        seen.add(alias);
      }
    }
  });

  it('no alias collides with any command name', () => {
    const names = new Set(COMMANDS.map(c => c.name));
    for (const cmd of COMMANDS) {
      for (const alias of cmd.aliases) {
        expect(names.has(alias)).toBe(false);
      }
    }
  });

  it('every command has a handler function', () => {
    for (const cmd of COMMANDS) {
      expect(typeof cmd.handler).toBe('function');
    }
  });

  it('every command has a valid category', () => {
    for (const cmd of COMMANDS) {
      expect(VALID_CATEGORIES).toContain(cmd.category);
    }
  });

  it('every command has a non-empty description', () => {
    for (const cmd of COMMANDS) {
      expect(cmd.description.length).toBeGreaterThan(0);
    }
  });

  it('aliases is always an array (even if empty)', () => {
    for (const cmd of COMMANDS) {
      expect(Array.isArray(cmd.aliases)).toBe(true);
    }
  });
});

// ── findCommand ──────────────────────────────────────────────────────────────

describe('findCommand', () => {
  it('finds a command by its exact name', () => {
    const cmd = findCommand('help');
    expect(cmd).toBeDefined();
    expect(cmd!.name).toBe('help');
  });

  it('finds a command by an alias', () => {
    const cmd = findCommand('h');
    expect(cmd).toBeDefined();
    expect(cmd!.name).toBe('help');
  });

  it('is case-insensitive', () => {
    const cmd = findCommand('HELP');
    expect(cmd).toBeDefined();
    expect(cmd!.name).toBe('help');
  });

  it('returns undefined for a nonexistent command', () => {
    expect(findCommand('nonexistent_xyz')).toBeUndefined();
  });
});

// ── filterCommands ───────────────────────────────────────────────────────────

describe('filterCommands', () => {
  it('returns all commands when prefix is empty', () => {
    const result = filterCommands('');
    expect(result.length).toBe(COMMANDS.length);
  });

  it('filters by prefix — "he" matches "help"', () => {
    const result = filterCommands('he');
    const names = result.map(c => c.name);
    expect(names).toContain('help');
  });

  it('prefix matches come before substring matches', () => {
    // "gen" should match "generate" (prefix) before any substring-only match
    const result = filterCommands('gen');
    expect(result.length).toBeGreaterThan(0);
    expect(result[0].name).toBe('generate');
  });

  it('returns empty array when nothing matches', () => {
    const result = filterCommands('zzzzzzz');
    expect(result.length).toBe(0);
  });
});

// ── Individual command handlers ──────────────────────────────────────────────

describe('command handlers', () => {
  it('/clear resets to input screen', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('clear')!;
    cmd.handler([], dispatch);
    expect(dispatch.setScreen).toHaveBeenCalledWith('input');
  });

  it('/help navigates to keybindings screen', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('help')!;
    cmd.handler([], dispatch);
    expect(dispatch.setScreen).toHaveBeenCalledWith('keybindings');
  });

  it('/exit calls dispatch.exit()', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('exit')!;
    cmd.handler([], dispatch);
    expect(dispatch.exit).toHaveBeenCalled();
  });

  it('/theme with a valid theme name calls setTheme', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('theme')!;
    cmd.handler(['dark'], dispatch);
    expect(dispatch.setTheme).toHaveBeenCalledWith('dark');
    expect(dispatch.showMessage).toHaveBeenCalledWith('Theme set to: dark', undefined);
  });

  it('/theme with an invalid name shows available themes', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('theme')!;
    cmd.handler(['nope'], dispatch);
    expect(dispatch.setTheme).not.toHaveBeenCalled();
    expect(dispatch.showMessage).toHaveBeenCalledWith(
      expect.stringContaining('Available themes'),
      undefined,
    );
  });

  it('/theme with no args shows available themes', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('theme')!;
    cmd.handler([], dispatch);
    expect(dispatch.setTheme).not.toHaveBeenCalled();
    expect(dispatch.showMessage).toHaveBeenCalledWith(
      expect.stringContaining('Available themes'),
      undefined,
    );
  });

  it('/model openai expands to openai-default', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('model')!;
    cmd.handler(['openai'], dispatch);
    expect(dispatch.setCurrentModel).toHaveBeenCalledWith('openai-default');
  });

  it('/model anthropic expands to anthropic-legacy', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('model')!;
    cmd.handler(['anthropic'], dispatch);
    expect(dispatch.setCurrentModel).toHaveBeenCalledWith('anthropic-legacy');
  });

  it('/model with a custom model id passes it through', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('model')!;
    cmd.handler(['gpt-5.4'], dispatch);
    expect(dispatch.setCurrentModel).toHaveBeenCalledWith('gpt-5.4');
  });

  it('/model with no args shows usage', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('model')!;
    cmd.handler([], dispatch);
    expect(dispatch.setCurrentModel).not.toHaveBeenCalled();
    expect(dispatch.showMessage).toHaveBeenCalledWith(
      expect.stringContaining('Usage'),
      undefined,
    );
  });

  it('/quality sets quality when valid', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('quality')!;
    cmd.handler(['low'], dispatch);
    expect(dispatch.setQuality).toHaveBeenCalledWith('low');
  });

  it('/quality with invalid value shows usage', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('quality')!;
    cmd.handler(['ultra'], dispatch);
    expect(dispatch.setQuality).not.toHaveBeenCalled();
    expect(dispatch.showMessage).toHaveBeenCalledWith(
      expect.stringContaining('Usage'),
      undefined,
    );
  });

  it('/generate without args shows usage message', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('generate')!;
    cmd.handler([], dispatch);
    expect(dispatch.startPipeline).not.toHaveBeenCalled();
    expect(dispatch.showMessage).toHaveBeenCalledWith(
      expect.stringContaining('Usage'),
      undefined,
    );
  });

  it('/generate with a concept starts the pipeline', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('generate')!;
    cmd.handler(['fourier', 'transform'], dispatch);
    expect(dispatch.startPipeline).toHaveBeenCalledWith('fourier transform');
  });

  it('/verbose toggles verbose mode', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('verbose')!;
    cmd.handler([], dispatch);
    expect(dispatch.toggleVerboseMode).toHaveBeenCalled();
  });

  it('/workspace navigates to workspace screen', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('workspace')!;
    cmd.handler([], dispatch);
    expect(dispatch.setScreen).toHaveBeenCalledWith('workspace');
  });

  it('/config navigates to settings screen', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('config')!;
    cmd.handler([], dispatch);
    expect(dispatch.setScreen).toHaveBeenCalledWith('settings');
  });

  it('/doctor navigates to doctor screen', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('doctor')!;
    cmd.handler([], dispatch);
    expect(dispatch.setScreen).toHaveBeenCalledWith('doctor');
  });

  it('/color with a valid name calls setPromptColor', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('color')!;
    cmd.handler(['red'], dispatch);
    expect(dispatch.setPromptColor).toHaveBeenCalledWith('#D28A96');
  });

  it('/color with an invalid name shows available colors', () => {
    const dispatch = mockDispatch();
    const cmd = findCommand('color')!;
    cmd.handler(['chartreuse'], dispatch);
    expect(dispatch.setPromptColor).not.toHaveBeenCalled();
    expect(dispatch.showMessage).toHaveBeenCalledWith(
      expect.stringContaining('Available colors'),
      undefined,
    );
  });
});
