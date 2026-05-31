import { execSync, execFileSync } from 'node:child_process';
import { appendFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Box, Text, useApp, useInput } from 'ink';
import { Banner } from './components/Banner.js';
import { ConceptInput } from './components/ConceptInput.js';
import { WelcomeScreen } from './components/WelcomeScreen.js';
import { Questionnaire } from './components/Questionnaire.js';
import { type ActivityLine, type ActivityKind } from './components/StatusBar.js';
// RunTimeline removed — replaced by RunScreen
import { WorkspaceDashboard } from './components/WorkspaceDashboard.js';
import { FooterStatusLine } from './components/FooterStatusLine.js';
import { PromptBar } from './components/PromptBar.js';
import { SettingsPanel } from './components/SettingsPanel.js';
import { DoctorPanel } from './components/DoctorPanel.js';
import { ContextVisualizer } from './components/ContextVisualizer.js';
import { KeybindingsHelpOverlay } from './components/KeybindingsHelpOverlay.js';
import { KeyboardShortcuts } from './components/KeyboardShortcuts.js';
import { PermissionPrompt } from './components/PermissionPrompt.js';
import { RunScreen, type RunScreenErrorInfo } from './components/RunScreen.js';
import type { FeedItem, FeedItemInput } from './lib/feedItems.js';
import { runHooks } from './lib/hooks.js';
import { usePipeline } from './hooks/usePipeline.js';
import { useElapsed } from './hooks/useElapsed.js';
import { useTerminalWidth } from './hooks/useTerminalWidth.js';
import { useTerminalHeight } from './hooks/useTerminalHeight.js';
import { AppContextProvider, useAppContext } from './context/AppContext.js';
import { exportSessionToText } from './lib/session.js';
import { loadMemory } from './lib/memory.js';
import { appendTrace, extractStoryboardTitles, inferWorkerRole, makeTraceEntry, reduceSegmentUpdate } from './lib/segmentBoard.js';
import { getStageConfig, segmentPhaseLabels, cleanStatus, type StageName } from './lib/theme.js';
import { formatDuration, formatToolCall } from './lib/format.js';
import { summarizeToolOutput } from './components/StatusBar.js';
import { buildCompactUnifiedDiff } from './lib/codeDiff.js';
import { collapseRunLogsForRetry, getRunLogDedupeKey, sanitizeRunLogText } from './lib/runLog.js';
import { resolveEffectiveVerbose } from './lib/verbose.js';
import type { BoardActivityDot, BoardRowModel, CompletedStage, ProgressMode, ReasoningKind, RunEventRecord, SegmentState, Settings, Session } from './lib/types.js';
import { PERMISSION_MODES } from './lib/types.js';

interface AppProps {
  initialConcept?: string;
  maxRetries: number;
  isLite: boolean;
  quality?: 'low' | 'medium' | 'high';
  skipAudio?: boolean;
  workspace?: boolean;
  resumeDir?: string;
  verbose: boolean;
  renderTimeout?: number;
  ttsTimeout?: number;
  // Phase 1 additions
  settings: Settings;
  session: Session;
  gitBranch: string | null;
  systemPrompt?: string;
  maxTurns?: number;
  noSessionPersistence?: boolean;
}

type Screen = 'input' | 'workspace' | 'questionnaire' | 'running' | 'complete' | 'error' | 'settings' | 'context' | 'doctor' | 'keybindings';

/** A single log entry rendered in the Static scroll region. */
interface LogEntry {
  id: string;
  type: 'header' | 'stage-complete' | 'log' | 'segment';
  dedupeKey?: string;
  // For stage-complete
  stage?: CompletedStage;
  // For log / segment lines
  text?: string;
  color?: string;
  icon?: string;
  bold?: boolean;
}

function activityPrefix(text: string): string {
  return text.trim().replace(/\s+/g, ' ').toLowerCase().slice(0, 42);
}

function coerceText(value: unknown, fallback = ''): string {
  if (typeof value === 'string') return value;
  if (value === null || value === undefined) return fallback;
  return String(value);
}

function extractFailureHint(raw?: string): string | undefined {
  if (!raw) return undefined;
  const line = raw
    .split('\n')
    .map(s => s.trim())
    .find(Boolean);
  if (!line) return undefined;
  return line.length > 110 ? `${line.slice(0, 109)}…` : line;
}

function classifyActivityGroup(text: unknown): 'doing' | 'checking' | 'fixing' | 'done' {
  const raw = coerceText(text).toLowerCase();
  if (/complete|completed|done|ready|success/.test(raw)) return 'done';
  if (/fix|retry|recover|repair/.test(raw)) return 'fixing';
  if (/verify|check|validate|docs|inspect/.test(raw)) return 'checking';
  return 'doing';
}

function classifyActivitySeverity(text: unknown): 'normal' | 'warning' | 'critical' {
  const raw = coerceText(text).toLowerCase();
  if (/fail|error|fatal|crash/.test(raw)) return 'critical';
  if (/retry|warn|slow/.test(raw)) return 'warning';
  return 'normal';
}

function eventIdFor(event: Pick<RunEventRecord, 'run_id' | 'seq'>): string {
  return `event:${event.run_id}:${event.seq}`;
}

function inferReasoningKindFromText(text: string): ReasoningKind {
  return /generating|looking up|repairing|validating|verifying|applying|timing normalized/i.test(text)
    ? 'inferred_reasoning'
    : 'status_summary';
}

function reasoningLabel(kind: ReasoningKind): string {
  if (kind === 'raw_reasoning') return 'Reasoning (model)';
  if (kind === 'inferred_reasoning') return 'Inference (UI summary)';
  return 'Status summary';
}

function buildToolPreview(name: string, output: string): string {
  return `${name}: ${summarizeToolOutput(output, 132)}`;
}

function relativeAge(updatedAt: number | undefined, now: number): string | undefined {
  if (!updatedAt) return undefined;
  const seconds = Math.max(0, Math.round((now - updatedAt) / 1000));
  return `${seconds}s`;
}

function compactCodePreview(code: string | undefined, maxLines: number): string[] | undefined {
  if (!code) return undefined;
  const lines = code.split('\n').slice(-maxLines).map(line => line.replace(/\t/g, '    '));
  return lines.length > 0 ? lines : undefined;
}

function activityDotsForSegment(segment: SegmentState): BoardActivityDot[] {
  const dots: BoardActivityDot[] = [];
  if (segment.latestReasoningKind) dots.push('reasoning');
  if (segment.lastToolCall || segment.lastToolResult) dots.push('tool');
  if (segment.latestCodeSummary || segment.liveCode) dots.push('code');
  if (segment.latestWarning) dots.push('warning');
  if (segment.done) dots.push('done');
  return dots;
}

function renderSingleLineBlock(text: string, maxLength: number): string {
  const compact = text.replace(/\s+/g, ' ').trim();
  if (compact.length <= maxLength) return compact;
  return `${compact.slice(0, Math.max(0, maxLength - 1))}…`;
}

function compactToolPreview(segment: SegmentState, width: number): string | undefined {
  const maxLength = width < 100 ? 24 : 34;
  if (segment.lastToolResult?.output) {
    return renderSingleLineBlock(summarizeToolOutput(segment.lastToolResult.output, maxLength), maxLength);
  }
  if (segment.lastToolCall) {
    return renderSingleLineBlock(formatToolCall(segment.lastToolCall.name, segment.lastToolCall.params), maxLength);
  }
  return undefined;
}

function selectedEventDetailLines(event: RunEventRecord | undefined): string[] {
  if (!event) return ['No event selected.'];
  const lines: string[] = [];
  lines.push(event.message);
  if (event.source || event.worker_role || event.channel) {
    lines.push('');
    lines.push(`source: ${event.source ?? 'unknown'}`);
    if (event.worker_role) lines.push(`worker: ${event.worker_role}`);
    if (event.channel) lines.push(`channel: ${event.channel}`);
  }
  if (event.reasoning) {
    lines.push('');
    lines.push(`reasoning: ${reasoningLabel(event.reasoning.kind)}`);
  }
  if (event.tool) {
    lines.push('');
    lines.push(`tool: ${event.tool.name}`);
    if (event.tool.output_preview) lines.push(`preview: ${event.tool.output_preview}`);
  }
  if (event.detail) {
    lines.push('');
    lines.push(...event.detail.split('\n').map(s => s.trimEnd()).filter(Boolean));
  }
  if (event.data && Object.keys(event.data).length > 0) {
    lines.push('');
    lines.push('data:');
    lines.push(...JSON.stringify(event.data, null, 2).split('\n'));
  }
  return lines;
}

