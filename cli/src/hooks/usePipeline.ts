/**
 * React hook that spawns the Python pipeline runner and streams NDJSON updates.
 */

import { useState, useCallback, useRef } from 'react';
import type { ChildProcess } from 'node:child_process';
import { spawnRunner } from '../lib/process.js';
import type { PipelineUpdate, PipelineArgs, QuestionDef, ToolCallEntry } from '../lib/types.js';

export type PipelineStatus = 'idle' | 'questionnaire' | 'running' | 'complete' | 'error';

interface UsePipelineOptions {
  verbose?: boolean;
  onTokenUsage?: (delta: { input: number; output: number; cacheRead: number }) => void;
}

interface UsePipelineReturn {
  status: PipelineStatus;
  updates: PipelineUpdate[];
  questions: QuestionDef[];
  errorMessage: string;
  finalUpdate: PipelineUpdate | null;
  toolCalls: ToolCallEntry[];
  thinkingText: string;
  permissionPending: { operation: string; path?: string } | null;
  start: (args: PipelineArgs) => void;
  answerQuestions: (answers: Record<string, string>) => void;
  answerPermission: (allow: boolean, always?: boolean) => void;
  kill: () => void;
}

export function usePipeline(opts?: UsePipelineOptions): UsePipelineReturn {
  const verbose = opts?.verbose ?? false;
  const [status, setStatus] = useState<PipelineStatus>('idle');
  const [updates, setUpdates] = useState<PipelineUpdate[]>([]);
  const [questions, setQuestions] = useState<QuestionDef[]>([]);
  const [errorMessage, setErrorMessage] = useState('');
  const [finalUpdate, setFinalUpdate] = useState<PipelineUpdate | null>(null);
  const [toolCalls, setToolCalls] = useState<ToolCallEntry[]>([]);
  const [thinkingText, setThinkingText] = useState('');
  const [permissionPending, setPermissionPending] = useState<{ operation: string; path?: string } | null>(null);
  const procRef = useRef<ChildProcess | null>(null);
  const bufferRef = useRef('');
  const toolCallIdCounter = useRef(0);

  // Context-injected callback for token usage (set by parent via ref)
  const onTokenUsage = opts?.onTokenUsage;

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
      } else if (msg.type === 'token_usage') {
        // Phase 5: accumulate token usage
        if (onTokenUsage) {
          onTokenUsage({ input: msg.input ?? 0, output: msg.output ?? 0, cacheRead: msg.cache_read ?? 0 });
        }
      } else if (msg.type === 'thinking') {
        // Phase 5: update thinking text
        setThinkingText(msg.text ?? '');
      } else if (msg.type === 'tool_call') {
        // Phase 5: add tool call entry
        const entry: ToolCallEntry = {
          id: `tc-${toolCallIdCounter.current++}`,
          name: msg.name ?? 'unknown',
          params: msg.params ?? {},
          output: msg.output,
          collapsed: true,
        };
        setToolCalls(prev => [...prev, entry]);
      } else if (msg.type === 'permission_request') {
        // Phase 6: permission prompt
        setPermissionPending({ operation: msg.operation ?? 'write', path: msg.path });
      }
      // Unknown types are silently ignored (backward compatible)
    } catch {
      // Non-JSON line — ignore (Python debug output, etc.)
    }
  }, [onTokenUsage]); // eslint-disable-line react-hooks/exhaustive-deps

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
    setToolCalls([]);
    setThinkingText('');
    setPermissionPending(null);
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

  /** Respond to a permission_request from Python. */
  const answerPermission = useCallback((allow: boolean, always = false) => {
    const proc = procRef.current;
    setPermissionPending(null);
    if (!proc?.stdin?.writable) return;
    const msg = JSON.stringify({ type: 'permission_response', allow, always });
    proc.stdin.write(msg + '\n');
  }, []);

  /** Kill the pipeline subprocess if it's still running. */
  const kill = useCallback(() => {
    const proc = procRef.current;
    if (proc && !proc.killed) {
      proc.kill('SIGTERM');
    }
  }, []);

  return { status, updates, questions, errorMessage, finalUpdate, toolCalls, thinkingText, permissionPending, start, answerQuestions, answerPermission, kill };
}
