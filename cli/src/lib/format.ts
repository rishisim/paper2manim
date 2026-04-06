/**
 * Shared formatting utilities — single source of truth for durations, tokens, etc.
 */

/** Format seconds into a clean human-readable duration. */
export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}m ${s.toString().padStart(2, '0')}s`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${h}h ${m}m ${s}s`;
}

/** Truncate a string from the right, keeping the beginning. */
export function truncateRight(s: string, maxLen: number): string {
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen - 1) + '\u2026';
}

/** Format a token count compactly: 0, 842, 1.2k, 45.3k, 1.2M */
export function formatTokenCount(count: number): string {
  if (count === 0) return '0';
  if (count < 1000) return String(count);
  if (count < 1_000_000) return `${(count / 1000).toFixed(1)}k`;
  return `${(count / 1_000_000).toFixed(1)}M`;
}

/** Fixed-width percentage string for progress bars (prevents digit-shift). */
export function padProgress(pct: number): string {
  return `${String(Math.round(pct)).padStart(3)}%`;
}

/**
 * Map raw Python tool names to human-readable Claude Code-style descriptions.
 * e.g. "fetch_manim_docs" → "Read Manim docs", "run_manim_code" → "Bash: manim render"
 */
/** Format an ISO timestamp as a relative human-readable string. */
export function formatRelativeDate(isoDate: string): string {
  const date = new Date(isoDate);
  if (isNaN(date.getTime())) return isoDate;

  const diffMs = Date.now() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);

  if (diffSecs < 60) return 'just now';
  const diffMins = Math.floor(diffSecs / 60);
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 30) return `${diffDays}d ago`;
  const diffMonths = Math.floor(diffDays / 30);
  if (diffMonths < 12) return `${diffMonths}mo ago`;
  return `${Math.floor(diffMonths / 12)}y ago`;
}

/** Render a text progress bar. Returns e.g. "████░░░░░░" */
export function renderProgressBar(pct: number, width = 10): string {
  const clamped = Math.max(0, Math.min(100, pct));
  const filled = Math.round((clamped / 100) * width);
  return '\u2588'.repeat(filled) + '\u2591'.repeat(width - filled);
}

/** Render an ASCII-safe determinate progress bar. */
export function renderProgressBarAscii(pct: number, width = 10): string {
  const clamped = Math.max(0, Math.min(100, pct));
  const filled = Math.round((clamped / 100) * width);
  return '='.repeat(filled) + '-'.repeat(Math.max(0, width - filled));
}

/** Render an ASCII-safe indeterminate progress bar with a moving window. */
export function renderIndeterminateProgressBar(frame: number, width = 10): string {
  const safeWidth = Math.max(6, width);
  const markerWidth = Math.max(3, Math.floor(safeWidth / 4));
  const travel = safeWidth - markerWidth;
  const offset = travel <= 0 ? 0 : Math.abs(frame % (travel * 2) - travel);
  let out = '';
  for (let i = 0; i < safeWidth; i += 1) {
    out += i >= offset && i < offset + markerWidth ? '=' : '-';
  }
  return out;
}

/** Format a USD cost value for compact display. */
export function formatCost(usd: number): string {
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  if (usd < 1) return `$${usd.toFixed(3)}`;
  return `$${usd.toFixed(2)}`;
}

const TOOL_DISPLAY_NAMES: Record<string, string> = {
  fetch_manim_docs:          'Read Manim docs',
  fetch_manim_file:          'Read Manim source',
  search_web:                'Search web',
  run_manim_code:            'Bash: manim render',
  dry_run_manim_code:        'Bash: manim dry-run',
  validate_manim_code:       'Validate code',
  fetch_golden_scenes:       'Read golden examples',
  fetch_golden_scenes_by_tags: 'Search golden examples',
  read_file:                 'Read',
  write_file:                'Write',
  edit_file:                 'Edit',
  bash:                      'Bash',
  // Planner sub-stages (emitted as synthetic tool_call events)
  analyze_concept:           'Analyze concept',
  build_prerequisite_tree:   'Build prerequisite tree',
  enrich_concept_tree:       'Enrich with equations',
  design_visuals:            'Design visual identity',
  compose_narrative:         'Compose narrative',
  // TTS / render / concat
  generate_voiceover:        'Generate voiceover',
  render_segment:            'Render segment',
  concat_segments:           'Concatenate segments',
  overlay_audio:             'Overlay audio',
  verify_segment:            'Verify segment code',
  verify_transitions:        'Verify transitions',
  adjust_tempo:              'Adjust video tempo',
  validate_timing:           'Validate A/V timing',
};

/** Format a tool call for display. Returns "Read Manim docs: Axes/methods" style string. */
export function formatToolCall(name: unknown, params?: Record<string, unknown>): string {
  const safeName = typeof name === 'string' && name.trim().length > 0 ? name : 'unknown_tool';
  const displayName = TOOL_DISPLAY_NAMES[safeName] ?? safeName;

  const safeParams = (params && typeof params === 'object') ? params : undefined;
  if (!safeParams || Object.keys(safeParams).length === 0) {
    return displayName;
  }

  // Build a compact param hint
  const values = Object.values(safeParams)
    .slice(0, 2)
    .map(v => {
      const s = String(v);
      return s.length > 40 ? s.slice(0, 39) + '…' : s;
    });

  // For "Read" / "Write" / "Edit" style tools, append the first value directly
  if (displayName === 'Read' || displayName === 'Write' || displayName === 'Edit') {
    return `${displayName} ${values[0] ?? ''}`;
  }

  // For "Bash" style, show the command
  if (displayName.startsWith('Bash')) {
    const cmd = safeParams.command ?? safeParams.cmd ?? values[0];
    return `Bash: ${String(cmd).slice(0, 60)}`;
  }

  return values.length > 0 ? `${displayName}: ${values.join(', ')}` : displayName;
}
