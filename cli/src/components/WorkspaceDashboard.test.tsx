import React from 'react';
import { EventEmitter } from 'node:events';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render } from 'ink-testing-library';
import { WorkspaceDashboard } from './WorkspaceDashboard.js';
import { AppContextProvider } from '../context/AppContext.js';
import { DEFAULT_SETTINGS, type Session } from '../lib/types.js';

vi.mock('../lib/process.js', () => ({
  spawnRunner: vi.fn(),
}));

import { spawnRunner } from '../lib/process.js';

const mockedSpawnRunner = vi.mocked(spawnRunner);

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

function makeProc(payload: unknown): EventEmitter & { stdout: EventEmitter; kill: () => void; killed?: boolean } {
  const proc = new EventEmitter() as EventEmitter & { stdout: EventEmitter; kill: () => void; killed?: boolean };
  proc.stdout = new EventEmitter();
  proc.kill = () => { proc.killed = true; };
  setTimeout(() => {
    proc.stdout.emit('data', Buffer.from(`${JSON.stringify(payload)}\n`));
    proc.emit('close');
  }, 0);
  return proc;
}

describe('WorkspaceDashboard', () => {
  beforeEach(() => {
    mockedSpawnRunner.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it('runs the suggested primary action on Enter from list view', async () => {
    const projects = [{
      dir: '/tmp/needs-rerun',
      folder: 'needs-rerun',
      concept: 'Divergence theorem',
      status: 'failed',
      updated_at: '2026-04-05T10:00:00Z',
      progress_done: 1,
      progress_total: 4,
      progress_desc: 'render failed',
      has_video: false,
    }];

    mockedSpawnRunner.mockImplementation(() =>
      makeProc({ type: 'workspace_projects', projects, placeholder_count: 0 }) as unknown as ReturnType<typeof spawnRunner>,
    );

    const instance = render(
      <AppContextProvider settings={DEFAULT_SETTINGS} session={baseSession()} gitBranch={null}>
        <WorkspaceDashboard onResume={vi.fn()} onRerun={vi.fn()} onBack={vi.fn()} />
      </AppContextProvider>,
    );

    await new Promise(resolve => setTimeout(resolve, 20));
    const frame = instance.lastFrame() ?? '';
    expect(frame).toContain('[Needs attention]');
    expect(frame).toContain('Re-run');
    expect(frame).toContain('run suggested action');
  });
});
