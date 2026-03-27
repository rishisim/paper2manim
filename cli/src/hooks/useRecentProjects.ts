import { useState, useEffect } from 'react';
import { spawnRunner } from '../lib/process.js';
import type { Project } from '../lib/types.js';

const MAX_RECENT = 5;

export function useRecentProjects(): { projects: Project[]; loading: boolean } {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const proc = spawnRunner(JSON.stringify({ mode: 'workspace', workspace_action: 'list' }));
    let buffer = '';

    proc.stdout?.on('data', (chunk: Buffer) => {
      buffer += chunk.toString();
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const msg = JSON.parse(line);
          if (msg.type === 'workspace_projects') {
            setProjects((msg.projects ?? []).slice(0, MAX_RECENT));
            setLoading(false);
          }
        } catch { /* ignore */ }
      }
    });

    proc.on('close', () => {
      if (buffer.trim()) {
        try {
          const msg = JSON.parse(buffer.trim());
          if (msg.type === 'workspace_projects') {
            setProjects((msg.projects ?? []).slice(0, MAX_RECENT));
          }
        } catch { /* ignore */ }
      }
      setLoading(false);
    });

    return () => {
      proc.kill();
    };
  }, []);

  return { projects, loading };
}
