import { describe, it, expect } from 'vitest';
import { collapseActivityLines, getActivityKindLabel, getStageProgressBarWidth, truncatePreserveTail, type ActivityLine } from './StatusBar.js';

describe('StatusBar helpers', () => {
  it('collapses consecutive matching activity rows and increments count', () => {
    const lines: ActivityLine[] = [
      { id: '1', kind: 'status', text: 'Rendering segment 1' },
      { id: '2', kind: 'status', text: 'Rendering segment 1' },
      { id: '3', kind: 'tool_call', text: 'Read file' },
      { id: '4', kind: 'status', text: 'Rendering segment 1' },
    ];
    const collapsed = collapseActivityLines(lines);
    expect(collapsed).toHaveLength(3);
    expect(collapsed[0]?.count).toBe(2);
    expect(collapsed[0]?.group).toBe('doing');
    expect(collapsed[1]?.count).toBe(1);
    expect(collapsed[2]?.count).toBe(1);
  });

  it('infers fixing/warning semantics for retry-like lines', () => {
    const lines: ActivityLine[] = [
      { id: '1', kind: 'status', text: 'Retrying failed segment 2' },
    ];
    const collapsed = collapseActivityLines(lines);
    expect(collapsed[0]?.group).toBe('fixing');
    expect(collapsed[0]?.severity).toBe('warning');
  });

  it('preserves output tail when truncating tool-like lines', () => {
    const source = '/Users/test/project/output/segments/segment_12_final.mp4';
    const out = truncatePreserveTail(source, 24, 2);
    expect(out).toContain('…');
    expect(out.endsWith('.mp4')).toBe(true);
  });

  it('handles undefined text safely when truncating', () => {
    expect(truncatePreserveTail(undefined, 24, 2)).toBe('');
  });

  it('uses compact and wide stage progress bar widths by terminal size', () => {
    expect(getStageProgressBarWidth(78)).toBe(10);
    expect(getStageProgressBarWidth(100)).toBe(14);
    expect(getStageProgressBarWidth(132)).toBe(20);
  });

  it('labels diff activity kind in compact and wide modes', () => {
    expect(getActivityKindLabel('diff', true)).toBe('Δ');
    expect(getActivityKindLabel('diff', false)).toBe('diff');
  });
});
