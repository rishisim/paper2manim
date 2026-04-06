import { describe, expect, it } from 'vitest';
import { AUTO_VERBOSE_WIDTH, resolveEffectiveVerbose } from './verbose.js';

describe('resolveEffectiveVerbose', () => {
  it('uses auto width threshold when no override is set', () => {
    expect(resolveEffectiveVerbose(AUTO_VERBOSE_WIDTH - 1, null)).toBe(false);
    expect(resolveEffectiveVerbose(AUTO_VERBOSE_WIDTH, null)).toBe(true);
  });

  it('manual override wins over auto behavior', () => {
    expect(resolveEffectiveVerbose(80, true)).toBe(true);
    expect(resolveEffectiveVerbose(200, false)).toBe(false);
  });
});

