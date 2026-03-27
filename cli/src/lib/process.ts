/**
 * Utilities for locating Python and spawning the pipeline runner.
 */

import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

/** Resolve the project root (where pipeline_runner.py lives). */
export function getProjectRoot(): string {
  // cli/src/lib/process.ts → cli/src/lib → cli/src → cli → project root
  // cli/dist/lib/process.js → cli/dist/lib → cli/dist → cli → project root
  let dir = __dirname;
  for (let i = 0; i < 4; i++) {
    const candidate = resolve(dir, 'pipeline_runner.py');
    if (existsSync(candidate)) return dir;
    dir = dirname(dir);
  }
  // Fallback: cwd
  return process.cwd();
}

/** Find the correct Python executable.
 *  Prefers PAPER2MANIM_PYTHON (set by cli_launcher.py to the venv Python). */
export function findPython(): string {
  const envPython = process.env['PAPER2MANIM_PYTHON'];
  if (envPython) return envPython;

  const candidates = ['python3', 'python'];
  for (const cmd of candidates) {
    try {
      const result = spawn(cmd, ['--version'], { stdio: 'pipe' });
      result.kill();
      return cmd;
    } catch {
      // continue
    }
  }
  return 'python3';
}

/** Spawn the pipeline runner with the given JSON args. */
export function spawnRunner(argsJson: string): ChildProcess {
  const root = getProjectRoot();
  const runnerPath = resolve(root, 'pipeline_runner.py');
  const python = findPython();

  return spawn(python, ['-u', runnerPath, argsJson], {
    cwd: root,
    stdio: ['pipe', 'pipe', 'pipe'],
    env: { ...process.env },
  });
}
