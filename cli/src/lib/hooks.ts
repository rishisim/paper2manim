/**
 * Hooks system — lifecycle event handlers for paper2manim.
 * Mirrors Claude Code CLI's hooks system.
 *
 * Hook handlers can be:
 *   - command: spawn a shell command with JSON payload on stdin
 *   - http: POST JSON payload to an HTTP endpoint
 */

import { spawn } from 'node:child_process';
import type { HookEvent, HooksConfig } from './types.js';

/** Run all hooks registered for a given event. */
export async function runHooks(
  event: HookEvent,
  payload: Record<string, unknown>,
  config: HooksConfig,
  disabled = false,
): Promise<void> {
  if (disabled) return;
  const handlers = config[event] ?? [];
  if (handlers.length === 0) return;

  const payloadStr = JSON.stringify({ event, ...payload });

  await Promise.allSettled(
    handlers.map(handler => {
      if (handler.type === 'command') {
        return runCommandHook(handler.command, payloadStr);
      } else if (handler.type === 'http') {
        return runHttpHook(handler.url, payload);
      }
      return Promise.resolve();
    }),
  );
}

function runCommandHook(command: string, payloadJson: string): Promise<void> {
  return new Promise<void>((resolve) => {
    try {
      const child = spawn(command, [], {
        shell: true,
        stdio: ['pipe', 'ignore', 'ignore'],
      });

      child.stdin?.write(payloadJson + '\n');
      child.stdin?.end();

      // 10-second timeout for hook commands
      const timeout = setTimeout(() => {
        child.kill();
        resolve();
      }, 10000);

      child.on('close', () => {
        clearTimeout(timeout);
        resolve();
      });

      child.on('error', () => {
        clearTimeout(timeout);
        resolve();
      });
    } catch {
      resolve();
    }
  });
}

async function runHttpHook(url: string, payload: Record<string, unknown>): Promise<void> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);

    await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    clearTimeout(timeout);
  } catch {
    // Silently ignore hook HTTP failures
  }
}
