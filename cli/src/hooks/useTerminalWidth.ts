import { useState, useEffect } from 'react';

export function useTerminalWidth(): number {
  const [width, setWidth] = useState(process.stdout.columns ?? 80);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;

    const handler = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        // Clear the screen so Ink re-renders from the top instead of
        // appending below the previous (differently-sized) render.
        process.stdout.write('\x1b[2J\x1b[H');
        setWidth(process.stdout.columns ?? 80);
      }, 80);
    };

    process.stdout.on('resize', handler);
    return () => {
      process.stdout.off('resize', handler);
      if (timer) clearTimeout(timer);
    };
  }, []);

  return width;
}
