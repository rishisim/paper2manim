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
export function formatToolCall(name: string, params?: Record<string, unknown>): string {
  const displayName = TOOL_DISPLAY_NAMES[name] ?? name;

  if (!params || Object.keys(params).length === 0) {
    return displayName;
  }

  // Build a compact param hint
  const values = Object.values(params)
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
    const cmd = params.command ?? params.cmd ?? values[0];
    return `Bash: ${String(cmd).slice(0, 60)}`;
  }

  return values.length > 0 ? `${displayName}: ${values.join(', ')}` : displayName;
}
