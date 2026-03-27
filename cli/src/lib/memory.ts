/**
 * Memory loader — reads PAPER2MANIM.md files and injects into pipeline args.
 *
 * Reads from:
 *   1. ~/.paper2manim/PAPER2MANIM.md  (user-level)
 *   2. PAPER2MANIM.md  (project root / cwd)
 *
 * Combined content is prepended as system_prompt_prefix in pipeline args.
 */

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';

export function loadMemory(): string {
  const parts: string[] = [];

  // User-level memory
  const userMemPath = join(homedir(), '.paper2manim', 'PAPER2MANIM.md');
  if (existsSync(userMemPath)) {
    try {
      const content = readFileSync(userMemPath, 'utf8').trim();
      if (content) parts.push(`# User Instructions (from ~/.paper2manim/PAPER2MANIM.md)\n\n${content}`);
    } catch { /* ignore */ }
  }

  // Project-level memory (cwd)
  const projectMemPath = join(process.cwd(), 'PAPER2MANIM.md');
  if (existsSync(projectMemPath)) {
    try {
      const content = readFileSync(projectMemPath, 'utf8').trim();
      if (content) parts.push(`# Project Instructions (from PAPER2MANIM.md)\n\n${content}`);
    } catch { /* ignore */ }
  }

  return parts.join('\n\n---\n\n');
}

/** Check if any memory files exist. */
export function hasMemory(): boolean {
  return (
    existsSync(join(homedir(), '.paper2manim', 'PAPER2MANIM.md')) ||
    existsSync(join(process.cwd(), 'PAPER2MANIM.md'))
  );
}