function AppInner({ initialConcept, maxRetries, isLite, quality = 'high', skipAudio = false, workspace = false, resumeDir, verbose, renderTimeout, ttsTimeout, systemPrompt, maxTurns }: Omit<AppProps, 'settings' | 'session' | 'gitBranch' | 'noSessionPersistence' | 'quality'> & { quality?: 'low'|'medium'|'high' }) {
  const { exit } = useApp();
  const {
    themeColors,
    permissionMode,
    currentModel,
    verboseMode: ctxVerboseMode,
    thinkingVisible,
    quality: ctxQuality,
    gitBranch,
    cyclePermissionMode,
    setPermissionMode,
    setVerboseMode,
    setThinkingVisible,
    setQuality,
    setCurrentModel,
    setPromptColor,
    updateSetting,
    addTokenUsage,
    pushHistory,
    updateSession,
    session,
  } = useAppContext();

  const pipeline = usePipeline({ verbose, onTokenUsage: addTokenUsage });
  const termWidth = useTerminalWidth();
  const termHeight = useTerminalHeight();

  const initialScreen: Screen = workspace ? 'workspace' : (initialConcept || resumeDir) ? 'running' : 'input';
  const [screen, setScreen] = useState<Screen>(initialScreen);
  const [concept, setConcept] = useState(initialConcept ?? '');
  // runViewMode removed — RunScreen is the single view now

  // All rendered log items (scroll region via Static)
  const [logEntries, setLogEntries] = useState<LogEntry[]>([]);
  const logIdCounter = useRef(0);
  const [activeRunLogStart, setActiveRunLogStart] = useState(0);
  const activeRunLogStartRef = useRef(0);
  const [collapsedHistoryCount, setCollapsedHistoryCount] = useState(0);
  useEffect(() => { activeRunLogStartRef.current = activeRunLogStart; }, [activeRunLogStart]);

  // Durable run-event journal (NDJSON). Keeps full history even when UI collapses.
  const runIdRef = useRef(`run-${Date.now()}`);
  const runSeqRef = useRef(0);
  const runEventsRef = useRef<RunEventRecord[]>([]);
  const runEventPathRef = useRef<string | null>(null);
  const runProjectDirRef = useRef<string | null>(null);
  const [runEventPathDisplay, setRunEventPathDisplay] = useState<string | null>(null);
  const [runEventVersion, setRunEventVersion] = useState(0);
  // Board navigation (used by RunScreen's SegmentListCompact)
  const [boardSelectedSegmentId, setBoardSelectedSegmentId] = useState<number | undefined>(undefined);
  const [boardScrollOffset, setBoardScrollOffset] = useState(0);
  const [boardFollowMode, setBoardFollowMode] = useState(true);

  const defaultRunEventPath = useCallback((runId: string) => {
    const folder = path.join(process.cwd(), 'output', '.run_events');
    if (!existsSync(folder)) mkdirSync(folder, { recursive: true });
    return path.join(folder, `${runId}.ndjson`);
  }, []);

  const writeRunEvent = useCallback((event: RunEventRecord) => {
    runEventsRef.current.push(event);
    setRunEventVersion(v => v + 1);
    const journalPath = runEventPathRef.current ?? defaultRunEventPath(runIdRef.current);
    runEventPathRef.current = journalPath;
    setRunEventPathDisplay(journalPath);
    appendFileSync(journalPath, `${JSON.stringify(event)}\n`, 'utf-8');
  }, [defaultRunEventPath]);

  const switchRunEventPathToProject = useCallback((projectDir: string) => {
    if (!projectDir) return;
    if (runProjectDirRef.current === projectDir && runEventPathRef.current === path.join(projectDir, 'run_events.ndjson')) {
      return;
    }
    if (!existsSync(projectDir)) return;
    runProjectDirRef.current = projectDir;
    const nextPath = path.join(projectDir, 'run_events.ndjson');
    const payload = runEventsRef.current.map(ev => JSON.stringify(ev)).join('\n');
    writeFileSync(nextPath, payload.length > 0 ? `${payload}\n` : '', 'utf-8');
    runEventPathRef.current = nextPath;
    setRunEventPathDisplay(nextPath);
  }, []);

  const addRunEvent = useCallback((event: Omit<RunEventRecord, 'run_id' | 'seq' | 'ts'>) => {
    const record: RunEventRecord = {
      run_id: runIdRef.current,
      seq: runSeqRef.current++,
      ts: new Date().toISOString(),
      ...event,
    };
    writeRunEvent(record);
    return record;
  }, [writeRunEvent]);

  const resetRunEventJournal = useCallback((label: string) => {
    runIdRef.current = `run-${Date.now()}`;
    runSeqRef.current = 0;
    runEventsRef.current = [];
    runProjectDirRef.current = null;
    runEventPathRef.current = defaultRunEventPath(runIdRef.current);
    setRunEventPathDisplay(runEventPathRef.current);
    addRunEvent({ kind: 'run_marker', message: label, source: 'ui_derived' });
    setBoardSelectedSegmentId(undefined);
    setBoardScrollOffset(0);
    setBoardFollowMode(true);
  }, [addRunEvent, defaultRunEventPath]);

  const addLog = (entry: Omit<LogEntry, 'id'>) => {
    const id = `log-${logIdCounter.current++}`;
    const sanitizedEntry: Omit<LogEntry, 'id'> = entry.text
      ? { ...entry, text: sanitizeRunLogText(entry.text) }
      : entry;
    const dedupeKey = getRunLogDedupeKey(sanitizedEntry);
    setLogEntries(prev => {
      // Dedup: skip if the last entry has the same normalized key.
      const last = prev[prev.length - 1];
      if (last && last.dedupeKey === dedupeKey) {
        return prev;
      }
      return [...prev, { id, ...sanitizedEntry, dedupeKey }];
    });
  };

  // Pipeline state
  const [currentStage, setCurrentStage] = useState<StageName | null>(null);
  const currentStageRef = useRef<StageName | null>(null);
  const [stageStartTime, setStageStartTime] = useState(Date.now());
  const stageStartTimeRef = useRef(Date.now());
  const [segments, setSegments] = useState<Map<number, SegmentState>>(new Map());
  const segmentsRef = useRef<Map<number, SegmentState>>(new Map());
  const [totalSegments, setTotalSegments] = useState(0);
  const [statusDetail, setStatusDetail] = useState('');
  const statusDetailRef = useRef('');
  const [completedStages, setCompletedStages] = useState<CompletedStage[]>([]);
  const completedStagesRef = useRef<CompletedStage[]>([]);
  // inspectRows removed — RunScreen replaces the inspect view

  // Activity stream (Claude Code-style) — recent activity lines for live display
  const [activityLines, setActivityLines] = useState<ActivityLine[]>([]);
  const activityIdCounter = useRef(0);
  const segmentCodeCacheRef = useRef<Map<number, string>>(new Map());

  // ── Streaming feed state ─────────────────────────────────────
  const [runState, setRunState] = useState<'active' | 'complete' | 'error'>('active');
  const [segmentCodes, setSegmentCodes] = useState<Map<number, string>>(new Map());
  const [codeRecentChanges, setCodeRecentChanges] = useState<Map<number, Set<number>>>(new Map());
  const [feedItems, setFeedItems] = useState<FeedItem[]>([]);
  const [feedScrollOffset, setFeedScrollOffset] = useState(0);
  const feedAutoScroll = useRef(true);
  const [feedExpandedItems, setFeedExpandedItems] = useState<Set<string>>(new Set());
  const [feedSelectedIndex, setFeedSelectedIndex] = useState(0);
  const feedIdCounter = useRef(0);

  // Completion/error info for RunScreen
  const [lastFinalUpdate, setLastFinalUpdate] = useState<import('./lib/types.js').PipelineUpdate | undefined>(undefined);
  const [lastErrorInfo, setLastErrorInfo] = useState<RunScreenErrorInfo | undefined>(undefined);

  const boardRows = useMemo(() => {
    const now = Date.now();
    return [...segments.values()]
      .sort((a, b) => a.id - b.id)
      .map((segment): BoardRowModel => ({
        segmentId: segment.id,
        title: segment.title,
        state: segment.failed
          ? 'failed'
          : segment.done
            ? 'done'
            : segment.latestWarning
              ? 'warning'
              : segment.updatedAt
                ? 'live'
                : 'queued',
        statusPipState: segment.failed
          ? 'failed'
          : segment.done
            ? 'done'
            : segment.latestWarning
              ? 'warning'
              : segment.updatedAt
                ? 'live'
                : 'queued',
        currentAction: renderSingleLineBlock(segment.currentTask ?? segment.prettyPhase, termWidth < 96 ? 28 : 42),
        primarySummary: renderSingleLineBlock(
          [
            segment.title ? `S${segment.id} ${segment.title}` : `S${segment.id}`,
            renderSingleLineBlock(segment.currentTask ?? segment.prettyPhase, termWidth < 96 ? 24 : 38),
          ].filter(Boolean).join(' · '),
          termWidth < 96 ? 56 : 88,
        ),
        secondarySummary: [
          segment.liveThinking
            ? `${segment.latestReasoningKind === 'raw_reasoning' ? 'reasoning' : segment.latestReasoningKind === 'inferred_reasoning' ? 'inference' : 'status'} ${renderSingleLineBlock(segment.liveThinking, termWidth < 96 ? 26 : 40)}`
            : undefined,
          compactToolPreview(segment, termWidth),
        ].filter(Boolean).join(' · ') || undefined,
        reasoningLabel: segment.latestReasoningKind === 'raw_reasoning' ? 'Reasoning' : segment.latestReasoningKind === 'inferred_reasoning' ? 'Inference' : undefined,
        reasoningPreview: segment.liveThinking ? renderSingleLineBlock(segment.liveThinking, termWidth < 100 ? 26 : 36) : undefined,
        toolPreview: compactToolPreview(segment, termWidth),
        codePreview: compactCodePreview(segment.liveCode ?? segmentCodes.get(segment.id), termHeight < 28 ? 2 : 4),
        selectedReasoningPreview: segment.liveThinking ? renderSingleLineBlock(segment.liveThinking, termWidth < 96 ? 140 : 220) : undefined,
        selectedCodePreview: compactCodePreview(segment.liveCode ?? segmentCodes.get(segment.id), termHeight < 28 ? 3 : 5),
        selectedToolPreview: segment.lastToolResult?.output
          ? buildToolPreview(segment.lastToolResult.name, segment.lastToolResult.output)
          : segment.lastToolCall
            ? formatToolCall(segment.lastToolCall.name, segment.lastToolCall.params)
            : undefined,
        activityDots: activityDotsForSegment(segment),
        updatedAgo: relativeAge(segment.updatedAt, now),
        lastUpdatedAt: segment.updatedAt,
        isExpandable: Boolean(segment.liveThinking || segment.liveCode || segment.lastToolResult || segment.lastToolCall || segment.latestCodeSummary),
      }));
  }, [segments, segmentCodes, termHeight, termWidth]);
  const boardWindowRows = Math.max(4, termHeight < 28 ? termHeight - 10 : termHeight - 12);

  const setCurrentStageTracked = (next: StageName | null) => {
    currentStageRef.current = next;
    setCurrentStage(next);
  };
  const setStageStartTimeTracked = (next: number) => {
    stageStartTimeRef.current = next;
    setStageStartTime(next);
  };
  const setStatusDetailTracked = (next: string) => {
    statusDetailRef.current = next;
    setStatusDetail(next);
  };
  const setSegmentsTracked = (updater: (prev: Map<number, SegmentState>) => Map<number, SegmentState>) => {
    setSegments(prev => {
      const next = updater(prev);
      segmentsRef.current = next;
      return next;
    });
  };

  const addActivity = (line: Omit<ActivityLine, 'id'>) => {
    const id = `act-${activityIdCounter.current++}`;
    const safeText = coerceText(line.text, '(no status)');
    const safeDetail = line.detail === undefined ? undefined : coerceText(line.detail);
    const mappedKind: ActivityKind = line.kind ?? line.type ?? 'status';
    const groupKey = line.groupKey ?? `${mappedKind}:${line.segmentId ?? 'global'}:${activityPrefix(safeText)}`;
    let eventRecord: RunEventRecord | undefined = line.event;
    if (!eventRecord) {
      eventRecord = addRunEvent({
        kind: 'activity',
        message: safeText,
        stage: currentStageRef.current,
        segment_id: line.segmentId,
        detail: safeDetail,
        source: mappedKind === 'thinking'
          ? line.reasoningKind === 'raw_reasoning' ? 'provider_stream' : 'ui_derived'
          : mappedKind === 'tool_call' || mappedKind === 'tool_result'
            ? 'tool_runtime'
            : 'pipeline_status',
        reasoning: mappedKind === 'thinking' && line.reasoningKind
          ? { kind: line.reasoningKind, text: safeText }
          : undefined,
        data: {
          activity_kind: mappedKind,
          group_key: groupKey,
          group: line.group,
          severity: line.severity,
        },
      });
    }
    setActivityLines(prev => {
      // Keep a rolling window of last 90 lines (collapsed later in StatusBar).
      const next = [...prev, {
        id,
        ...line,
        text: safeText,
        detail: safeDetail,
        kind: mappedKind,
        groupKey,
        eventId: eventRecord ? eventIdFor(eventRecord) : line.eventId,
        event: eventRecord,
      }];
      return next.length > 90 ? next.slice(-90) : next;
    });
    return eventRecord;
  };

  // ── Feed item builder ────────────────────────────────────────
  const addFeedItem = useCallback((item: FeedItemInput) => {
    const id = `feed-${feedIdCounter.current++}`;
    setFeedItems(prev => [...prev, { ...item, id } as FeedItem]);
    if (feedAutoScroll.current) {
      setFeedScrollOffset(Infinity); // clamped by StreamingFeed
    }
  }, []);

  // Track previous segment phases to only log on phase transitions
  const prevSegPhases = useRef<Map<number, string>>(new Map());

  const isRunning = screen === 'running' && currentStage !== null && currentStage !== 'done';
  const elapsed = useElapsed(isRunning);

  // Stage-based fallback estimate (used until segment totals are known).
  const stageEstimatePct = (() => {
    if (!currentStage || currentStage === 'done') return 100;
    switch (currentStage) {
      case 'plan':        return 5;
      case 'tts':         return 20;
      case 'code':        return 35;
      case 'code_retry':  return 55;
      case 'verify':      return 65;
      case 'render':      return 75;
      case 'timing':      return 85;
      case 'concat':      return 90;
      case 'subtitles':   return 97;
      case 'overlay':     return 95;
      default:            return 0;
    }
  })();
  const stageSegmentsTotal = totalSegments;
  const segmentsCompleted = [...segments.values()].filter(s => s.done || s.failed).length;
  const waitingForFirstSegmentUpdate = currentStage === 'pipeline' && stageSegmentsTotal > 0 && segments.size === 0;
  const stageProgressPct = stageSegmentsTotal > 0
    ? Math.round((segmentsCompleted / stageSegmentsTotal) * 100)
    : 0;
  const progressMode: ProgressMode = stageSegmentsTotal > 0 ? 'determinate' : 'indeterminate';
  const progressPct = progressMode === 'determinate' ? stageProgressPct : stageEstimatePct;
  const runtimeHintText = waitingForFirstSegmentUpdate
    ? `Queued ${stageSegmentsTotal} segment${stageSegmentsTotal === 1 ? '' : 's'}; waiting for the first live worker update from TTS or code generation.`
    : undefined;

  // ── Double Ctrl+C to exit (Claude Code style) ──────────────
  const [ctrlCPending, setCtrlCPending] = useState(false);
  const ctrlCTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inlineMsgTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Keyboard shortcut state ─────────────────────────────────
  const [showHelp, setShowHelp] = useState(false);
  const [verboseManualOverride, setVerboseManualOverride] = useState<boolean | null>(null);
  const verboseLive = resolveEffectiveVerbose(termWidth, verboseManualOverride);
  const verboseLiveRef = useRef(verboseLive);
  useEffect(() => { verboseLiveRef.current = verboseLive; }, [verboseLive]);
  const applyVerboseMode = useCallback((next: boolean) => {
    setVerboseManualOverride(next);
    setVerboseMode(next);
  }, [setVerboseMode]);
  const toggleVerboseMode = useCallback(() => {
    const current = verboseManualOverride ?? verboseLiveRef.current;
    applyVerboseMode(!current);
  }, [applyVerboseMode, verboseManualOverride]);
  useEffect(() => {
    if (ctxVerboseMode !== verboseLive) {
      setVerboseMode(verboseLive);
    }
  }, [ctxVerboseMode, setVerboseMode, verboseLive]);
  useEffect(() => { currentStageRef.current = currentStage; }, [currentStage]);
  useEffect(() => { stageStartTimeRef.current = stageStartTime; }, [stageStartTime]);
  useEffect(() => { statusDetailRef.current = statusDetail; }, [statusDetail]);
  useEffect(() => { segmentsRef.current = segments; }, [segments]);
  useEffect(() => {
    if (feedItems.length === 0) {
      setFeedSelectedIndex(0);
      return;
    }
    setFeedSelectedIndex(prev => Math.max(0, Math.min(prev, feedItems.length - 1)));
  }, [feedItems.length]);
  // Board follow-mode: auto-select the most active segment
  useEffect(() => {
    if (boardRows.length === 0) {
      setBoardSelectedSegmentId(undefined);
      setBoardScrollOffset(0);
      return;
    }
    if (boardFollowMode) {
      const live = [...boardRows]
        .sort((a, b) => {
          const stateRank = (row: BoardRowModel) => row.state === 'live' ? 4 : row.state === 'warning' ? 3 : row.state === 'queued' ? 2 : row.state === 'done' ? 1 : 0;
          const rankGap = stateRank(b) - stateRank(a);
          if (rankGap !== 0) return rankGap;
          return (b.lastUpdatedAt ?? 0) - (a.lastUpdatedAt ?? 0);
        })[0];
      if (live) setBoardSelectedSegmentId(live.segmentId);
      const selectedIndex = live ? boardRows.findIndex(row => row.segmentId === live.segmentId) : 0;
      setBoardScrollOffset(Math.max(0, Math.min(selectedIndex, Math.max(0, boardRows.length - boardWindowRows))));
      return;
    }
    setBoardSelectedSegmentId(prev => {
      if (prev !== undefined && boardRows.some(row => row.segmentId === prev)) return prev;
      return boardRows[0]?.segmentId;
    });
    setBoardScrollOffset(prev => Math.max(0, Math.min(prev, Math.max(0, boardRows.length - boardWindowRows))));
  }, [boardRows, boardFollowMode, boardWindowRows]);

  // Inline messages (e.g. from slash command confirmations)
  const [inlineMessage, setInlineMessage] = useState<{text: string; color?: string} | null>(null);

  // Prompt pre-fill (e.g. from /surprise)
  const [promptPrefill, setPromptPrefill] = useState<string | undefined>(undefined);

  // Stage tracking for footer
  const [currentStageForFooter, setCurrentStageForFooter] = useState<string | null>(null);

  // ── Hooks: fire SessionStart on mount, SessionEnd on unmount ──────
  const { settings } = useAppContext();
  // H2: Use a ref so the SessionEnd cleanup always reads the latest settings value
  const settingsRef = useRef(settings);
  useEffect(() => { settingsRef.current = settings; }, [settings]);

  useEffect(() => {
    const s = settingsRef.current;
    if (!s.disableAllHooks) {
      runHooks('SessionStart', { concept: initialConcept ?? '' }, s.hooks, s.disableAllHooks);
    }
    return () => {
      const s2 = settingsRef.current;
      if (!s2.disableAllHooks) {
        runHooks('SessionEnd', {}, s2.hooks, s2.disableAllHooks);
      }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const escPressTime = useRef<number>(0);

  const syncBoardViewport = useCallback((nextIndex: number) => {
    if (boardRows.length === 0) return;
    const clamped = Math.max(0, Math.min(nextIndex, boardRows.length - 1));
    const target = boardRows[clamped];
    setBoardSelectedSegmentId(target?.segmentId);
    setBoardFollowMode(false);
    setBoardScrollOffset(prev => {
      if (clamped < prev) return clamped;
      const pageEnd = prev + boardWindowRows - 1;
      if (clamped > pageEnd) return Math.max(0, clamped - boardWindowRows + 1);
      return prev;
    });
  }, [boardRows, boardWindowRows]);

  useInput((_input, key) => {
    // Ctrl+C — cancel pipeline / exit
    if (key.ctrl && _input === 'c') {
      if (screen === 'running' && currentStage && currentStage !== 'done') {
        // Single Ctrl+C during run — prompt for confirmation
        if (ctrlCPending) {
          pipeline.kill();
          exit();
          process.exit(0);
        } else {
          setCtrlCPending(true);
          if (ctrlCTimer.current) clearTimeout(ctrlCTimer.current);
          ctrlCTimer.current = setTimeout(() => setCtrlCPending(false), 2000);
        }
      } else {
        if (ctrlCPending) {
          exit();
          process.exit(0);
        } else {
          setCtrlCPending(true);
          if (ctrlCTimer.current) clearTimeout(ctrlCTimer.current);
          ctrlCTimer.current = setTimeout(() => setCtrlCPending(false), 2000);
        }
      }
      return;
    }

    // Ctrl+D — clean exit
    if (key.ctrl && _input === 'd') {
      pipeline.kill();
      exit();
      process.exit(0);
      return;
    }

    // Ctrl+L — clear screen (preserve log history)
    if (key.ctrl && _input === 'l') {
      process.stdout.write('\x1b[2J\x1b[H');
      return;
    }

    // Ctrl+O — toggle verbose mode
    if (key.ctrl && _input === 'o') {
      toggleVerboseMode();
      return;
    }

    // Shift+Tab / Alt+M — cycle permission modes
    if (key.shift && key.tab) {
      cyclePermissionMode();
      return;
    }

    // Alt+T — toggle thinking visible
    if (key.meta && _input === 't') {
      setThinkingVisible(v => !v);
      return;
    }

    // Alt+O — toggle fast/lite mode (quality low ↔ high)
    if (key.meta && _input === 'o') {
      setQuality(ctxQuality === 'low' ? 'high' : 'low');
      return;
    }

    // Alt+P — cycle provider profile openai-default ↔ anthropic-legacy
    if (key.meta && _input === 'p') {
      const next = currentModel === 'anthropic-legacy' ? 'openai-default' : 'anthropic-legacy';
      setCurrentModel(next);
      return;
    }

    // Esc+Esc — rewind to last checkpoint (quick double-Esc)
    // Important: ignore arrow-key escape sequences so child components
    // (like Questionnaire) can use left/right navigation reliably.
    if (key.escape && !key.upArrow && !key.downArrow && !key.leftArrow && !key.rightArrow) {
      const now = Date.now();
      if (now - escPressTime.current < 500) {
        // C6: Double Esc navigates back to input from ANY non-running screen
        if (screen !== 'input' && screen !== 'running') {
          setScreen('input');
        }
      }
      escPressTime.current = now;
      return;
    }

    const isRunScreen = screen === 'running';
    if (isRunScreen) {
      // ? — toggle help overlay
      if (_input === '?') {
        setShowHelp(h => !h);
        return;
      }

      // Segment navigation (↑↓ / j/k)
      const currentIndex = boardSelectedSegmentId !== undefined
        ? boardRows.findIndex(row => row.segmentId === boardSelectedSegmentId)
        : 0;
      const safeIndex = currentIndex >= 0 ? currentIndex : 0;
      if (key.downArrow || _input === 'j') {
        syncBoardViewport(safeIndex + 1);
        return;
      }
      if (key.upArrow || _input === 'k') {
        syncBoardViewport(safeIndex - 1);
        return;
      }
      if (_input === 'g' || _input === 'G') {
        setBoardFollowMode(true);
        return;
      }
    }

    // Navigate back from secondary screens with Esc (handled per-screen via useInput in child components)
  });

  // Keep run markers concise to avoid duplicating banner metadata.
  const addRunMarker = (c: string, isResume = false) => {
    const prefix = isResume ? 'Resuming run' : 'Starting run';
    resetRunEventJournal(`${prefix}: ${c}`);
    addLog({
      type: 'header',
      text: `${prefix}: ${c}`,
    });
  };

  // Start pipeline when concept is set (from CLI arg) or resuming
  useEffect(() => {
    if (resumeDir) {
      addRunMarker('project from: ' + resumeDir, true);
      pipeline.start({ concept: 'resume', max_retries: maxRetries, is_lite: isLite, skip_audio: skipAudio, resume_dir: resumeDir, render_timeout: renderTimeout, tts_timeout: ttsTimeout, system_prompt_prefix: buildSystemPrompt(), max_turns: maxTurns, model: currentModel });
    } else if (initialConcept) {
      addRunMarker(initialConcept);
      pipeline.start({ concept: initialConcept, max_retries: maxRetries, is_lite: isLite, skip_audio: skipAudio, render_timeout: renderTimeout, tts_timeout: ttsTimeout, system_prompt_prefix: buildSystemPrompt(), max_turns: maxTurns, model: currentModel });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // H9: Build the effective system_prompt_prefix by combining PAPER2MANIM.md memory with the CLI --system-prompt flag
  const buildSystemPrompt = () => {
    const memory = loadMemory();
    const parts = [memory, systemPrompt].filter(Boolean);
    return parts.join('\n\n---\n\n') || undefined;
  };

  // Handle concept submission
  const handleConceptSubmit = (c: string) => {
    setConcept(c);
    addRunMarker(c);
    pushHistory(c);
    updateSession({ concept: c });
    process.stdout.write(`\x1b]0;paper2manim: ${c.slice(0, 50)}\x07`);
    pipeline.start({ concept: c, max_retries: maxRetries, is_lite: isLite, skip_audio: skipAudio, render_timeout: renderTimeout, tts_timeout: ttsTimeout, system_prompt_prefix: buildSystemPrompt(), max_turns: maxTurns, model: currentModel });
    setScreen('running');
    setRunState('active');
    setLastFinalUpdate(undefined);
    setLastErrorInfo(undefined);
    setBoardSelectedSegmentId(undefined);
    setBoardScrollOffset(0);
    setBoardFollowMode(true);
  };

  // Handle questionnaire state
  useEffect(() => {
    if (pipeline.status === 'questionnaire' && pipeline.questions.length > 0) {
      setScreen('questionnaire');
    }
  }, [pipeline.status, pipeline.questions]);

  const handleQuestionnaireComplete = (answers: Record<string, string>) => {
    pipeline.answerQuestions(answers);
    setScreen('running');
    setRunState('active');
    setLastFinalUpdate(undefined);
    setLastErrorInfo(undefined);
    setBoardSelectedSegmentId(undefined);
    setBoardScrollOffset(0);
    setBoardFollowMode(true);

    // iTerm2 taskbar bounce — draw attention when pipeline starts
    process.stdout.write('\x1b]1337;RequestAttention=yes\x07');
  };

  // ── Process pipeline updates ──────────────────────────────────
  const PIPELINE_SUBSTAGES = new Set<StageName>(['tts', 'code', 'render', 'stitch']);
  const processedIdx = useRef(0);
  useEffect(() => {
    if (pipeline.updates.length === 0) return;

    // Process all updates since last render, not just the latest
    const unprocessed = pipeline.updates.slice(processedIdx.current);
    processedIdx.current = pipeline.updates.length;
    let batchStage = currentStageRef.current;
    let batchStageStartTime = stageStartTimeRef.current;
    let batchStatusDetail = statusDetailRef.current;

    for (const latest of unprocessed) {
    const stage = latest.stage as StageName;
    if (latest.project_dir) {
      switchRunEventPathToProject(latest.project_dir);
    }

    // Track total segments
    if (latest.num_segments) {
      setTotalSegments(latest.num_segments);
    }
    if (latest.storyboard) {
      const titles = extractStoryboardTitles(latest.storyboard);
      if (titles.size > 0) {
        setSegmentsTracked(prev => {
          const next = new Map(prev);
          for (const [segId, title] of titles.entries()) {
            const existing = next.get(segId);
            next.set(segId, existing ? { ...existing, title } : {
              id: segId,
              title,
              phase: 'queued',
              prettyPhase: 'Queued',
              attempt: 1,
              done: false,
              failed: false,
              startedAt: Date.now(),
            });
          }
          return next;
        });
      }
    }

    // ── Stage transitions ───────────────────────────────────────
    // Pipeline sub-stages (tts, code, render, stitch) run interleaved
    // during the parallel pipeline. Don't treat them as full stage
    // transitions — that would clear segment state and spam headers.
    const isPipelineSubstage = PIPELINE_SUBSTAGES.has(stage) &&
      (batchStage === 'pipeline' || (batchStage != null && PIPELINE_SUBSTAGES.has(batchStage)));

    if (stage !== batchStage && stage !== 'done' && !isPipelineSubstage) {
      // Complete the previous stage → add panel to log
      if (batchStage && batchStage !== 'done') {
        const stageElapsed = (Date.now() - batchStageStartTime) / 1000;
        const config = getStageConfig(themeColors)[batchStage];
        const completed: CompletedStage = {
          name: batchStage,
          summary: batchStatusDetail || `${config?.label ?? batchStage} complete`,
          elapsed: stageElapsed,
          status: 'ok',
        };
        setCompletedStages(prev => { const next = [...prev, completed]; completedStagesRef.current = next; return next; });
        addLog({ type: 'stage-complete', stage: completed });
        addRunEvent({
          kind: 'stage_complete',
          message: completed.summary,
          stage: batchStage,
          source: 'pipeline_status',
          data: {
            status: completed.status,
            elapsed_seconds: stageElapsed,
            error: completed.error,
          },
        });
      }

      // New stage header
      const now = Date.now();
      setCurrentStageTracked(stage);
      setStageStartTimeTracked(now);
      setStatusDetailTracked('');
      batchStage = stage;
      batchStageStartTime = now;
      batchStatusDetail = '';
      setActivityLines([]);  // Clear activity stream on stage transition
      if (stage === 'plan' || stage === 'pipeline') {
        segmentCodeCacheRef.current = new Map();
        setSegmentCodes(new Map());
        setCodeRecentChanges(new Map());
      }
      addRunEvent({
        kind: 'stage_transition',
        message: `Entered ${stage}`,
        stage,
        source: 'pipeline_status',
      });
      // Feed: new stage header
      addFeedItem({ type: 'stage_header', stage, status: 'active' });

      if (stage === 'pipeline') {
        setSegmentsTracked(() => new Map());
        prevSegPhases.current = new Map();
      }
      // code_retry reuses existing segment state — don't clear
    }

    // ── Intermediate status updates ─────────────────────────────
    // Show as regular status unless it's a segment-specific update.
    // Feed: only show meaningful status lines (containing data, not chatter).
    const hasSegmentId = latest.segment_id !== undefined;
    const isSegmentStage = PIPELINE_SUBSTAGES.has(stage) || stage === 'code_retry';
    if (latest.status && !(isSegmentStage && hasSegmentId)) {
      const cleaned = cleanStatus(latest.status);
      setStatusDetailTracked(cleaned);
      batchStatusDetail = cleaned;
      if (cleaned) {
        const reasoningKind = inferReasoningKindFromText(cleaned);
        const statusLine = {
          kind: 'status' as const,
          text: cleaned,
          group: classifyActivityGroup(cleaned),
          severity: classifyActivitySeverity(cleaned),
        };
        const event = addRunEvent({
          kind: 'status',
          message: cleaned,
          stage,
          source: 'pipeline_status',
          reasoning: reasoningKind === 'status_summary' ? undefined : { kind: reasoningKind, text: cleaned },
        });
        addActivity({ ...statusLine, event, eventId: eventIdFor(event) });
        addFeedItem({ type: 'activity', line: { ...statusLine, id: '', event, eventId: eventIdFor(event) }, event, eventId: eventIdFor(event) });
      }
    }

    // ── Tool call events for ALL stages (Claude Code-style) ─────
    if (latest.tool_call && stage !== 'code' && stage !== 'code_retry') {
      const tc = latest.tool_call;
      const displayText = formatToolCall(tc.name, tc.params);
      const event = addRunEvent({
        kind: 'activity',
        message: displayText,
        stage,
        source: 'tool_runtime',
        tool: { name: tc.name, params: tc.params },
      });
      const toolLine = {
        kind: 'tool_call' as const,
        text: displayText,
        group: classifyActivityGroup(displayText),
        severity: classifyActivitySeverity(displayText),
      };
      addActivity({ ...toolLine, event, eventId: eventIdFor(event) });
      addFeedItem({ type: 'activity', line: { ...toolLine, id: '', event, eventId: eventIdFor(event) }, event, eventId: eventIdFor(event) });
    }
    if (latest.tool_result && stage !== 'code' && stage !== 'code_retry') {
      const out = latest.tool_result.output?.trim() || '(no output)';
      const preview = buildToolPreview(latest.tool_result.name, out);
      const event = addRunEvent({
        kind: 'activity',
        message: preview,
        stage,
        source: 'tool_runtime',
        detail: out,
        tool: {
          name: latest.tool_result.name,
          output_preview: summarizeToolOutput(out),
        },
      });
      const resultLine = {
        kind: 'tool_result' as const,
        text: preview,
        detail: out,
        group: 'done' as const,
        severity: classifyActivitySeverity(out),
      };
      addActivity({ ...resultLine, event, eventId: eventIdFor(event) });
      addFeedItem({ type: 'activity', line: { ...resultLine, id: '', event, eventId: eventIdFor(event) }, event, eventId: eventIdFor(event) });
    }

    if (latest.thinking !== undefined && stage !== 'code' && stage !== 'code_retry') {
      if (latest.thinking) {
        const thinkText = typeof latest.thinking === 'string'
          ? latest.thinking.slice(0, 120)
          : 'Reasoning...';
        const reasoningKind: ReasoningKind = latest.stream_event?.channel === 'thinking' ? 'raw_reasoning' : 'inferred_reasoning';
        const event = addRunEvent({
          kind: 'activity',
          message: `${reasoningLabel(reasoningKind)}: ${thinkText}`,
          stage,
          source: reasoningKind === 'raw_reasoning' ? 'provider_stream' : 'ui_derived',
          channel: latest.stream_event?.channel,
          reasoning: { kind: reasoningKind, text: thinkText },
        });
        const thinkLine = { kind: 'thinking' as const, text: thinkText, group: 'checking' as const, reasoningKind };
        addActivity({ ...thinkLine, event, eventId: eventIdFor(event) });
        addFeedItem({ type: 'activity', line: { ...thinkLine, id: '', event, eventId: eventIdFor(event) }, event, eventId: eventIdFor(event) });
      }
    }

    // ── Segment-level updates during parallel pipeline ──────────
    if ((isSegmentStage) && latest.segment_id !== undefined) {
      const segId = latest.segment_id;
      const phase = latest.segment_phase ?? 'running';

      // Include sub-stage label for non-code stages
      const subLabel: Record<string, string> = {
        tts: 'TTS', render: 'Render', stitch: 'Stitch',
      };
      const prefix = subLabel[stage] ? `${subLabel[stage]} ` : '';
      const prettyPhase = `${prefix}${segmentPhaseLabels[phase] ?? phase}`;

      // Track attempt number
      const attemptMatch = latest.status?.match(/Attempt (\d+)\//);
      let segElapsed: number | undefined;

      setSegmentsTracked(prev => {
        const next = new Map(prev);
        const existing = next.get(segId);
        let attempt = existing?.attempt ?? 1;
        if (attemptMatch) attempt = parseInt(attemptMatch[1]!, 10);

        const now = Date.now();
        const segState = reduceSegmentUpdate(existing ? { ...existing, id: segId } : { id: segId, phase, prettyPhase, attempt, done: false, failed: false }, {
          stage,
          phase,
          prettyPhase,
          status: latest.status ? cleanStatus(latest.status) : undefined,
          error: latest.error,
          now,
          attempt,
          thinking: latest.thinking,
          toolCall: latest.tool_call,
          toolResult: latest.tool_result,
          streamEvent: latest.stream_event,
        });
        const startedAt = segState.startedAt ?? now;
        if (phase === 'done' || phase === 'failed') {
          segElapsed = Math.max(0, (now - startedAt) / 1000);
        }

        next.set(segId, segState);
        return next;
      });

      // Log only completions/failures — phase transitions are shown
      // in the live status bar instead of cluttering the scroll log.
      const prevPhase = prevSegPhases.current.get(segId);
      if (phase !== prevPhase) {
        prevSegPhases.current.set(segId, phase);
        addRunEvent({
          kind: phase === 'done' || phase === 'failed' ? 'segment_terminal' : 'segment_phase',
          message: `Segment ${segId}: ${prettyPhase}`,
          stage,
          segment_id: segId,
          source: 'pipeline_status',
          worker_role: inferWorkerRole(stage, phase, latest.status),
          data: {
            previous_phase: prevPhase,
            phase,
            attempt: attemptMatch ? parseInt(attemptMatch[1]!, 10) : 1,
            status: latest.status,
          },
        });

        const attemptNum = attemptMatch ? parseInt(attemptMatch[1]!, 10) : 1;
        const attemptStr = attemptNum > 1 ? ` on attempt ${attemptNum}` : '';

        // Feed: segment header — only show completions/failures (not every "running" transition)
        const segStatus = phase === 'done' ? 'done' as const : phase === 'failed' ? 'failed' as const : 'active' as const;
        if (phase === 'done' || phase === 'failed' || runState === 'active' || verboseLiveRef.current) {
          addFeedItem({
            type: 'segment_header',
            segmentId: segId,
            label: `Segment ${segId}: ${prettyPhase}`,
            status: segStatus,
            elapsed: segElapsed,
            attempt: attemptNum,
          });
        }

        if (phase === 'done') {
          const elapsedSecs = segElapsed ?? 0;
          const timeStr = elapsedSecs > 0 ? ` in ${formatDuration(elapsedSecs)}` : '';
          addLog({
            type: 'segment',
            text: `Segment ${segId} completed${attemptStr}${timeStr}`,
            icon: 'OK',
            color: themeColors.success,
            bold: true,
          });
        } else if (phase === 'failed') {
          const elapsedSecs = segElapsed ?? 0;
          const timeStr = elapsedSecs > 0 ? ` after ${formatDuration(elapsedSecs)}` : '';
          addLog({
            type: 'segment',
            text: `Segment ${segId} FAILED${attemptStr}${timeStr}`,
            icon: 'ERR',
            color: themeColors.error,
            bold: true,
          });
          // Terminal bell on segment failure
          process.stdout.write('\x07');
        }
        // In verbose mode, log all phase transitions (not just done/failed)
        else if (verboseLiveRef.current) {
          addLog({
            type: 'log',
            text: `  Seg ${segId}: ${prettyPhase}${attemptStr ? ` (attempt ${attemptNum})` : ''}`,
            color: themeColors.dim,
          });
        }
      }

      // Log tool calls to scroll region (Claude Code style — ⎿ marker)
      if (latest.tool_call) {
        const tc = latest.tool_call;
        const displayText = formatToolCall(tc.name, tc.params);
        const event = addRunEvent({
          kind: 'activity',
          message: `Seg ${segId}: ${displayText}`,
          stage,
          segment_id: segId,
          source: 'tool_runtime',
          worker_role: inferWorkerRole(stage, phase, latest.status),
          tool: { name: tc.name, params: tc.params },
        });
        const segToolLine = {
          kind: 'tool_call' as const,
          text: `Seg ${segId}: ${displayText}`,
          segmentId: segId,
          group: classifyActivityGroup(displayText),
          severity: classifyActivitySeverity(displayText),
        };
        addActivity({ ...segToolLine, event, eventId: eventIdFor(event) });
        addFeedItem({ type: 'activity', line: { ...segToolLine, id: '', event, eventId: eventIdFor(event) }, segmentId: segId, event, eventId: eventIdFor(event) });
      }
      if (latest.tool_result) {
        const out = latest.tool_result.output?.trim() || '(no output)';
        const preview = buildToolPreview(latest.tool_result.name, out);
        const event = addRunEvent({
          kind: 'activity',
          message: `Seg ${segId}: ${preview}`,
          stage,
          segment_id: segId,
          source: 'tool_runtime',
          worker_role: inferWorkerRole(stage, phase, latest.status),
          detail: out,
          tool: {
            name: latest.tool_result.name,
            output_preview: summarizeToolOutput(out),
          },
        });
        const segResultLine = {
          kind: 'tool_result' as const,
          text: `Seg ${segId}: ${preview}`,
          detail: out,
          segmentId: segId,
          group: 'done' as const,
          severity: classifyActivitySeverity(out),
        };
        addActivity({ ...segResultLine, event, eventId: eventIdFor(event) });
        addFeedItem({ type: 'activity', line: { ...segResultLine, id: '', event, eventId: eventIdFor(event) }, segmentId: segId, event, eventId: eventIdFor(event) });
      }

      if (latest.thinking !== undefined) {
        if (latest.thinking) {
          const thinkText = typeof latest.thinking === 'string'
            ? `Seg ${segId}: ${latest.thinking.slice(0, 100)}`
            : `Seg ${segId}: Reasoning...`;
          const reasoningKind: ReasoningKind = latest.stream_event?.channel === 'thinking' ? 'raw_reasoning' : 'inferred_reasoning';
          const event = addRunEvent({
            kind: 'activity',
            message: `${reasoningLabel(reasoningKind)}: ${thinkText}`,
            stage,
            segment_id: segId,
            source: reasoningKind === 'raw_reasoning' ? 'provider_stream' : 'ui_derived',
            worker_role: inferWorkerRole(stage, phase, latest.status),
            channel: latest.stream_event?.channel,
            reasoning: { kind: reasoningKind, text: thinkText },
          });
          const segThinkLine = { kind: 'thinking' as const, text: thinkText, segmentId: segId, group: 'checking' as const, reasoningKind };
          addActivity({ ...segThinkLine, event, eventId: eventIdFor(event) });
          addFeedItem({ type: 'activity', line: { ...segThinkLine, id: '', event, eventId: eventIdFor(event) }, segmentId: segId, event, eventId: eventIdFor(event) });
        }
      }

      // Update status bar detail
      if (latest.status) {
        const cleaned = cleanStatus(latest.status);
        setStatusDetailTracked(cleaned);
        batchStatusDetail = cleaned;
      }

      if ((stage === 'code' || stage === 'code_retry') && typeof latest.code === 'string' && latest.code.length > 0) {
        const prevCode = segmentCodeCacheRef.current.get(segId) ?? '';
        const nextCode = latest.code;
        if (prevCode !== nextCode) {
          const diff = buildCompactUnifiedDiff(prevCode, nextCode, {
            maxVisibleLines: termWidth < 100 ? 10 : 16,
            contextLines: termWidth < 100 ? 0 : 1,
          });
          if (diff.hasChanges) {
            const diffLine = {
              kind: 'diff' as const,
              segmentId: segId,
              text: `Seg ${segId} code changes (${diff.summary})`,
              detail: diff.lines.join('\n'),
              group: 'doing' as const,
              severity: 'normal' as const,
              groupKey: `diff:${segId}:${diff.dedupeKey}`,
            };
            const diffEvent = addRunEvent({
              kind: 'activity',
              message: diffLine.text,
              stage,
              segment_id: segId,
              source: 'ui_derived',
              worker_role: inferWorkerRole(stage, phase, latest.status),
              channel: 'code',
              detail: diffLine.detail,
            });
            addActivity({ ...diffLine, event: diffEvent, eventId: eventIdFor(diffEvent) });
            addFeedItem({ type: 'activity', line: { ...diffLine, id: '', event: diffEvent, eventId: eventIdFor(diffEvent) }, segmentId: segId, event: diffEvent, eventId: eventIdFor(diffEvent) });
            setSegmentsTracked(prev => {
              const next = new Map(prev);
              const existing = next.get(segId);
              if (existing) {
                next.set(segId, {
                  ...existing,
                  latestCodeSummary: diff.summary,
                  trace: appendTrace(existing.trace, makeTraceEntry('code', `${diff.summary}`, existing.currentWorker, Date.now())),
                });
              }
              return next;
            });
          }
          segmentCodeCacheRef.current.set(segId, nextCode);

          // Update segmentCodes state
          setSegmentCodes(prev => {
            const next = new Map(prev);
            next.set(segId, nextCode);
            return next;
          });

          // Code snapshot for the feed (first time only — subsequent updates show as diffs)
          if (!prevCode) {
            const lineCount = nextCode.split('\n').length;
            addFeedItem({
              type: 'code_snapshot',
              segmentId: segId,
              code: nextCode,
              summary: `Seg ${segId}: initial code (${lineCount} lines)`,
            });
            setSegmentsTracked(prev => {
              const next = new Map(prev);
              const existing = next.get(segId);
              if (existing) {
                next.set(segId, {
                  ...existing,
                  latestCodeSummary: `initial draft (${lineCount} lines)`,
                  trace: appendTrace(existing.trace, makeTraceEntry('code', `initial draft (${lineCount} lines)`, existing.currentWorker, Date.now())),
                });
              }
              return next;
            });
          }

          // Track recently changed lines for gutter markers
          const prevLines = prevCode.split('\n');
          const nextLines = nextCode.split('\n');
          const changedLineNums = new Set<number>();
          for (let i = 0; i < nextLines.length; i++) {
            if (i >= prevLines.length || prevLines[i] !== nextLines[i]) {
              changedLineNums.add(i + 1); // 1-indexed
            }
          }
          if (changedLineNums.size > 0) {
            setCodeRecentChanges(prev => {
              const next = new Map(prev);
              const existing = next.get(segId) ?? new Set<number>();
              for (const ln of changedLineNums) existing.add(ln);
              next.set(segId, existing);
              return next;
            });
            // Clear change markers after 3 seconds
            setTimeout(() => {
              setCodeRecentChanges(prev => {
                const next = new Map(prev);
                const existing = next.get(segId);
                if (existing) {
                  for (const ln of changedLineNums) existing.delete(ln);
                  if (existing.size === 0) next.delete(segId);
                  else next.set(segId, existing);
                }
                return next;
              });
            }, 3000);
          }

        }
      }

      if ((stage === 'code' || stage === 'code_retry') && latest.stream_event?.channel === 'code' && latest.stream_event.snapshot) {
        const snapshot = latest.stream_event.snapshot;
        segmentCodeCacheRef.current.set(segId, snapshot);
        setSegmentCodes(prev => {
          const next = new Map(prev);
          next.set(segId, snapshot);
          return next;
        });
      }
    } else if ((stage === 'code' || stage === 'code_retry') && latest.status) {
      // Code stage summary updates (not segment-specific)
      const cleaned = cleanStatus(latest.status);
      setStatusDetailTracked(cleaned);
      batchStatusDetail = cleaned;
    }

    // ── Final update ────────────────────────────────────────────
    if (latest.final) {
      if (batchStage && batchStage !== 'done') {
        const stageElapsed = (Date.now() - batchStageStartTime) / 1000;
        const completed: CompletedStage = {
          name: batchStage,
          summary: latest.status ?? 'Complete',
          elapsed: stageElapsed,
          status: latest.error ? 'failed' : 'ok',
          error: latest.error,
        };
        setCompletedStages(prev => { const next = [...prev, completed]; completedStagesRef.current = next; return next; });
        addLog({ type: 'stage-complete', stage: completed });
        addRunEvent({
          kind: 'stage_complete',
          message: completed.summary,
          stage: batchStage,
          source: 'pipeline_status',
          data: {
            status: completed.status,
            elapsed_seconds: stageElapsed,
            error: completed.error,
          },
        });
      }
      setCurrentStageTracked('done');
      batchStage = 'done';
      addRunEvent({
        kind: 'final',
        message: latest.error ? 'Run finished with error' : 'Run finished successfully',
        stage: 'done',
        source: 'pipeline_status',
        data: {
          error: latest.error,
          project_dir: latest.project_dir,
          video_path: latest.video_path,
          total_elapsed_seconds: latest.total_elapsed_seconds,
          failed_segments: latest.failed_segments?.length ?? 0,
        },
      });

      if (latest.error) {
        setRunState('error');
        setLastErrorInfo({
          message: latest.error,
          failedSegments: latest.failed_segments,
          projectDir: latest.project_dir,
          videoPath: latest.video_path,
          tokenSummary: latest.token_summary ? {
            estimated_cost_usd: latest.token_summary.estimated_cost_usd,
            total_api_calls: latest.token_summary.total_api_calls,
          } : null,
        });
        // Feed: error summary (kept for event journal)
        addFeedItem({
          type: 'error',
          message: latest.error,
          failedSegments: latest.failed_segments,
          projectDir: latest.project_dir,
          videoPath: latest.video_path,
          completedStages: [...(completedStagesRef.current ?? [])],
          tokenSummary: latest.token_summary,
        });
      } else {
        setRunState('complete');
        setLastFinalUpdate(latest);
        // Feed: completion summary (kept for event journal)
        addFeedItem({
          type: 'completion',
          finalUpdate: latest,
          completedStages: [...(completedStagesRef.current ?? [])],
        });

        // Open video in default player
        if (latest.video_path) {
          try {
            const platform = os.platform();
            if (platform === 'darwin') {
              execFileSync('open', [latest.video_path]);
            } else if (platform === 'win32') {
              execFileSync('cmd', ['/c', 'start', '', latest.video_path]);
            } else {
              execFileSync('xdg-open', [latest.video_path]);
            }
          } catch { /* ignore if player is unavailable */ }
        }
      }

      // Terminal bell + title reset
      process.stdout.write('\x07');
      process.stdout.write(latest.error ? '\x1b]0;paper2manim ✗\x07' : '\x1b]0;paper2manim ✓\x07');

      // iTerm2 taskbar bounce
      process.stdout.write('\x1b]1337;RequestAttention=yes\x07');

      // Desktop notification (cross-platform)
      const notifMsg = latest.error ? 'Pipeline failed' : 'Video generation complete!';
      try {
        if (os.platform() === 'darwin') {
          execSync(`osascript -e 'display notification "${notifMsg}" with title "paper2manim" sound name "Glass"'`);
        } else if (os.platform() === 'linux') {
          execFileSync('notify-send', ['paper2manim', notifMsg]);
        }
        // Windows: terminal bell (already sent above) is sufficient
      } catch { /* ignore if notification tool is unavailable */ }
    }
    } // end for (unprocessed)
  }, [pipeline.updates.length]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Secondary screens (settings, context, doctor, keybindings) ──
  if (screen === 'settings') {
    return (
      <Box flexDirection="column" paddingX={1}>
        <SettingsPanel onBack={() => setScreen('input')} />
        <FooterStatusLine stage={null} />
      </Box>
    );
  }

  if (screen === 'context') {
    return (
      <Box flexDirection="column" paddingX={1}>
        <ContextVisualizer onBack={() => setScreen('input')} />
        <FooterStatusLine stage={null} />
      </Box>
    );
  }

  if (screen === 'doctor') {
    return (
      <Box flexDirection="column" paddingX={1}>
        <DoctorPanel onBack={() => setScreen('input')} />
        <FooterStatusLine stage={null} />
      </Box>
    );
  }

  if (screen === 'keybindings') {
    return (
      <Box flexDirection="column" paddingX={1}>
        <KeybindingsHelpOverlay onBack={() => setScreen('input')} />
        <FooterStatusLine stage={null} />
      </Box>
    );
  }

  // ── Build AppDispatch for command handlers ──────────────────────
  const appDispatch: import('./lib/types.js').AppDispatch = {
    setScreen: (s) => setScreen(s as Screen),
    setPermissionMode: (mode) => setPermissionMode(mode),
    setVerboseMode: (v: boolean) => {
      applyVerboseMode(v);
    },
    toggleVerboseMode,
    setThinkingVisible: (v: boolean) => setThinkingVisible(v),
    setPromptColor: (color) => setPromptColor(color),
    setCurrentModel: (model) => setCurrentModel(model),
    setTheme: (theme) => updateSetting('theme', theme),
    setQuality: (q) => setQuality(q),
    startPipeline: (c) => handleConceptSubmit(c),
    resumePipeline: (dir) => {
      setConcept(dir);
      addRunMarker(dir, true);
      pipeline.start({ concept: 'resume', max_retries: maxRetries, is_lite: isLite, skip_audio: skipAudio, resume_dir: dir, render_timeout: renderTimeout, tts_timeout: ttsTimeout, system_prompt_prefix: buildSystemPrompt(), max_turns: maxTurns, model: currentModel });
      setScreen('running');
      setRunState('active');
      setLastFinalUpdate(undefined);
      setLastErrorInfo(undefined);
      setBoardSelectedSegmentId(undefined);
      setBoardScrollOffset(0);
      setBoardFollowMode(true);
    },
    retryPipeline: () => {
      const lastRunError = pipeline.finalUpdate?.error;
      const projectDir = pipeline.finalUpdate?.project_dir;
      if (!projectDir || !lastRunError) {
        if (inlineMsgTimer.current) clearTimeout(inlineMsgTimer.current);
        setInlineMessage({ text: 'Nothing to retry — no failed run in this session.', color: themeColors.error });
        inlineMsgTimer.current = setTimeout(() => setInlineMessage(null), 5000);
        return;
      }
      const collapse = collapseRunLogsForRetry(logEntries.length, activeRunLogStartRef.current);
      const visibleHistory = collapse.collapsedCount;
      if (visibleHistory > 0) {
        setCollapsedHistoryCount(prev => prev + visibleHistory);
      }
      const nextRunStart = collapse.nextActiveRunStart;
      activeRunLogStartRef.current = nextRunStart;
      setActiveRunLogStart(nextRunStart);

      // Reset stage tracking for the new run
      setCompletedStages([]);
      setSegmentsTracked(() => new Map());
      setCurrentStageTracked(null);
      setStatusDetailTracked('');
      setActivityLines([]);
      segmentCodeCacheRef.current = new Map();
      prevSegPhases.current.clear();
      processedIdx.current = 0;
      // Reset run state
      setRunState('active');
      setSegmentCodes(new Map());
      setCodeRecentChanges(new Map());
      setLastFinalUpdate(undefined);
      setLastErrorInfo(undefined);
      setBoardSelectedSegmentId(undefined);
      setBoardScrollOffset(0);
      setBoardFollowMode(true);

      addLog({
        type: 'log',
        text: `[Fixing] Retrying failed segments (${visibleHistory} prior run line${visibleHistory === 1 ? '' : 's'} collapsed)`,
        color: themeColors.warn,
      });
      addRunEvent({
        kind: 'diagnostic',
        message: 'Retry requested for failed run',
        stage: currentStageRef.current,
        source: 'ui_derived',
        data: {
          visible_history_collapsed: visibleHistory,
          project_dir: projectDir,
          last_error: lastRunError,
        },
      });
      addRunMarker(concept || projectDir, true);
      pipeline.start({ concept: concept || 'resume', max_retries: maxRetries, is_lite: isLite, skip_audio: skipAudio, resume_dir: projectDir, render_timeout: renderTimeout, tts_timeout: ttsTimeout, system_prompt_prefix: buildSystemPrompt(), max_turns: maxTurns, model: currentModel });
      setScreen('running');
    },
    compactLogs: (_instructions) => {
      setLogEntries(prev => {
        const hidden = prev.slice(0, activeRunLogStartRef.current);
        const visible = prev.slice(activeRunLogStartRef.current);
        const compactVisible = visible.slice(-5);
        const next = [...hidden, ...compactVisible];
        const nextStart = hidden.length;
        activeRunLogStartRef.current = nextStart;
        setActiveRunLogStart(nextStart);
        return next;
      });
      if (inlineMsgTimer.current) clearTimeout(inlineMsgTimer.current);
      setInlineMessage({ text: 'Log compacted.', color: themeColors.dim });
      addRunEvent({
        kind: 'diagnostic',
        message: 'UI logs compacted by user command',
        stage: currentStageRef.current,
        source: 'ui_derived',
      });
      inlineMsgTimer.current = setTimeout(() => setInlineMessage(null), 5000);
    },
    exportSession: (_filename) => {
      return exportSessionToText(session);
    },
    killPipeline: () => { pipeline.kill(); },
    exit: () => { pipeline.kill(); exit(); process.exit(0); },
    showMessage: (text, color) => {
      if (inlineMsgTimer.current) clearTimeout(inlineMsgTimer.current);
      setInlineMessage({ text, color });
      inlineMsgTimer.current = setTimeout(() => setInlineMessage(null), 5000);
    },
    setPromptText: (text) => {
      setPromptPrefill(text);
    },
  };

  // ── Input screen ──────────────────────────────────────────────
  if (screen === 'input') {
    return (
      <Box flexDirection="column" paddingX={1}>
        <WelcomeScreen
          onSubmit={handleConceptSubmit}
          dispatch={appDispatch}
          onResumeProject={(project) => {
            setConcept(project.concept);
            addRunMarker(project.concept, true);
            pipeline.start({ concept: project.concept, max_retries: maxRetries, is_lite: isLite, skip_audio: skipAudio, resume_dir: project.dir, model: currentModel });
            setScreen('running');
            setRunState('active');
            setLastFinalUpdate(undefined); setLastErrorInfo(undefined); setBoardSelectedSegmentId(undefined); setBoardScrollOffset(0); setBoardFollowMode(true);
          }}
          promptPrefill={promptPrefill}
          onPromptPrefillConsumed={() => setPromptPrefill(undefined)}
        />
        {inlineMessage && (
          <Box marginTop={1} paddingLeft={1}>
            <Text color={inlineMessage.color ?? themeColors.dim}>{inlineMessage.text}</Text>
          </Box>
        )}
        {ctrlCPending && (
          <Box marginTop={1}>
            <Text color={themeColors.dim}>Press <Text bold>Ctrl+C</Text> again to exit</Text>
          </Box>
        )}
        <FooterStatusLine stage={null} />
      </Box>
    );
  }

  // ── Workspace screen ────────────────────────────────────────
  if (screen === 'workspace') {
    return (
      <Box flexDirection="column" paddingX={1}>
        <Banner concept={concept} />
        <WorkspaceDashboard
          onResume={(resumeConcept, resumeFromDir) => {
            setConcept(resumeConcept);
            addRunMarker(resumeConcept, true);
            pipeline.start({ concept: resumeConcept, max_retries: maxRetries, is_lite: isLite, skip_audio: skipAudio, resume_dir: resumeFromDir, render_timeout: renderTimeout, tts_timeout: ttsTimeout, system_prompt_prefix: buildSystemPrompt(), max_turns: maxTurns, model: currentModel });
            setScreen('running');
            setRunState('active');
            setLastFinalUpdate(undefined); setLastErrorInfo(undefined); setBoardSelectedSegmentId(undefined); setBoardScrollOffset(0); setBoardFollowMode(true);
          }}
          onRerun={(rerunConcept, rerunFromDir) => {
            setConcept(rerunConcept);
            addRunMarker(rerunConcept);
            pipeline.start({ concept: rerunConcept, max_retries: maxRetries, is_lite: isLite, skip_audio: skipAudio, resume_dir: rerunFromDir, force_restart: true, render_timeout: renderTimeout, tts_timeout: ttsTimeout, system_prompt_prefix: buildSystemPrompt(), max_turns: maxTurns, model: currentModel });
            setScreen('running');
            setRunState('active');
            setLastFinalUpdate(undefined); setLastErrorInfo(undefined); setBoardSelectedSegmentId(undefined); setBoardScrollOffset(0); setBoardFollowMode(true);
          }}
          onBack={() => {
            setScreen('input');
          }}
        />
        {ctrlCPending && (
          <Box marginTop={1}>
            <Text color={themeColors.dim}>Press <Text bold>Ctrl+C</Text> again to exit</Text>
          </Box>
        )}
        <FooterStatusLine stage={null} />
      </Box>
    );
  }

  // ── Questionnaire screen ──────────────────────────────────────
  if (screen === 'questionnaire') {
    return (
      <Box flexDirection="column" paddingX={1}>
        <Questionnaire
          concept={concept}
          questions={pipeline.questions}
          onComplete={handleQuestionnaireComplete}
          onCancel={() => setScreen('input')}
        />
        {ctrlCPending && (
          <Box marginTop={1}>
            <Text color={themeColors.dim}>Press <Text bold>Ctrl+C</Text> again to exit</Text>
          </Box>
        )}
        <FooterStatusLine stage={null} />
      </Box>
    );
  }

  // ── Running / Complete / Error screens ──────────────────────
  return (
    <Box flexDirection="column" paddingX={1}>
      <RunScreen
        concept={concept}
        stage={currentStage}
        elapsed={elapsed}
        runState={runState}
        segments={segments}
        segmentCodes={segmentCodes}
        boardRows={boardRows}
        totalSegments={stageSegmentsTotal}
        progressPct={progressPct}
        progressMode={progressMode}
        selectedSegmentId={boardSelectedSegmentId}
        scrollOffset={boardScrollOffset}
        completedStages={completedStages}
        finalUpdate={lastFinalUpdate}
        errorInfo={lastErrorInfo}
      />

      {/* Help overlay — post-run only */}
      {showHelp && runState !== 'active' && (
        <KeyboardShortcuts verboseMode={verboseLive} />
      )}

      {/* Ctrl+C warning */}
      {ctrlCPending && (
        <Box paddingLeft={1} marginTop={1}>
          <Text color={themeColors.dim}>Press <Text bold>Ctrl+C</Text> again to exit</Text>
        </Box>
      )}

      {/* Permission prompt */}
      {pipeline.permissionPending && (
        <PermissionPrompt
          operation={pipeline.permissionPending.operation}
          path={pipeline.permissionPending.path}
          onAllow={() => pipeline.answerPermission(true)}
          onDeny={() => pipeline.answerPermission(false)}
          onAllowAlways={() => pipeline.answerPermission(true, true)}
        />
      )}

      {/* Footer */}
      <FooterStatusLine
        stage={currentStage}
        progress={progressPct}
        progressMode={progressMode}
        verboseModeOverride={verboseLive}
        hintText={runState === 'active'
          ? '↑↓ select  ·  g follow  ·  Ctrl+C stop'
          : '↑↓ select  ·  g follow  ·  ? help'}
        elapsedSeconds={elapsed}
        segmentsCompleted={segmentsCompleted}
        totalSegments={stageSegmentsTotal}
      />
    </Box>
  );
}

/** Public App component — wraps AppInner with AppContextProvider. */
export function App(props: AppProps) {
  return (
    <AppContextProvider
      settings={props.settings}
      session={props.session}
      gitBranch={props.gitBranch}
    >
      <AppInner
        initialConcept={props.initialConcept}
        maxRetries={props.maxRetries}
        isLite={props.isLite}
        quality={props.quality}
        skipAudio={props.skipAudio}
        workspace={props.workspace}
        resumeDir={props.resumeDir}
        verbose={props.verbose}
        renderTimeout={props.renderTimeout}
        ttsTimeout={props.ttsTimeout}
        systemPrompt={props.systemPrompt}
        maxTurns={props.maxTurns}
      />
    </AppContextProvider>
  );
}
