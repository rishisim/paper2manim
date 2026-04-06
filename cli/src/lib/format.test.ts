import { describe, it, expect } from 'vitest';
import { formatToolCall, renderIndeterminateProgressBar, renderProgressBarAscii } from './format.js';

describe('formatToolCall', () => {
  it('falls back safely when tool name is missing', () => {
    const out = formatToolCall(undefined, { q: 'manim axes' });
    expect(out).toContain('unknown_tool');
  });
});

describe('progress bar helpers', () => {
  it('renders ASCII determinate bars safely', () => {
    expect(renderProgressBarAscii(50, 10)).toBe('=====-----');
    expect(renderProgressBarAscii(0, 8)).toBe('--------');
    expect(renderProgressBarAscii(100, 6)).toBe('======');
  });

  it('renders indeterminate bar with moving marker', () => {
    const a = renderIndeterminateProgressBar(1, 12);
    const b = renderIndeterminateProgressBar(5, 12);
    expect(a).toHaveLength(12);
    expect(b).toHaveLength(12);
    expect(a).not.toBe(b);
    expect(a).toContain('=');
    expect(a).toContain('-');
  });
});
