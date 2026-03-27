/**
 * Non-interactive pipeline runner for --print and --output-format json modes.
 * Bypasses Ink entirely, writing plain text or a JSON summary to stdout.
 */

import { spawnRunner } from './process.js';
import type { PipelineArgs, QuestionDef, PipelineUpdate } from './types.js';

export async function runPrintMode(
  args: PipelineArgs,
  outputFormat: 'text' | 'json',
): Promise<void> {
  return new Promise((resolve, reject) => {
    const proc = spawnRunner(JSON.stringify(args));
    let buffer = '';
    let finalUpdate: PipelineUpdate | null = null;

    const handleLine = (line: string) => {
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(line);
      } catch {
        return; // ignore non-JSON (Python debug output, etc.)
      }

      if (msg.type === 'questions') {
        // Auto-answer using each question's default value
        const questions = msg.questions as QuestionDef[];
        const answers: Record<string, string> = {};
        for (const q of questions) {
          answers[q.id] = q.default ?? (q.options[0] ?? '');
        }
        if (proc.stdin?.writable) {
          proc.stdin.write(JSON.stringify({ type: 'answers', answers }) + '\n');
        }
        if (outputFormat === 'text') {
          process.stdout.write('[questionnaire] Using defaults\n');
        }
      } else if (msg.type === 'pipeline') {
        const update = msg.update as PipelineUpdate;
        if (outputFormat === 'text') {
          process.stdout.write(`[${update.stage}] ${update.status}\n`);
        }
        if (update.final) {
          finalUpdate = update;
        }
      } else if (msg.type === 'error') {
        process.stderr.write(`error: ${msg.message as string}\n`);
        proc.kill();
        process.exit(1);
      } else if (msg.type === 'preferences_summary') {
        if (outputFormat === 'text') {
          process.stdout.write(`[preferences] ${msg.summary as string}\n`);
        }
      }
    };

    proc.stdout?.on('data', (chunk: Buffer) => {
      buffer += chunk.toString();
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      for (const line of lines) {
        if (line.trim()) handleLine(line);
      }
    });

    proc.stderr?.on('data', (chunk: Buffer) => {
      // Suppress Python stderr in non-interactive mode (keep stdout clean)
      void chunk;
    });

    proc.on('close', (code) => {
      // Flush remaining buffer
      if (buffer.trim()) handleLine(buffer.trim());

      if (finalUpdate && !finalUpdate.error) {
        if (outputFormat === 'json') {
          const out = {
            video_path: finalUpdate.video_path ?? null,
            project_dir: finalUpdate.project_dir ?? null,
            timings: finalUpdate.timings ?? [],
            tool_call_counts: finalUpdate.tool_call_counts ?? {},
            total_tool_calls: finalUpdate.total_tool_calls ?? 0,
          };
          process.stdout.write(JSON.stringify(out, null, 2) + '\n');
        } else {
          process.stdout.write(`\ndone: ${finalUpdate.video_path ?? 'no video path'}\n`);
        }
        resolve();
      } else if (code !== 0) {
        const errMsg = finalUpdate?.error ?? `process exited with code ${code}`;
        process.stderr.write(`error: ${errMsg}\n`);
        process.exit(1);
      } else {
        resolve();
      }
    });

    proc.on('error', (err) => {
      process.stderr.write(`error: failed to start pipeline: ${err.message}\n`);
      reject(err);
    });
  });
}
