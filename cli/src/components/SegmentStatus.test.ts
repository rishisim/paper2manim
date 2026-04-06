import { describe, it, expect } from 'vitest';
import { getSegmentLineViewModel, formatSegmentViewModelForWidth } from './SegmentStatus.js';
import type { SegmentState } from '../lib/types.js';

function baseSegment(overrides: Partial<SegmentState> = {}): SegmentState {
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

describe('SegmentStatus view model', () => {
  it('maps running segment to running state', () => {
    const vm = getSegmentLineViewModel(baseSegment());
    expect(vm.state).toBe('running');
    expect(vm.detail).toContain('Generating');
  });

  it('maps retried segment to retry state with attempt context', () => {
    const vm = getSegmentLineViewModel(baseSegment({ attempt: 2 }));
    expect(vm.state).toBe('retry');
    expect(vm.detail).toContain('attempt 2/3');
  });

  it('maps failed segment with actionable hint', () => {
    const vm = getSegmentLineViewModel(baseSegment({
      failed: true,
      phase: 'failed',
      failHint: 'Check missing asset path',
    }));
    expect(vm.state).toBe('failed');
    expect(vm.hint).toBe('Check missing asset path');
  });

  it('maps completed segment to done state', () => {
    const vm = getSegmentLineViewModel(baseSegment({
      done: true,
      phase: 'done',
    }));
    expect(vm.state).toBe('done');
    expect(vm.detail).toBe('done');
  });

  it('preserves status hints through width formatting', () => {
    const vm = formatSegmentViewModelForWidth(getSegmentLineViewModel(baseSegment({
      failed: true,
      phase: 'failed',
      failHint: 'Missing audio asset: output/segment_5/audio.wav. Regenerate TTS before stitch.',
    })), 80);
    expect(vm.hint).toContain('Missing audio asset');
    expect(vm.hint?.endsWith('…')).toBe(true);
  });
});
