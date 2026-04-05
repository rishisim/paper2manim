import { useState, useEffect } from 'react';

export function useTerminalWidth(): number {
  const [width, setWidth] = useState(process.stdout.columns ?? 80);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;

    const handler = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
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
