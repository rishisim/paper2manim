import { describe, it, expect } from 'vitest';
import { getFooterProgressLabel, getFooterVisibility } from './FooterStatusLine.js';

describe('FooterStatusLine visibility', () => {
  it('80 cols running: shows elapsed, segments, progress, hint', () => {
    const vis = getFooterVisibility(80, true, true);
    expect(vis.showElapsed).toBe(true);
    expect(vis.showSegments).toBe(true);
    expect(vis.showProgress).toBe(true);
    expect(vis.showTokens).toBe(false);
    expect(vis.showHint).toBe(true);
  });

  it('160+ cols: shows tokens', () => {
    const vis = getFooterVisibility(160, true, true);
    expect(vis.showTokens).toBe(true);
  });

  it('does not show run-only fields when not running', () => {
    const vis = getFooterVisibility(140, false, true);
    expect(vis.showElapsed).toBe(false);
    expect(vis.showSegments).toBe(false);
    expect(vis.showProgress).toBe(false);
    expect(vis.showHint).toBe(false);
  });

  it('narrow terminal hides elapsed and segments', () => {
    const vis = getFooterVisibility(55, true, true);
    expect(vis.showElapsed).toBe(false);
    expect(vis.showSegments).toBe(false);
  });
});

describe('FooterStatusLine progress labels', () => {
  it('shows determinate progress at 0, mid, and 100', () => {
    expect(getFooterProgressLabel(0, 'determinate')).toBe('0%');
    expect(getFooterProgressLabel(47.2, 'determinate')).toBe('47%');
    expect(getFooterProgressLabel(100, 'determinate')).toBe('100%');
  });

  it('shows estimating label for indeterminate mode', () => {
    expect(getFooterProgressLabel(33, 'indeterminate')).toBe('estimating...');
  });
});
