import { useState, useEffect, useRef } from 'react';
import type { SegmentState } from '../lib/types.js';

/**
 * Braille dot spinner patterns from cli-spinners.
 * Each state uses a different pattern to visually distinguish segment activity.
 */

// Coding/active — classic braille spinner (fast, 80ms)
const DOTS = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

// Rendering — full-block braille rotation (80ms)
const DOTS2 = ['⣾', '⣽', '⣻', '⢿', '⡿', '⣟', '⣯', '⣷'];

// Thinking/reasoning — slower pulse pattern (120ms effective via frame skip)
const DOTS12 = ['⢄', '⢂', '⢁', '⡁', '⡈', '⡐', '⡠'];

// Static states
const DONE_CHAR = '⣿';
const FAILED_CHARS = ['⠿', '⠀'];
const QUEUED_CHAR = '○';

export type SegmentSpinnerState = 'thinking' | 'coding' | 'rendering' | 'done' | 'failed' | 'queued';

/** Returns a frame counter that ticks at 80ms. */
export function useBrailleSpinner(): number {
  const [frame, setFrame] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    timerRef.current = setInterval(() => {
      setFrame(prev => prev + 1);
    }, 80);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  return frame;
}

/** Pure function: given the global frame counter and a segment state, return the spinner character. */
export function getSpinnerChar(frame: number, state: SegmentSpinnerState): string {
  switch (state) {
    case 'done':
      return DONE_CHAR;
    case 'queued':
      return QUEUED_CHAR;
    case 'failed':
      // Blink at ~500ms (every 6 frames at 80ms)
      return FAILED_CHARS[Math.floor(frame / 6) % FAILED_CHARS.length]!;
    case 'thinking':
      // Slower: advance every 2nd frame (~160ms per step)
      return DOTS12[Math.floor(frame / 2) % DOTS12.length]!;
    case 'rendering':
      return DOTS2[frame % DOTS2.length]!;
    case 'coding':
    default:
      return DOTS[frame % DOTS.length]!;
  }
}

/** Map a SegmentState to a spinner visual state. */
export function segmentToSpinnerState(seg: SegmentState): SegmentSpinnerState {
  if (seg.done) return 'done';
  if (seg.failed) return 'failed';
  if (!seg.updatedAt) return 'queued';
  if (seg.isThinking || seg.latestReasoningKind === 'raw_reasoning') return 'thinking';
  const phaseLower = (seg.phase ?? '').toLowerCase();
  if (phaseLower.includes('render') || phaseLower.includes('stitch') || phaseLower.includes('concat')) return 'rendering';
  return 'coding';
}
