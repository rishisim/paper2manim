import React from 'react';
import { EventEmitter } from 'node:events';
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render } from 'ink-testing-library';
import { SlashCommandOverlay } from './SlashCommandOverlay.js';
import { AppContextProvider } from '../context/AppContext.js';
import { DEFAULT_SETTINGS, type Session } from '../lib/types.js';

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

function renderOverlay(query: string) {
  const instance = render(
    <AppContextProvider settings={DEFAULT_SETTINGS} session={baseSession()} gitBranch={null}>
      <SlashCommandOverlay
        query={query}
        onAccept={() => {}}
        onDismiss={() => {}}
        isActive
      />
    </AppContextProvider>,
  );

  return instance.lastFrame() ?? '';
}

describe('SlashCommandOverlay', () => {
  afterEach(() => {
    cleanup();
  });

  it('keeps a stable height across filtered states', async () => {
    const fullFrame = renderOverlay('');
    const singleMatchFrame = renderOverlay('surprise');
    const noMatchFrame = renderOverlay('zzzz-no-such-command');

    await new Promise(resolve => setTimeout(resolve, 20));

    expect(fullFrame.split('\n')).toHaveLength(singleMatchFrame.split('\n').length);
    expect(singleMatchFrame.split('\n')).toHaveLength(noMatchFrame.split('\n').length);
    expect(noMatchFrame).toContain('No matching commands');
  });
});
