import { describe, expect, it } from 'vitest';
import { buildCompactUnifiedDiff } from './codeDiff.js';

describe('buildCompactUnifiedDiff', () => {
  it('shows additions for initial snapshot', () => {
    const diff = buildCompactUnifiedDiff('', 'line1\nline2');
    expect(diff.hasChanges).toBe(true);
    expect(diff.added).toBe(2);
    expect(diff.removed).toBe(0);
    expect(diff.lines.some(l => l.startsWith('+line1'))).toBe(true);
  });

  it('shows mixed additions and removals', () => {
    const prev = 'a\nb\nc\n';
    const next = 'a\nbx\nc\nz\n';
    const diff = buildCompactUnifiedDiff(prev, next);
    expect(diff.hasChanges).toBe(true);
    expect(diff.added).toBeGreaterThan(0);
    expect(diff.removed).toBeGreaterThan(0);
    expect(diff.summary).toContain('+');
    expect(diff.summary).toContain('-');
  });

  it('truncates with compact line budget', () => {
    const prev = Array.from({ length: 20 }, (_, i) => `x${i}`).join('\n');
    const next = Array.from({ length: 20 }, (_, i) => `y${i}`).join('\n');
    const diff = buildCompactUnifiedDiff(prev, next, { maxVisibleLines: 6 });
    expect(diff.truncated).toBe(true);
    expect(diff.lines[diff.lines.length - 1]).toContain('more diff lines');
  });

  it('suppresses whitespace-only changes', () => {
    const prev = 'a  \n b\n';
    const next = 'a\n b  \n';
    const diff = buildCompactUnifiedDiff(prev, next);
    expect(diff.hasChanges).toBe(false);
  });
});

