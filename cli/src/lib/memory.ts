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

/** H8: Maximum characters per memory file before truncation (~2000 tokens). */
const MAX_MEMORY_CHARS = 8000;

function readMemoryFile(path: string, label: string): string | null {
  try {
    let content = readFileSync(path, 'utf8').trim();
    if (!content) return null;
    // H8: Truncate files that are too large to avoid overrunning the token budget
    if (content.length > MAX_MEMORY_CHARS) {
      content = content.slice(0, MAX_MEMORY_CHARS) + `\n\n[...truncated — file exceeds ${MAX_MEMORY_CHARS} chars]`;
    }
    return `# ${label}\n\n${content}`;
  } catch {
    // Ignore unreadable files (permissions, encoding issues, etc.)
    return null;
  }
}

export function loadMemory(): string {
  const parts: string[] = [];

  const userPart = readMemoryFile(
    join(homedir(), '.paper2manim', 'PAPER2MANIM.md'),
    'User Instructions (from ~/.paper2manim/PAPER2MANIM.md)',
  );
  if (userPart) parts.push(userPart);

  const projectPart = readMemoryFile(
    join(process.cwd(), 'PAPER2MANIM.md'),
    'Project Instructions (from PAPER2MANIM.md)',
  );
  if (projectPart) parts.push(projectPart);

  return parts.join('\n\n---\n\n');
}

/** Check if any memory files exist. */
export function hasMemory(): boolean {
  return (
    existsSync(join(homedir(), '.paper2manim', 'PAPER2MANIM.md')) ||
    existsSync(join(process.cwd(), 'PAPER2MANIM.md'))
  );
}
