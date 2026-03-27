/**
 * Hook that tracks elapsed time since a given start point.
 */

import { useState, useEffect, useRef } from 'react';

export function useElapsed(running: boolean): number {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef<number>(Date.now());

  useEffect(() => {
    if (!running) return;

    startRef.current = Date.now();
    setElapsed(0);

    const interval = setInterval(() => {
      setElapsed((Date.now() - startRef.current) / 1000);
    }, 100);

    return () => clearInterval(interval);
  }, [running]);

  return elapsed;
}
