import { useState, useEffect, useRef } from 'react';

/**
 * Claude Code's custom spinner characters.
 * Cycles through Unicode symbols with easing — first and last chars hold longer.
 */
const SPINNER_CHARS = ['·', '✢', '✳', '∗', '✻', '✽'];

// Easing: first and last hold 1.5x longer than middle chars
const BASE_MS = 100;
const HOLD_MS = 150;
const FRAME_DURATIONS = SPINNER_CHARS.map((_, i) =>
  i === 0 || i === SPINNER_CHARS.length - 1 ? HOLD_MS : BASE_MS,
);

/** Returns a cycling spinner character using Claude Code's Unicode set with easing. */
export function useClaudeSpinner(): string {
  const [frame, setFrame] = useState(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const advance = () => {
      setFrame(prev => {
        const next = (prev + 1) % SPINNER_CHARS.length;
        timerRef.current = setTimeout(advance, FRAME_DURATIONS[next]!);
        return next;
      });
    };

    timerRef.current = setTimeout(advance, FRAME_DURATIONS[0]!);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  return SPINNER_CHARS[frame % SPINNER_CHARS.length]!;
}
