/**
 * React hook that spawns the Python pipeline runner and streams NDJSON updates.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
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
  // H3: use a ref for status so `start` callback doesn't depend on status state
  const statusRef = useRef<PipelineStatus>('idle');
  // Track whether a final update was received (C1)
  const finalUpdateReceivedRef = useRef(false);

  // Keep statusRef in sync
  const updateStatus = useCallback((s: PipelineStatus) => {
    statusRef.current = s;
    setStatus(s);
  }, []);

  // L1: Stabilize onTokenUsage via a ref so handleLine's dep array doesn't
  // recreate the callback on every render when the caller passes a new function reference.
  const onTokenUsageRef = useRef(opts?.onTokenUsage);
  useEffect(() => { onTokenUsageRef.current = opts?.onTokenUsage; });

  const handleLine = useCallback((line: string) => {
    try {
      const msg = JSON.parse(line);

      if (msg.type === 'questions') {
        setQuestions(msg.questions);
        updateStatus('questionnaire');
      } else if (msg.type === 'pipeline') {
        const update = msg.update as PipelineUpdate;
        setUpdates(prev => [...prev, update]);
        updateStatus('running');

        if (update.final) {
          finalUpdateReceivedRef.current = true;
          if (update.error) {
            setErrorMessage(update.error);
            updateStatus('error');
          } else {
            updateStatus('complete');
          }
          setFinalUpdate(update);
        }
      } else if (msg.type === 'error') {
        setErrorMessage(msg.message);
        updateStatus('error');
      } else if (msg.type === 'token_usage') {
        onTokenUsageRef.current?.({ input: msg.input ?? 0, output: msg.output ?? 0, cacheRead: msg.cache_read ?? 0 });
      } else if (msg.type === 'thinking') {
        setThinkingText(msg.text ?? '');
      } else if (msg.type === 'tool_call') {
        const entry: ToolCallEntry = {
          id: `tc-${toolCallIdCounter.current++}`,
          name: msg.name ?? 'unknown',
          params: msg.params ?? {},
          output: msg.output,
          collapsed: true,
        };
        setToolCalls(prev => [...prev, entry]);
      } else if (msg.type === 'permission_request') {
        setPermissionPending({ operation: msg.operation ?? 'write', path: msg.path });
      }
      // Unknown types are silently ignored (backward compatible)
    } catch {
      // H13: Non-JSON line — log in verbose mode, ignore otherwise
      if (verbose) {
        process.stderr.write(`[warn] Non-JSON pipeline line: ${line.slice(0, 120)}\n`);
      }
    }
  }, [updateStatus, verbose]);

  const processChunk = useCallback((chunk: Buffer) => {
    bufferRef.current += chunk.toString();
    // C3: Warn if buffer grows suspiciously large (indicates a very long partial line)
    if (bufferRef.current.length > 65536 && verbose) {
      process.stderr.write(`[warn] Pipeline buffer at ${bufferRef.current.length} bytes — possible partial message\n`);
    }
    const lines = bufferRef.current.split('\n');
    // Keep the last partial line in the buffer
    bufferRef.current = lines.pop() ?? '';
    for (const line of lines) {
      if (line.trim()) handleLine(line);
    }
  }, [handleLine, verbose]);

  const start = useCallback((args: PipelineArgs) => {
    // H3: reset without depending on status state in the dep array
    updateStatus('running');
    setUpdates([]);
    setQuestions([]);
    setErrorMessage('');
    setFinalUpdate(null);
    setToolCalls([]);
    setThinkingText('');
    setPermissionPending(null);
    bufferRef.current = '';
    finalUpdateReceivedRef.current = false;

    const proc = spawnRunner(JSON.stringify(args));
    procRef.current = proc;

    proc.stdout?.on('data', processChunk);

    proc.stderr?.on('data', (chunk: Buffer) => {
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

      // H12: Clear any dangling permission prompt when process exits
      setPermissionPending(null);

      // C1: Set error if process exited non-zero AND no proper final update was received
      if (code !== 0 && !finalUpdateReceivedRef.current) {
        setErrorMessage(`Pipeline process exited with code ${code}`);
        updateStatus('error');
      }
    });

    proc.on('error', (err) => {
      setErrorMessage(`Failed to start pipeline: ${err.message}`);
      updateStatus('error');
    });
  }, [processChunk, handleLine, updateStatus, verbose]); // H3: no `status` in deps

  const answerQuestions = useCallback((answers: Record<string, string>) => {
    const proc = procRef.current;
    if (!proc?.stdin?.writable) return;

    const msg = JSON.stringify({ type: 'answers', answers });
    proc.stdin.write(msg + '\n');
    setQuestions([]);
    updateStatus('running');
  }, [updateStatus]);

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
      // H4: Clean up listeners before killing to prevent leaks on multiple kill() calls
      proc.stdout?.removeAllListeners();
      proc.stderr?.removeAllListeners();
      proc.removeAllListeners();
      proc.kill('SIGTERM');
    }
  }, []);

  return { status, updates, questions, errorMessage, finalUpdate, toolCalls, thinkingText, permissionPending, start, answerQuestions, answerPermission, kill };
}
