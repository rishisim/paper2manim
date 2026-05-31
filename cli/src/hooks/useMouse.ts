/**
 * useMouse — Terminal mouse click support for Ink apps.
 *
 * Enables SGR mouse reporting on mount, parses click events from stdin,
 * and returns the last click position. Cleans up on unmount.
 *
 * Works in: iTerm2, Terminal.app, Windows Terminal, most xterm-compatible terminals.
 */

import { useState, useEffect, useRef } from 'react';

export interface MouseEvent {
  x: number;       // 1-indexed column
  y: number;       // 1-indexed row
  button: number;  // 0=left, 1=middle, 2=right
  type: 'press' | 'release';
}

interface UseMouseResult {
  lastClick: MouseEvent | null;
  /** Call to consume the click (prevents re-processing) */
  consumeClick: () => void;
}

// SGR mouse event regex: \x1b[<button;x;yM (press) or \x1b[<button;x;ym (release)
const SGR_MOUSE_RE = /\x1b\[<(\d+);(\d+);(\d+)([Mm])/g;

export function useMouse(): UseMouseResult {
  const [lastClick, setLastClick] = useState<MouseEvent | null>(null);
  const enabled = useRef(false);

  useEffect(() => {
    // Only enable mouse in interactive TTY sessions
    const isTTY = process.stdin.isTTY && process.stdout.isTTY;
    if (!isTTY) return;

    // Enable SGR mouse mode (extended coordinates, works beyond 223 columns)
    if (!enabled.current) {
      process.stdout.write('\x1b[?1000h'); // enable basic mouse tracking
      process.stdout.write('\x1b[?1006h'); // enable SGR extended mode
      enabled.current = true;
    }

    const handleData = (data: Buffer) => {
      const str = data.toString('utf-8');

      // Parse SGR mouse events
      let match: RegExpExecArray | null;
      SGR_MOUSE_RE.lastIndex = 0;
      while ((match = SGR_MOUSE_RE.exec(str)) !== null) {
        const buttonCode = parseInt(match[1]!, 10);
        const x = parseInt(match[2]!, 10);
        const y = parseInt(match[3]!, 10);
        const type = match[4] === 'M' ? 'press' : 'release';

        // Only fire on press, not release or drag
        if (type !== 'press') continue;

        // Button: lower 2 bits = button number (0=left, 1=middle, 2=right)
        // Bit 5 (32) = motion while pressed (drag) — skip these
        if (buttonCode & 32) continue;

        const button = buttonCode & 3;

        // Only handle left click
        if (button === 0) {
          setLastClick({ x, y, button, type });
        }
      }
    };

    process.stdin.on('data', handleData);

    return () => {
      process.stdin.removeListener('data', handleData);
      // Disable mouse tracking on cleanup
      if (enabled.current) {
        try {
          process.stdout.write('\x1b[?1000l');
          process.stdout.write('\x1b[?1006l');
        } catch { /* ignore if stdout is closed */ }
        enabled.current = false;
      }
    };
  }, []);

  const consumeClick = () => setLastClick(null);

  return { lastClick, consumeClick };
}
