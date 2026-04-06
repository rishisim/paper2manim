import { describe, expect, it } from 'vitest';
import { collapseRunLogsForRetry, getRunLogDedupeKey, sanitizeRunLogText } from './runLog.js';

describe('runLog helpers', () => {
  it('sanitizes control characters and collapses whitespace', () => {
    const raw = '\u0007 Segment   2 \u001b failed\t after  4.1s ';
    expect(sanitizeRunLogText(raw)).toBe('Segment 2 failed after 4.1s');
  });

  it('builds stable dedupe keys for stage headers and completed stages', () => {
    const stageHeader = getRunLogDedupeKey({ type: 'stage-header', text: 'pipeline' });
    const stageComplete = getRunLogDedupeKey({
      type: 'stage-complete',
      stage: { name: 'pipeline', status: 'ok', summary: 'Done', elapsed: 2.3 },
    });
    expect(stageHeader).toBe('stage-header:pipeline');
    expect(stageComplete).toBe('stage-complete:pipeline:ok:Done');
  });

  it('collapses only the active run logs when retrying', () => {
    expect(collapseRunLogsForRetry(12, 0)).toEqual({ collapsedCount: 12, nextActiveRunStart: 12 });
    expect(collapseRunLogsForRetry(18, 10)).toEqual({ collapsedCount: 8, nextActiveRunStart: 18 });
  });
});
