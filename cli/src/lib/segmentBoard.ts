import type {
  PipelineUpdate,
  SegmentState,
  SegmentTraceCategory,
  SegmentTraceEntry,
  WorkerRole,
  WorkerStatus,
} from './types.js';
import type { StageName } from './theme.js';

const TRACE_LIMIT = 64;

function normalizeText(text: string | undefined): string | undefined {
  if (!text) return undefined;
  const cleaned = text.replace(/\s+/g, ' ').trim();
  return cleaned || undefined;
}

function titleCaseWorker(role: WorkerRole): string {
  return role.charAt(0).toUpperCase() + role.slice(1);
}

export function workerLabel(role: WorkerRole): string {
  if (role === 'tts') return 'TTS';
  if (role === 'coder') return 'Coder';
  if (role === 'verifier') return 'Verifier';
  if (role === 'renderer') return 'Renderer';
  if (role === 'stitcher') return 'Stitcher';
  return 'Planner';
}

export function inferWorkerRole(stage: StageName, phase?: string, status?: string): WorkerRole {
  const raw = `${phase ?? ''} ${status ?? ''}`.toLowerCase();
  if (stage === 'plan') return 'planner';
  if (stage === 'tts') return 'tts';
  if (stage === 'render') return 'renderer';
  if (stage === 'stitch' || stage === 'concat' || stage === 'timing' || stage === 'subtitles' || stage === 'overlay') {
    return 'stitcher';
  }
  if (stage === 'verify') return 'verifier';
  if (/verify|validation|check|docs|inspect/.test(raw)) return 'verifier';
  return 'coder';
}

export function inferWorkerStatus(phase: string, status?: string): WorkerStatus {
  const raw = `${phase} ${status ?? ''}`.toLowerCase();
  if (/failed|error|fatal/.test(raw)) return 'failed';
  if (/warn|busy|retry/.test(raw)) return 'warning';
  if (/queued|waiting/.test(raw)) return 'queued';
  if (/blocked/.test(raw)) return 'blocked';
  if (/done|complete|ready|success/.test(raw)) return 'done';
  return 'working';
}

export function buildTaskLabel(role: WorkerRole, prettyPhase: string, status?: string): string {
  const cleaned = normalizeText(status) ?? prettyPhase;
  if (!cleaned) return workerLabel(role);
  const lower = cleaned.toLowerCase();
  const prefixes = [
    'coder:',
    'verifier:',
    'renderer:',
    'stitcher:',
    'planner:',
    'tts:',
  ];
  if (prefixes.some(prefix => lower.startsWith(prefix))) {
    return cleaned;
  }
  return `${workerLabel(role)}: ${cleaned}`;
}

export function badgeForStage(stage: StageName, workerStatus: WorkerStatus): string | undefined {
  if (workerStatus !== 'done' && workerStatus !== 'warning' && workerStatus !== 'working') return undefined;
  if (stage === 'tts' && workerStatus === 'done') return 'TTS done';
  if ((stage === 'code' || stage === 'code_retry') && workerStatus === 'done') return 'Draft code ready';
  if (stage === 'verify' && workerStatus === 'warning') return 'Verification warning';
  if (stage === 'verify' && workerStatus === 'done') return 'Verification done';
  if (stage === 'render' && workerStatus === 'working') return 'HD render running';
  if (stage === 'render' && workerStatus === 'done') return 'HD render done';
  if ((stage === 'stitch' || stage === 'concat' || stage === 'timing') && workerStatus === 'working') return 'Final assembly running';
  if ((stage === 'stitch' || stage === 'concat' || stage === 'timing') && workerStatus === 'done') return 'Final assembly done';
  return undefined;
}

export function makeTraceEntry(
  category: SegmentTraceCategory,
  text: string,
  workerRole: WorkerRole | undefined,
  ts: number,
): SegmentTraceEntry {
  return {
    id: `${category}:${workerRole ?? 'none'}:${ts}:${text.slice(0, 24)}`,
    category,
    text,
    ts,
    workerRole,
  };
}

