import React from 'react';
import { EventEmitter } from 'node:events';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render } from 'ink-testing-library';
import { Text } from 'ink';
import { AppContextProvider } from '../context/AppContext.js';
import { DEFAULT_SETTINGS, type AppDispatch, type Project, type Session } from '../lib/types.js';

const promptBarState = vi.hoisted(() => ({
  latest: null as null | Record<string, unknown>,
}));

vi.mock('../hooks/useRecentProjects.js', () => ({
  useRecentProjects: vi.fn(),
}));

vi.mock('../hooks/useTerminalWidth.js', () => ({
  useTerminalWidth: vi.fn(() => 110),
}));

vi.mock('../hooks/useTerminalHeight.js', () => ({
  useTerminalHeight: vi.fn(() => 40),
}));

vi.mock('./PromptBar.js', () => ({
  PromptBar: (props: Record<string, unknown>) => {
    promptBarState.latest = props;
    return React.createElement(Text, null, '[PromptBar]');
  },
}));

import { useRecentProjects } from '../hooks/useRecentProjects.js';
import { WelcomeScreen } from './WelcomeScreen.js';

const mockedUseRecentProjects = vi.mocked(useRecentProjects);

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
];

async function flush(ms = 10): Promise<void> {
  await new Promise(resolve => setTimeout(resolve, ms));
}

describe('WelcomeScreen onboarding navigation', () => {
  beforeEach(() => {
    mockedUseRecentProjects.mockReset();
    promptBarState.latest = null;
  });

  afterEach(() => {
    cleanup();
  });

  it('keeps generation gated until reaching Step 3', async () => {
    mockedUseRecentProjects.mockReturnValue({ projects: [], loading: false });
    const onSubmit = vi.fn();

    const instance = render(
      <AppContextProvider settings={DEFAULT_SETTINGS} session={baseSession()} gitBranch={null}>
        <WelcomeScreen onSubmit={onSubmit} onResumeProject={vi.fn()} dispatch={mockDispatch()} />
      </AppContextProvider>,
    );
    await flush();

    const prompt = promptBarState.latest as { onSubmit: (value: string) => void };
    prompt.onSubmit('Chain rule intuition');
    await flush();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(instance.lastFrame() ?? '').toContain('Press Enter to move to Step 3. Down/Tab also moves focus.');

    expect(instance.lastFrame() ?? '').toContain('Press Enter to move to Step 3. Down/Tab also moves focus.');

    expect(onSubmit).not.toHaveBeenCalled();
  });


  it('does not jump to projects when pressing Up from the topic input', async () => {
    mockedUseRecentProjects.mockReturnValue({ projects: PROJECTS, loading: false });
    const onResumeProject = vi.fn();

    const instance = render(
      <AppContextProvider settings={DEFAULT_SETTINGS} session={baseSession()} gitBranch={null}>
        <WelcomeScreen onSubmit={vi.fn()} onResumeProject={onResumeProject} dispatch={mockDispatch()} />
      </AppContextProvider>,
    );
    await flush();

    instance.stdin.write('\u001B[A');
    await flush();

    expect(instance.lastFrame() ?? '').toContain('Press Enter to continue to Step 2.');
    expect(onResumeProject).not.toHaveBeenCalled();
  });

  it('reaches projects from Step 3 using Down', async () => {
    mockedUseRecentProjects.mockReturnValue({ projects: PROJECTS, loading: false });

    const instance = render(
      <AppContextProvider settings={DEFAULT_SETTINGS} session={baseSession()} gitBranch={null}>
        <WelcomeScreen onSubmit={vi.fn()} onResumeProject={vi.fn()} dispatch={mockDispatch()} />
      </AppContextProvider>,
    );
    await flush();

    instance.stdin.write('\u001B[B'); // concept -> goal
    instance.stdin.write('\u001B[B'); // goal -> quality
    await flush();
    instance.stdin.write('\u001B[B'); // quality -> projects
    await flush();

    expect(instance.lastFrame() ?? '').toContain('Press Enter to resume');
  });

});
