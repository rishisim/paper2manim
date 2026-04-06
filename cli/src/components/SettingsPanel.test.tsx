import React from 'react';
import { EventEmitter } from 'node:events';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render } from 'ink-testing-library';
import { SettingsPanel } from './SettingsPanel.js';
import { AppContextProvider } from '../context/AppContext.js';
import { DEFAULT_SETTINGS, type Session } from '../lib/types.js';

vi.mock('../lib/settings.js', () => ({
  getSettingsPath: vi.fn((scope: string) => `/tmp/${scope}.json`),
  loadSettings: vi.fn(),
  saveSettings: vi.fn(),
}));

import { loadSettings, saveSettings } from '../lib/settings.js';

const mockedLoadSettings = vi.mocked(loadSettings);
const mockedSaveSettings = vi.mocked(saveSettings);

(EventEmitter.prototype as EventEmitter & { ref?: () => void; unref?: () => void }).ref ??= () => {};
(EventEmitter.prototype as EventEmitter & { ref?: () => void; unref?: () => void }).unref ??= () => {};

function baseSession(): Session {
  return {
    id: 'test-session',
    name: null,
    startedAt: '2026-04-05T00:00:00Z',
    concept: '',
    stage: null,
    checkpoints: [],
    tokenUsage: { input: 0, output: 0, cacheRead: 0 },
    permissionMode: 'default',
  };
}

describe('SettingsPanel', () => {
  beforeEach(() => {
    mockedLoadSettings.mockReset();
    mockedSaveSettings.mockReset();
    mockedLoadSettings.mockReturnValue(DEFAULT_SETTINGS);
  });

  afterEach(() => {
    cleanup();
  });

  it('shows effective vs scope values and editable inline controls', async () => {
    const instance = render(
      <AppContextProvider settings={DEFAULT_SETTINGS} session={baseSession()} gitBranch={null}>
        <SettingsPanel onBack={vi.fn()} />
      </AppContextProvider>,
    );

    await new Promise(resolve => setTimeout(resolve, 20));
    const frame = instance.lastFrame() ?? '';
    expect(frame).toContain('effective=');
    expect(frame).toContain('inherit');
    expect(frame).toContain('(Enter to cycle)');
    expect(frame).toContain('Legend:');
    expect(mockedSaveSettings).not.toHaveBeenCalled();
  });
});