export function appendTrace(
  trace: SegmentTraceEntry[] | undefined,
  entry: SegmentTraceEntry | undefined,
): SegmentTraceEntry[] {
  const base = trace ?? [];
  if (!entry) return base;
  const last = base[base.length - 1];
  if (last && last.category === entry.category && last.text === entry.text && last.workerRole === entry.workerRole) {
    return base;
  }
  const next = [...base, entry];
  return next.slice(-TRACE_LIMIT);
}

export function extractStoryboardTitles(storyboard: unknown): Map<number, string> {
  const out = new Map<number, string>();
  if (!storyboard || typeof storyboard !== 'object') return out;
  const segments = (storyboard as { segments?: unknown }).segments;
  if (!Array.isArray(segments)) return out;
  for (const segment of segments) {
    if (!segment || typeof segment !== 'object') continue;
    const id = Number((segment as { id?: unknown }).id);
    const title = normalizeText((segment as { title?: unknown }).title as string | undefined);
    if (Number.isFinite(id) && title) out.set(id, title);
  }
  return out;
}

export interface ReduceSegmentUpdateInput {
  stage: StageName;
  phase: string;
  prettyPhase: string;
  status?: string;
  error?: string;
  now: number;
  attempt?: number;
  thinking?: PipelineUpdate['thinking'];
  toolCall?: PipelineUpdate['tool_call'];
  toolResult?: PipelineUpdate['tool_result'];
  streamEvent?: PipelineUpdate['stream_event'];
}

