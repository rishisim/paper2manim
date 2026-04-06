import { describe, it, expect } from 'vitest';
import { simulateRunUi } from './runUiSimulator.js';
import type { ActivityLine } from '../components/StatusBar.js';
import type { SegmentState } from './types.js';

function seg(overrides: Partial<SegmentState>): SegmentState {
  return {
    id: 1,
    phase: 'running',
    prettyPhase: 'Generating initial script',
    attempt: 1,
    done: false,
    failed: false,
    ...overrides,
  };
}

describe('runUiSimulator scenarios', () => {
  it('smooth run keeps compact width focused (80 cols)', () => {
    const activity: ActivityLine[] = [
      { id: '1', kind: 'status', text: 'Planning storyboard' },
      { id: '2', kind: 'status', text: 'Planning storyboard' },
      { id: '3', kind: 'tool_call', text: 'read_file PAPER2MANIM.md' },
      { id: '4', kind: 'status', text: 'Rendering segments in parallel' },
    ];
    const state = simulateRunUi({
      width: 80,
      activity,
      segments: [seg({ id: 1 }), seg({ id: 2, done: true, phase: 'done' })],
      verbose: true,
      progressPct: 40,
      progressMode: 'determinate',
    });
    expect(state.activityMaxLines).toBe(5);
    expect(state.rows.some(r => r.count > 1)).toBe(true);
    expect(state.rows.every(r => r.kindLabel.length <= 1)).toBe(true);
    expect(state.footer.showSegments).toBe(true);
    expect(state.footer.showTokens).toBe(false);
    expect(state.footer.showBranch).toBe(false);
    expect(state.progressBar).toHaveLength(10);
    expect(state.progressPct).toBe(40);
  });

  it('retry-heavy run keeps more activity context at 100 cols', () => {
    const activity: ActivityLine[] = [
      { id: '1', kind: 'status', text: 'Segment 3 execution failed, self-correcting' },
      { id: '2', kind: 'status', text: 'Segment 3 execution failed, self-correcting' },
      { id: '3', kind: 'tool_call', text: 'web_search manim docs' },
      { id: '4', kind: 'tool_result', text: 'web_search: https://docs.manim.community/en/stable/reference' },
      { id: '5', kind: 'status', text: 'Applying fix for Segment 3' },
    ];
    const state = simulateRunUi({
      width: 100,
      activity,
      segments: [seg({ id: 3, attempt: 2, prettyPhase: 'Applying fix' })],
      progressPct: 65,
      progressMode: 'determinate',
    });
    expect(state.activityMaxLines).toBe(5);
    expect(state.rows[0]?.count).toBeGreaterThanOrEqual(2);
    expect(state.rows.some(r => r.kindLabel === 'tool')).toBe(true);
    expect(state.footer.showStagePct).toBe(true);
    expect(state.footer.showProgress).toBe(true);
    expect(state.progressBar).toHaveLength(14);
  });

  it('failure-heavy run preserves actionable failure hint at 120 cols', () => {
    const activity: ActivityLine[] = [
      { id: '1', kind: 'status', text: 'Segment 4 failed during render' },
      { id: '2', kind: 'status', text: 'Segment 5 failed during render' },
      { id: '3', kind: 'tool_result', text: 'stderr: FileNotFoundError: output/segment_5/audio.wav missing' },
    ];
    const state = simulateRunUi({
      width: 120,
      activity,
      segments: [
        seg({
          id: 5,
          failed: true,
          phase: 'failed',
          attempt: 3,
          failHint: 'Missing audio asset: output/segment_5/audio.wav. Regenerate TTS before stitch.',
        }),
      ],
      progressPct: 85,
      progressMode: 'determinate',
    });
    expect(state.activityMaxLines).toBe(6);
    expect(state.footer.showTokens).toBe(false);
    expect(state.footer.showBranch).toBe(false);
    expect(state.segments[0]?.hint).toContain('Missing audio asset');
    expect(state.progressBar).toHaveLength(20);
  });

  it('verbose mode expands activity history on wider terminals', () => {
    const state = simulateRunUi({
      width: 120,
      verbose: true,
      activity: Array.from({ length: 10 }, (_, i) => ({
        id: String(i),
        kind: 'status',
        text: `status ${i}`,
      })),
      segments: [],
      progressMode: 'determinate',
      progressPct: 42,
    });
    expect(state.activityMaxLines).toBe(8);
    expect(state.rows).toHaveLength(8);
    expect(state.rows[0]?.text).toContain('status 2');
  });

  it('shows indeterminate progress before totals are known', () => {
    const state = simulateRunUi({
      width: 90,
      activity: [{ id: '1', kind: 'status', text: 'Planning storyboard' }],
      segments: [],
      progressMode: 'indeterminate',
      progressPct: 5,
    });
    expect(state.progressMode).toBe('indeterminate');
    expect(state.footer.showProgress).toBe(true);
    expect(state.progressBar).toContain('=');
    expect(state.progressBar).toContain('-');
  });

  it('renders diff activity rows in the live lane', () => {
    const state = simulateRunUi({
      width: 120,
      activity: [
        {
          id: 'd1',
          kind: 'diff',
          text: 'Seg 2 code changes (+5 -2)',
          detail: '@@ -1,2 +1,3 @@\n-old\n+new',
        },
      ],
      segments: [],
      progressMode: 'determinate',
      progressPct: 42,
    });
    expect(state.rows[0]?.kind).toBe('diff');
    expect(state.rows[0]?.kindLabel).toBe('diff');
  });
});
