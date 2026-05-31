import React from 'react';
import { render } from 'ink-testing-library';
import { describe, expect, it } from 'vitest';
import { RunHarness } from './RunHarness.js';
import { AppContextProvider } from '../context/AppContext.js';
import type { BoardRowModel, InspectRow, Settings, Session } from '../lib/types.js';

const settings = {
  model: 'openai-default',
  theme: 'dark',
  defaultMode: 'default',
  outputStyle: 'verbose',
  editorMode: 'normal',
  quality: 'high',
  hooks: {},
  permissions: {},
  statusLine: null,
  disableAllHooks: false,
  promptColor: '#64B4FF',
} satisfies Settings;

const session = {
  id: 's1',
  name: null,
  startedAt: '2026-04-09T00:00:00Z',
  concept: 'demo',
  stage: 'code',
  checkpoints: [],
  tokenUsage: { input: 0, output: 0, cacheRead: 0 },
  permissionMode: 'default',
} satisfies Session;

function renderHarness(boardRows: BoardRowModel[]) {
  const inspectRows: InspectRow[] = [];
  return render(
    <AppContextProvider settings={settings} session={session} gitBranch={null}>
      <RunHarness
        concept="demo"
        quality="high"
        stage="code"
        elapsed={12}
        runState="active"
        segments={new Map()}
        segmentCodes={new Map()}
        totalSegments={boardRows.length}
        progressPct={50}
        progressMode="determinate"
        globalEvents={[]}
        viewMode="board"
        boardRows={boardRows}
        boardSelectedSegmentId={1}
        boardScrollOffset={0}
        boardWindowRows={4}
        boardExpandedSegmentId={1}
        boardFollowMode={false}
        inspectRows={inspectRows}
        inspectSelectedId={undefined}
        inspectScrollOffset={0}
        inspectWindowLines={6}
        inspectExpandedItems={new Set()}
        inspectFilter="all"
        inspectFollowMode={true}
      />
    </AppContextProvider>,
  );
}

describe('RunHarness board view', () => {
  it('renders compact board rows with matrix and selected drawer', () => {
    const boardRows: BoardRowModel[] = [
      {
        segmentId: 1,
        title: 'Intro',
        state: 'live',
        statusPipState: 'live',
        currentAction: 'Coder: drafting opening',
        primarySummary: 'S1 Intro · Coder: drafting opening',
        secondarySummary: 'reasoning Planning the opening beat · search_docs(query=manim axes)',
        reasoningLabel: 'Reasoning',
        reasoningPreview: 'Planning the opening beat',
        toolPreview: 'search_docs(query=manim axes)',
        codePreview: ['class Segment1Scene(Scene):', '    pass'],
        selectedReasoningPreview: 'Planning the opening beat',
        selectedCodePreview: ['class Segment1Scene(Scene):', '    pass'],
        selectedToolPreview: 'search_docs(query=manim axes)',
        activityDots: ['reasoning', 'tool', 'code'],
        updatedAgo: '3s',
        lastUpdatedAt: Date.now(),
        isExpandable: true,
      },
      {
        segmentId: 2,
        title: 'Wrap',
        state: 'queued',
        statusPipState: 'queued',
        currentAction: 'Queued',
        primarySummary: 'S2 Wrap · Queued',
        activityDots: [],
        updatedAgo: undefined,
        lastUpdatedAt: undefined,
        isExpandable: false,
      },
    ];

    const { lastFrame } = renderHarness(boardRows);
    const frame = lastFrame();
    expect(frame).toContain('board');
    expect(frame).toContain('S1 Intro');
    expect(frame).toContain('Reasoning  Planning the opening beat');
    expect(frame).toContain('class Segment1Scene(Scene):');
  });
});
