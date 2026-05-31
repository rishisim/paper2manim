import { describe, expect, it } from 'vitest';
import { appendTrace, extractStoryboardTitles, reduceSegmentUpdate } from './segmentBoard.js';

describe('segmentBoard helpers', () => {
  it('reduces per-segment updates into stable worker-owned state', () => {
    const first = reduceSegmentUpdate(undefined, {
      stage: 'code',
      phase: 'generate',
      prettyPhase: 'Doing: generating initial script',
      status: 'generating initial script',
      now: 1000,
      thinking: 'Drafting the opening animation',
    });

    expect(first.currentWorker).toBe('coder');
    expect(first.currentTask).toContain('Coder');
    expect(first.latestInference).toContain('Drafting');
    expect(first.latestReasoningKind).toBe('inferred_reasoning');
    expect(first.trace?.some(entry => entry.category === 'inference')).toBe(true);
  });

  it('keeps a segment in place when it moves from done to a later active stage', () => {
    const coded = reduceSegmentUpdate(undefined, {
      stage: 'code',
      phase: 'done',
      prettyPhase: 'Complete',
      status: 'code complete',
      now: 1000,
    });
    const rendered = reduceSegmentUpdate(coded, {
      stage: 'render',
      phase: 'running',
      prettyPhase: 'Render Doing: running',
      status: 'running hd render',
      now: 2000,
    });

    expect(coded.done).toBe(true);
    expect(rendered.done).toBe(false);
    expect(rendered.currentWorker).toBe('renderer');
    expect(rendered.completedBadges).toContain('Draft code ready');
  });

  it('rolls trace entries forward without unbounded growth', () => {
    let state = reduceSegmentUpdate(undefined, {
      stage: 'code',
      phase: 'generate',
      prettyPhase: 'Doing',
      status: 'start',
      now: 1000,
    });

    for (let index = 0; index < 10; index += 1) {
      state = {
        ...state,
        trace: appendTrace(state.trace, {
          id: `code:${index}`,
          category: 'code',
          text: `diff ${index}`,
          ts: 1000 + index,
          workerRole: 'coder',
        }),
      };
    }

    expect(state.trace?.length).toBeLessThanOrEqual(64);
    expect(state.trace?.[state.trace.length - 1]?.text).toBe('diff 9');
  });

  it('stores live code snapshots from streaming code events', () => {
    const state = reduceSegmentUpdate(undefined, {
      stage: 'code',
      phase: 'generate',
      prettyPhase: 'Doing',
      status: 'streaming code draft',
      now: 1000,
      streamEvent: {
        channel: 'code',
        delta: 'from manim import *\n',
        snapshot: 'from manim import *\nclass Segment1Scene(Scene):\n    pass\n',
      },
    });

    expect(state.liveCode).toContain('class Segment1Scene');
    expect(state.trace?.some(entry => entry.category === 'code')).toBe(true);
  });

  it('marks streamed thinking snapshots as raw reasoning', () => {
    const state = reduceSegmentUpdate(undefined, {
      stage: 'code',
      phase: 'fix_docs',
      prettyPhase: 'Fixing',
      status: 'reasoning through fix',
      now: 1000,
      thinking: 'Inspecting the failure',
      streamEvent: {
        channel: 'thinking',
        delta: 'Inspecting',
        snapshot: 'Inspecting the failure',
      },
    });

    expect(state.latestReasoningKind).toBe('raw_reasoning');
    expect(state.liveThinking).toContain('Inspecting');
  });

  it('extracts storyboard titles by segment id', () => {
    const titles = extractStoryboardTitles({
      segments: [
        { id: 1, title: 'Open-loop instability' },
        { id: 2, title: 'The feedback loop' },
      ],
    });

    expect(titles.get(1)).toBe('Open-loop instability');
    expect(titles.get(2)).toBe('The feedback loop');
  });
});
