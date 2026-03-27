/**
 * React hook that reads the current git branch once on mount.
 */

import { useState, useEffect } from 'react';
import { execSync } from 'node:child_process';

export function useGitBranch(): string | null {
  const [branch, setBranch] = useState<string | null>(null);

  useEffect(() => {
    try {
      const result = execSync('git rev-parse --abbrev-ref HEAD', {
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
        timeout: 2000,
      }).trim();
      if (result && result !== 'HEAD') {
        setBranch(result);
      }
    } catch {
      // Not a git repo or git not available
    }
  }, []);

  return branch;
}
