import type { CompletedStage } from './types.js';

export interface RunLogLike {
  type: 'header' | 'stage-header' | 'stage-complete' | 'log' | 'segment';
  dedupeKey?: string;
  stage?: CompletedStage;
  text?: string;
  icon?: string;
}

const CONTROL_CHARS = /[\u0000-\u001f\u007f-\u009f]/g;

export function sanitizeRunLogText(raw: string): string {
  return raw.replace(CONTROL_CHARS, '').replace(/\s+/g, ' ').trim();
}

export function getRunLogDedupeKey(entry: RunLogLike): string {
  if (entry.dedupeKey) return entry.dedupeKey;
  if (entry.type === 'stage-complete' && entry.stage) {
    return `stage-complete:${entry.stage.name}:${entry.stage.status}:${entry.stage.summary}`;
  }
  if (entry.type === 'stage-header') {
    return `stage-header:${entry.text ?? ''}`;
  }
  if (entry.type === 'segment') {
    return `segment:${entry.icon ?? 'line'}:${entry.text ?? ''}`;
  }
  return `${entry.type}:${entry.text ?? ''}`;
}

export function collapseRunLogsForRetry(totalLogs: number, activeRunStart: number): {
  collapsedCount: number;
  nextActiveRunStart: number;
} {
  const collapsedCount = Math.max(0, totalLogs - activeRunStart);
  return {
    collapsedCount,
    nextActiveRunStart: totalLogs,
  };
}
