/**
 * React hook that spawns the Python pipeline runner and streams NDJSON updates.
 */

import { useState, useCallback, useRef } from 'react';
import type { ChildProcess } from 'node:child_process';
import { spawnRunner } from '../lib/process.js';
import type { PipelineUpdate, PipelineArgs, QuestionDef } from '../lib/types.js';

export type PipelineStatus = 'idle' | 'questionnaire' | 'running' | 'complete' | 'error';

interface UsePipelineOptions {
  verbose?: boolean;
}

interface UsePipelineReturn {
  status: PipelineStatus;
  updates: PipelineUpdate[];
  questions: QuestionDef[];
  errorMessage: string;
  finalUpdate: PipelineUpdate | null;
  start: (args: PipelineArgs) => void;
  answerQuestions: (answers: Record<string, string>) => void;
  kill: () => void;
}

export function usePipeline(opts?: UsePipelineOptions): UsePipelineReturn {
  const verbose = opts?.verbose ?? false;
  const [status, setStatus] = useState<PipelineStatus>('idle');
  const [updates, setUpdates] = useState<PipelineUpdate[]>([]);
  const [questions, setQuestions] = useState<QuestionDef[]>([]);
  const [errorMessage, setErrorMessage] = useState('');
  const [finalUpdate, setFinalUpdate] = useState<PipelineUpdate | null>(null);
  const procRef = useRef<ChildProcess | null>(null);
  const bufferRef = useRef('');

  const handleLine = useCallback((line: string) => {
    try {
      const msg = JSON.parse(line);

      if (msg.type === 'questions') {
        setQuestions(msg.questions);
        setStatus('questionnaire');
      } else if (msg.type === 'pipeline') {
        const update = msg.update as PipelineUpdate;
        setUpdates(prev => [...prev, update]);
        setStatus('running');

        if (update.final) {
          if (update.error) {
            setErrorMessage(update.error);
            setStatus('error');
          } else {
            setStatus('complete');
          }
          setFinalUpdate(update);
        }
      } else if (msg.type === 'error') {
        setErrorMessage(msg.message);
        setStatus('error');
      }
    } catch {
      // Non-JSON line — ignore (Python debug output, etc.)
    }
  }, []);

  const processChunk = useCallback((chunk: Buffer) => {
    bufferRef.current += chunk.toString();
    const lines = bufferRef.current.split('\n');
    // Keep the last partial line in the buffer
    bufferRef.current = lines.pop() ?? '';
    for (const line of lines) {
      if (line.trim()) handleLine(line);
    }
  }, [handleLine]);

  const start = useCallback((args: PipelineArgs) => {
    setStatus('running');
    setUpdates([]);
    setQuestions([]);
    setErrorMessage('');
    setFinalUpdate(null);
    bufferRef.current = '';

    const proc = spawnRunner(JSON.stringify(args));
    procRef.current = proc;

    proc.stdout?.on('data', processChunk);

    proc.stderr?.on('data', (chunk: Buffer) => {
      // Only show Python stderr in verbose mode to keep UI clean
      if (verbose) {
        const text = chunk.toString().trim();
        if (text) {
          process.stderr.write(`[python] ${text}\n`);
        }
      }
    });

    proc.on('close', (code) => {
      // Flush any remaining buffer
      if (bufferRef.current.trim()) {
        handleLine(bufferRef.current.trim());
        bufferRef.current = '';
      }

      if (code !== 0 && status !== 'complete' && status !== 'error') {
        setErrorMessage(`Pipeline process exited with code ${code}`);
        setStatus('error');
      }
    });

    proc.on('error', (err) => {
      setErrorMessage(`Failed to start pipeline: ${err.message}`);
      setStatus('error');
    });
  }, [processChunk, handleLine, status, verbose]);

  const answerQuestions = useCallback((answers: Record<string, string>) => {
    const proc = procRef.current;
    if (!proc?.stdin?.writable) return;

    const msg = JSON.stringify({ type: 'answers', answers });
    proc.stdin.write(msg + '\n');
    setQuestions([]);
    setStatus('running');
  }, []);

  /** Kill the pipeline subprocess if it's still running. */
  const kill = useCallback(() => {
    const proc = procRef.current;
    if (proc && !proc.killed) {
      proc.kill('SIGTERM');
    }
  }, []);

  return { status, updates, questions, errorMessage, finalUpdate, start, answerQuestions, kill };
}
