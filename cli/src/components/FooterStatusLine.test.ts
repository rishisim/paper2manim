import { describe, it, expect } from 'vitest';
import { getFooterProgressLabel, getFooterVisibility } from './FooterStatusLine.js';

describe('FooterStatusLine visibility', () => {
  it('80 cols: keeps only high-priority run signals', () => {
    const vis = getFooterVisibility(80, true, true, true, true);
    expect(vis.showElapsed).toBe(true);
    expect(vis.showSegments).toBe(true);
    expect(vis.showStagePct).toBe(false);
    expect(vis.showProgress).toBe(true);
    expect(vis.showTokens).toBe(false);
    expect(vis.showStage).toBe(false);
    expect(vis.showBranch).toBe(false);
    expect(vis.showVerbose).toBe(false);
  });

  it('100 cols: enables stage-local speed context but still hides branch/tokens', () => {
    const vis = getFooterVisibility(100, true, true, true, true);
    expect(vis.showElapsed).toBe(true);
    expect(vis.showSegments).toBe(true);
    expect(vis.showStagePct).toBe(true);
    expect(vis.showProgress).toBe(true);
    expect(vis.showTokens).toBe(false);
    expect(vis.showStage).toBe(true);
    expect(vis.showBranch).toBe(false);
    expect(vis.showVerbose).toBe(false);
  });

  it('120 cols: shows expanded context including tokens and branch', () => {
    const vis = getFooterVisibility(120, true, true, true, false);
    expect(vis.showElapsed).toBe(true);
    expect(vis.showSegments).toBe(true);
    expect(vis.showStagePct).toBe(true);
    expect(vis.showProgress).toBe(true);
    expect(vis.showTokens).toBe(false);
    expect(vis.showBranch).toBe(false);
  });

  it('140 cols: shows tokens and branch after progress-first fields', () => {
    const vis = getFooterVisibility(140, true, true, true, false);
    expect(vis.showProgress).toBe(true);
    expect(vis.showTokens).toBe(true);
    expect(vis.showBranch).toBe(true);
  });

  it('shows verbose badge only when verbose is enabled', () => {
    const on = getFooterVisibility(160, true, true, true, true);
    const off = getFooterVisibility(160, true, true, true, false);
    expect(on.showVerbose).toBe(true);
    expect(off.showVerbose).toBe(false);
  });

  it('does not show run-only fields when not running', () => {
    const vis = getFooterVisibility(140, false, true, true, true);
    expect(vis.showElapsed).toBe(false);
    expect(vis.showSegments).toBe(false);
    expect(vis.showStagePct).toBe(false);
    expect(vis.showHint).toBe(false);
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
