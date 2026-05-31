import { describe, expect, it } from 'vitest';
import { buildTimelineRows } from './RunTimeline.js';
import type { RunEventRecord } from '../lib/types.js';

function ev(seq: number, message: string, extra: Partial<RunEventRecord> = {}): RunEventRecord {
  return {
    run_id: 'run-1',
    seq,
    ts: '2026-04-07T00:00:00.000Z',
    kind: 'status',
    message,
    ...extra,
  };
}

describe('buildTimelineRows', () => {
  it('keeps append order and emits compact badges for mixed event types', () => {
    const events: RunEventRecord[] = [
      ev(0, 'Entered pipeline', { kind: 'stage_transition', stage: 'pipeline', ts: '2026-04-07T00:00:00.000Z' }),
      ev(1, 'Reasoning', { kind: 'activity', stage: 'code', segment_id: 1, ts: '2026-04-07T00:00:01.000Z', worker_role: 'coder', source: 'provider_stream', reasoning: { kind: 'raw_reasoning', text: 'drafting' } }),
      ev(2, 'Segment 1 done', { kind: 'segment_terminal', stage: 'code', segment_id: 1, ts: '2026-04-07T00:00:02.000Z' }),
    ];

    const rows = buildTimelineRows(events, 'all');
    expect(rows.map(r => r.summary)).toEqual([
      'Entered pipeline',
      'Reasoning',
      'Segment 1 done',
    ]);
    expect(rows[1]?.badges).toEqual(['S1', 'coder', 'reason', 'model']);
  });

  it('filters down to reasoning events', () => {
    const events: RunEventRecord[] = [
      ev(0, 'Entered pipeline', { kind: 'stage_transition', stage: 'pipeline' }),
      ev(1, 'Tool call', { kind: 'activity', stage: 'code', tool: { name: 'search_docs' } }),
      ev(2, 'Reasoning', { kind: 'activity', stage: 'code', reasoning: { kind: 'inferred_reasoning', text: 'checking docs' } }),
    ];

    const rows = buildTimelineRows(events, 'reasoning');
    expect(rows).toHaveLength(1);
    expect(rows[0]?.badges).toContain('infer');
  });
});
