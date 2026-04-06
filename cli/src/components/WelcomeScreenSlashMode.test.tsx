import React from 'react';
import { EventEmitter } from 'node:events';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render } from 'ink-testing-library';
import { AppContextProvider } from '../context/AppContext.js';
import { DEFAULT_SETTINGS, type AppDispatch, type Session } from '../lib/types.js';

const promptBarMockState = vi.hoisted(() => ({
  mountEvents: 0,
  unmountEvents: 0,
}));

vi.mock('../hooks/useRecentProjects.js', () => ({
  useRecentProjects: vi.fn(() => ({ projects: [], loading: false })),
}));

vi.mock('../hooks/useTerminalWidth.js', () => ({
  useTerminalWidth: vi.fn(() => 110),
}));

vi.mock('../hooks/useTerminalHeight.js', () => ({
  useTerminalHeight: vi.fn(() => 40),
}));

vi.mock('./PromptBar.js', async () => {
  const ReactModule = await import('react');
  const { Text } = await import('ink');

  return {
    PromptBar: ({ onSlashModeChange }: { onSlashModeChange?: (active: boolean) => void }) => {
      ReactModule.useEffect(() => {
        promptBarMockState.mountEvents += 1;
        onSlashModeChange?.(true);

        return () => {
          promptBarMockState.unmountEvents += 1;
        };
      }, [onSlashModeChange]);

      return ReactModule.createElement(Text, null, '[PromptBar]');
    },
  };
});

import { WelcomeScreen } from './WelcomeScreen.js';

(EventEmitter.prototype as EventEmitter & { ref?: () => void; unref?: () => void }).ref ??= () => {};
(EventEmitter.prototype as EventEmitter & { ref?: () => void; unref?: () => void }).unref ??= () => {};

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

describe('WelcomeScreen slash mode', () => {
  beforeEach(() => {
    promptBarMockState.mountEvents = 0;
    promptBarMockState.unmountEvents = 0;
  });

  afterEach(() => {
    cleanup();
  });

  it('keeps PromptBar mounted when slash mode opens', async () => {
    const instance = render(
      <AppContextProvider settings={DEFAULT_SETTINGS} session={baseSession()} gitBranch={null}>
        <WelcomeScreen
          onSubmit={vi.fn()}
          onResumeProject={vi.fn()}
          dispatch={mockDispatch()}
        />
      </AppContextProvider>,
    );

    await new Promise(resolve => setTimeout(resolve, 20));

    const frame = instance.lastFrame() ?? '';
    expect(frame).toContain('Slash Commands');
    expect(frame).toContain('Type `/` to browse, keep typing to filter');
    expect(promptBarMockState.mountEvents).toBe(1);
    expect(promptBarMockState.unmountEvents).toBe(0);
  });
});
