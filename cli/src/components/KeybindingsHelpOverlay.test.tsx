import React from 'react';
import { EventEmitter } from 'node:events';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render } from 'ink-testing-library';
import { AppContextProvider } from '../context/AppContext.js';
import { DEFAULT_SETTINGS, type Session } from '../lib/types.js';
import { KeybindingsHelpOverlay } from './KeybindingsHelpOverlay.js';

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

describe('KeybindingsHelpOverlay', () => {
  afterEach(() => {
    cleanup();
  });

  it('shows first-run essentials with aligned onboarding wording', async () => {
    const instance = render(
      <AppContextProvider settings={DEFAULT_SETTINGS} session={baseSession()} gitBranch={null}>
        <KeybindingsHelpOverlay onBack={vi.fn()} />
      </AppContextProvider>,
    );

    await new Promise(resolve => setTimeout(resolve, 20));
    const frame = instance.lastFrame() ?? '';
    expect(frame).toContain('First-Run Essentials');
    expect(frame).toContain('Advance to the next onboarding step, then generate on Step 3');
    expect(frame).toContain('Move focus between onboarding steps');
    expect(frame).toContain('Open command search (for /generate, /list, /config)');
  });
});