export function reduceSegmentUpdate(
  previous: SegmentState | undefined,
  input: ReduceSegmentUpdateInput,
): SegmentState {
  const workerRole = inferWorkerRole(input.stage, input.phase, input.status);
  const workerStatus = inferWorkerStatus(input.phase, input.status);
  const trace = previous?.trace ?? [];
  const workerRoles = Array.from(new Set([...(previous?.workerRoles ?? []), workerRole]));
  const workerStates = { ...(previous?.workerStates ?? {}), [workerRole]: workerStatus };
  const prettyTask = buildTaskLabel(workerRole, input.prettyPhase, input.status);
  const badge = badgeForStage(input.stage, workerStatus);

  let nextTrace = trace;
  nextTrace = appendTrace(nextTrace, makeTraceEntry('status', prettyTask, workerRole, input.now));

  let latestInference = previous?.latestInference;
  let liveCode = previous?.liveCode;
  let liveThinking = previous?.liveThinking;
  let liveConsole = previous?.liveConsole;
  let latestReasoningKind = previous?.latestReasoningKind;
  if (input.thinking) {
    latestInference = normalizeText(typeof input.thinking === 'string' ? input.thinking : 'Reasoning in progress');
    liveThinking = latestInference;
    latestReasoningKind = input.streamEvent?.channel === 'thinking' ? 'raw_reasoning' : 'inferred_reasoning';
    if (latestInference) {
      nextTrace = appendTrace(nextTrace, makeTraceEntry('inference', latestInference, workerRole, input.now));
    }
  }
  else {
    const inferredFromStatus = normalizeText(input.status);
    if (inferredFromStatus && /generating|looking up|repairing|validating|verifying|applying|timing normalized/i.test(inferredFromStatus)) {
      latestInference = inferredFromStatus;
      liveThinking = inferredFromStatus;
      latestReasoningKind = 'inferred_reasoning';
      nextTrace = appendTrace(nextTrace, makeTraceEntry('inference', inferredFromStatus, workerRole, input.now));
    }
  }

  let latestCheck = previous?.latestCheck;
  if (input.toolCall) {
    const toolText = normalizeText(input.toolCall.name);
    if (toolText) {
      latestCheck = `${titleCaseWorker(workerRole)} tool: ${toolText}`;
      liveConsole = latestCheck;
      nextTrace = appendTrace(nextTrace, makeTraceEntry('check', latestCheck, workerRole, input.now));
    }
  }

  if (input.toolResult?.output) {
    const preview = normalizeText(input.toolResult.output.slice(0, 160));
    if (preview) {
      latestCheck = preview;
      liveConsole = preview;
      nextTrace = appendTrace(nextTrace, makeTraceEntry('check', preview, workerRole, input.now));
    }
  }

  if (input.streamEvent) {
    const snapshot = normalizeText(input.streamEvent.snapshot);
    if (input.streamEvent.channel === 'code') {
      liveCode = input.streamEvent.snapshot ?? liveCode;
      if (snapshot) {
        const summary = `writing ${input.streamEvent.snapshot?.split('\n').length ?? 0} lines`;
        nextTrace = appendTrace(nextTrace, makeTraceEntry('code', summary, workerRole, input.now));
      }
    } else if (input.streamEvent.channel === 'thinking') {
      liveThinking = input.streamEvent.snapshot ?? input.streamEvent.delta ?? liveThinking;
      latestInference = normalizeText(input.streamEvent.snapshot ?? input.streamEvent.delta) ?? latestInference;
      latestReasoningKind = 'raw_reasoning';
      const deltaText = normalizeText(input.streamEvent.delta);
      if (deltaText) {
        nextTrace = appendTrace(nextTrace, makeTraceEntry('inference', deltaText, workerRole, input.now));
      }
    } else {
      liveConsole = input.streamEvent.snapshot ?? input.streamEvent.delta ?? liveConsole;
      const deltaText = normalizeText(input.streamEvent.delta);
      if (deltaText) {
        nextTrace = appendTrace(nextTrace, makeTraceEntry('status', deltaText, workerRole, input.now));
      }
    }
  }

  const warningText = normalizeText(input.error) ?? (/warn|busy/.test((input.status ?? '').toLowerCase()) ? normalizeText(input.status) : undefined);
  let latestWarning = previous?.latestWarning;
  if (warningText) {
    latestWarning = warningText;
    nextTrace = appendTrace(nextTrace, makeTraceEntry('warning', warningText, workerRole, input.now));
  }

  if (workerStatus === 'done' || workerStatus === 'failed') {
    nextTrace = appendTrace(
      nextTrace,
      makeTraceEntry(workerStatus === 'done' ? 'completion' : 'warning', prettyTask, workerRole, input.now),
    );
  }

  const completedBadges = Array.from(
    new Set([
      ...(previous?.completedBadges ?? []),
      ...(badge ? [badge] : []),
    ]),
  );

  return {
    id: previous?.id ?? 0,
    title: previous?.title,
    phase: input.phase,
    prettyPhase: input.prettyPhase,
    attempt: input.attempt ?? previous?.attempt ?? 1,
    done: workerStatus === 'done',
    failed: workerStatus === 'failed',
    startedAt: previous?.startedAt ?? input.now,
    finishedAt: workerStatus === 'done' || workerStatus === 'failed' ? input.now : previous?.finishedAt,
    updatedAt: input.now,
    currentWorker: workerRole,
    currentTask: prettyTask,
    latestInference,
    latestCodeSummary: previous?.latestCodeSummary,
    latestCheck,
    latestWarning,
    liveCode,
    liveThinking,
    liveConsole,
    latestReasoningKind,
    workerRoles,
    workerStates,
    completedBadges,
    trace: nextTrace,
    isThinking: !!input.thinking,
    thinkingText: typeof input.thinking === 'string' ? input.thinking : undefined,
    lastStatus: normalizeText(input.status) ?? previous?.lastStatus,
    lastToolCall: input.toolCall ?? previous?.lastToolCall,
    lastToolResult: input.toolResult ?? previous?.lastToolResult,
    failHint: warningText ?? previous?.failHint,
  };
}
