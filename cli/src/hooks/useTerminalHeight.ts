import { useState, useEffect } from 'react';

export function useTerminalHeight(): number {
  const [height, setHeight] = useState(process.stdout.rows ?? 24);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;

    const handler = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        setHeight(process.stdout.rows ?? 24);
      }, 80);
    };

    process.stdout.on('resize', handler);
    return () => {
      process.stdout.off('resize', handler);
      if (timer) clearTimeout(timer);
    };
  }, []);

  return height;
}
