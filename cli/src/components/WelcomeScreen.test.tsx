import React from 'react';
import { EventEmitter } from 'node:events';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, cleanup } from 'ink-testing-library';
import { WelcomeScreen } from './WelcomeScreen.js';
import { AppContextProvider } from '../context/AppContext.js';
import { DEFAULT_SETTINGS, type AppDispatch, type Project, type Session } from '../lib/types.js';

vi.mock('../hooks/useRecentProjects.js', () => ({
  useRecentProjects: vi.fn(),
}));

vi.mock('../hooks/useTerminalWidth.js', () => ({
  useTerminalWidth: vi.fn(() => 110),
}));

vi.mock('../hooks/useTerminalHeight.js', () => ({
  useTerminalHeight: vi.fn(() => 40),
}));

import { useRecentProjects } from '../hooks/useRecentProjects.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';
import { useTerminalHeight } from '../hooks/useTerminalHeight.js';

const mockedUseRecentProjects = vi.mocked(useRecentProjects);
const mockedUseTerminalWidth = vi.mocked(useTerminalWidth);
const mockedUseTerminalHeight = vi.mocked(useTerminalHeight);

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

const PROJECTS: Project[] = [
  {
    dir: '/tmp/rendering',
    folder: 'rendering',
    concept: 'Fourier transform intuition',
    status: 'running',
    updated_at: '2026-04-05T10:00:00Z',
    progress_done: 2,
    progress_total: 5,
    progress_desc: 'render stage',
  },
  {
    dir: '/tmp/completed',
    folder: 'completed',
    concept: 'Bayes theorem',
    status: 'completed',
    updated_at: '2026-04-04T10:00:00Z',
    progress_done: 5,
    progress_total: 5,
    progress_desc: 'done',
    has_video: true,
  },
];

describe('WelcomeScreen', () => {
  beforeEach(() => {
    mockedUseRecentProjects.mockReset();
    mockedUseTerminalWidth.mockReturnValue(110);
    mockedUseTerminalHeight.mockReturnValue(40);
  });

  afterEach(() => {
    cleanup();
  });

  it('renders the guided-first onboarding layout', async () => {
    mockedUseRecentProjects.mockReturnValue({ projects: PROJECTS, loading: false });

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
    expect(frame).toContain('Start New Video');
    expect(frame).toContain('Step 2 (Optional): Teaching Goal');
    expect(frame).toContain('Step 3: Quality');
    expect(frame).toContain('Recent Projects');
    expect(frame).toContain('Selected action');
    expect(frame).toContain('Shortcuts:');
    expect(frame).toContain('Press Enter to move to Step 2.');
  });

  it('uses compact-density layout on narrow/short terminals', async () => {
    mockedUseRecentProjects.mockReturnValue({ projects: PROJECTS, loading: false });
    mockedUseTerminalWidth.mockReturnValue(82);
    mockedUseTerminalHeight.mockReturnValue(24);

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
    expect(frame).toContain('Now: Topic');
    expect(frame).toContain('Press Enter to move to Step 2. Down/Tab also moves focus.');
  });
});
