import { execSync, execFileSync } from 'node:child_process';
import os from 'node:os';
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Box, Text, Static, useApp, useInput } from 'ink';
import { Banner } from './components/Banner.js';
import { ConceptInput } from './components/ConceptInput.js';
import { WelcomeScreen } from './components/WelcomeScreen.js';
import { Questionnaire } from './components/Questionnaire.js';
import { StagePanel } from './components/StagePanel.js';
import { SegmentStatus } from './components/SegmentStatus.js';
import { StatusBar, type ActivityLine, type ActivityKind } from './components/StatusBar.js';
import { AgentActivityPanel } from './components/AgentActivityPanel.js';
import { SummaryTable } from './components/SummaryTable.js';
import { ErrorPanel } from './components/ErrorPanel.js';
import { SuccessPanel } from './components/SuccessPanel.js';
import { WorkspaceDashboard } from './components/WorkspaceDashboard.js';
import { FooterStatusLine } from './components/FooterStatusLine.js';
import { PromptBar } from './components/PromptBar.js';
import { SettingsPanel } from './components/SettingsPanel.js';
import { DoctorPanel } from './components/DoctorPanel.js';
import { ContextVisualizer } from './components/ContextVisualizer.js';
import { KeybindingsHelpOverlay } from './components/KeybindingsHelpOverlay.js';
import { KeyboardShortcuts } from './components/KeyboardShortcuts.js';
import { PermissionPrompt } from './components/PermissionPrompt.js';
import { runHooks } from './lib/hooks.js';
import { usePipeline } from './hooks/usePipeline.js';
import { useElapsed } from './hooks/useElapsed.js';
import { useTerminalWidth } from './hooks/useTerminalWidth.js';
import { AppContextProvider, useAppContext } from './context/AppContext.js';
import { exportSessionToText } from './lib/session.js';
import { loadMemory } from './lib/memory.js';
import { getStageConfig, segmentPhaseLabels, cleanStatus, type StageName } from './lib/theme.js';
import { formatDuration, formatToolCall } from './lib/format.js';
import { summarizeToolOutput } from './components/StatusBar.js';
import { buildCompactUnifiedDiff } from './lib/codeDiff.js';
import { collapseRunLogsForRetry, getRunLogDedupeKey, sanitizeRunLogText } from './lib/runLog.js';
import { resolveEffectiveVerbose } from './lib/verbose.js';
import type { CompletedStage, ProgressMode, SegmentState, Settings, Session } from './lib/types.js';
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

  const initialScreen: Screen = workspace ? 'workspace' : (initialConcept || resumeDir) ? 'running' : 'input';
  const [screen, setScreen] = useState<Screen>(initialScreen);
  const [concept, setConcept] = useState(initialConcept ?? '');

  // All rendered log items (scroll region via Static)
  const [logEntries, setLogEntries] = useState<LogEntry[]>([]);
  const logIdCounter = useRef(0);
  const [activeRunLogStart, setActiveRunLogStart] = useState(0);
  const activeRunLogStartRef = useRef(0);
  const [collapsedHistoryCount, setCollapsedHistoryCount] = useState(0);
  useEffect(() => { activeRunLogStartRef.current = activeRunLogStart; }, [activeRunLogStart]);

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

  // Activity stream (Claude Code-style) — recent activity lines for live display
  const [activityLines, setActivityLines] = useState<ActivityLine[]>([]);
  const activityIdCounter = useRef(0);
  const segmentCodeCacheRef = useRef<Map<number, string>>(new Map());

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
    setActivityLines(prev => {
      // Keep a rolling window of last 90 lines (collapsed later in StatusBar).
      const next = [...prev, { id, ...line, text: safeText, detail: safeDetail, kind: mappedKind, groupKey }];
      return next.length > 90 ? next.slice(-90) : next;
    });
  };

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

    // ? — toggle keyboard help overlay
    if (_input === '?' && screen === 'running') {
      setShowHelp(h => !h);
      return;
    }

    // Navigate back from secondary screens with Esc (handled per-screen via useInput in child components)
  });

  // Keep run markers concise to avoid duplicating banner metadata.
  const addRunMarker = (c: string, isResume = false) => {
    const prefix = isResume ? 'Resuming run' : 'Starting run';
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

    // Track total segments
    if (latest.num_segments) {
      setTotalSegments(latest.num_segments);
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
        setCompletedStages(prev => [...prev, completed]);
        addLog({ type: 'stage-complete', stage: completed });
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
      }

      if (stage === 'pipeline') {
        setSegmentsTracked(() => new Map());
        prevSegPhases.current = new Map();
      }
      // code_retry reuses existing segment state — don't clear
    }

    // ── Intermediate status updates ─────────────────────────────
    // Show as regular status unless it's a segment-specific update
    const hasSegmentId = latest.segment_id !== undefined;
    const isSegmentStage = PIPELINE_SUBSTAGES.has(stage) || stage === 'code_retry';
    if (latest.status && !(isSegmentStage && hasSegmentId)) {
      const cleaned = cleanStatus(latest.status);
      setStatusDetailTracked(cleaned);
      batchStatusDetail = cleaned;
      if (cleaned) {
        addActivity({
          kind: 'status',
          text: cleaned,
          group: classifyActivityGroup(cleaned),
          severity: classifyActivitySeverity(cleaned),
        });
      }
      // Status lines are shown in the live activity stream; avoid duplicating in static log.
    }

    // ── Tool call events for ALL stages (Claude Code-style) ─────
    if (latest.tool_call && stage !== 'code' && stage !== 'code_retry') {
      const tc = latest.tool_call;
      const displayText = formatToolCall(tc.name, tc.params);
      addActivity({
        kind: 'tool_call',
        text: displayText,
        group: classifyActivityGroup(displayText),
        severity: classifyActivitySeverity(displayText),
      });
    }
    if (latest.tool_result && stage !== 'code' && stage !== 'code_retry') {
      const out = latest.tool_result.output?.trim() || '(no output)';
      addActivity({
        kind: 'tool_result',
        text: `${latest.tool_result.name}: ${summarizeToolOutput(out)}`,
        detail: out,
        group: 'done',
        severity: classifyActivitySeverity(out),
      });
    }

    // ── Thinking events for ALL stages ──────────────────────────
    if (latest.thinking !== undefined && stage !== 'code' && stage !== 'code_retry') {
      if (latest.thinking) {
        const thinkText = typeof latest.thinking === 'string'
          ? latest.thinking.slice(0, 120)
          : 'Reasoning...';
        addActivity({ kind: 'thinking', text: thinkText, group: 'checking' });
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
        const startedAt = existing?.startedAt ?? now;
        const segState: SegmentState = {
          id: segId,
          phase,
          prettyPhase,
          attempt,
          done: phase === 'done',
          failed: phase === 'failed',
          startedAt,
          finishedAt: (phase === 'done' || phase === 'failed') ? now : existing?.finishedAt,
          // Carry forward agent activity from previous state
          isThinking: existing?.isThinking,
          thinkingText: existing?.thinkingText,
          lastStatus: existing?.lastStatus,
          lastToolCall: existing?.lastToolCall,
          lastToolResult: existing?.lastToolResult,
          failHint: existing?.failHint,
        };

        // Update agent activity based on pipeline event
        if (latest.thinking !== undefined) {
          segState.isThinking = !!latest.thinking;
          segState.thinkingText = typeof latest.thinking === 'string' ? latest.thinking : undefined;
          if (latest.thinking) segState.lastToolCall = undefined;
        }
        if (latest.tool_call) {
          segState.isThinking = false;
          segState.thinkingText = undefined;
          segState.lastToolCall = latest.tool_call;
        }
        if (latest.tool_result) {
          segState.lastToolResult = latest.tool_result;
        }
        if (latest.status) {
          segState.lastStatus = cleanStatus(latest.status);
        }
        if (phase === 'failed') {
          segState.failHint = extractFailureHint(latest.error)
            ?? extractFailureHint(latest.segment_status)
            ?? extractFailureHint(latest.status)
            ?? segState.failHint;
        }
        // Clear activity on completion
        if (phase === 'done' || phase === 'failed') {
          segState.isThinking = false;
          segState.thinkingText = undefined;
          segState.lastToolCall = undefined;
          segState.lastToolResult = undefined;
        }
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

        const attemptNum = attemptMatch ? parseInt(attemptMatch[1]!, 10) : 1;
        const attemptStr = attemptNum > 1 ? ` on attempt ${attemptNum}` : '';

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
        addActivity({
          kind: 'tool_call',
          text: `Seg ${segId}: ${displayText}`,
          segmentId: segId,
          group: classifyActivityGroup(displayText),
          severity: classifyActivitySeverity(displayText),
        });
      }
      if (latest.tool_result) {
        const out = latest.tool_result.output?.trim() || '(no output)';
        addActivity({
          kind: 'tool_result',
          text: `Seg ${segId}: ${latest.tool_result.name}: ${summarizeToolOutput(out)}`,
          detail: out,
          segmentId: segId,
          group: 'done',
          severity: classifyActivitySeverity(out),
        });
      }

      // Thinking events during code stages
      if (latest.thinking !== undefined) {
        if (latest.thinking) {
          const thinkText = typeof latest.thinking === 'string'
            ? `Seg ${segId}: ${latest.thinking.slice(0, 100)}`
            : `Seg ${segId}: Reasoning...`;
          addActivity({ kind: 'thinking', text: thinkText, segmentId: segId, group: 'checking' });
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
            addActivity({
              kind: 'diff',
              segmentId: segId,
              text: `Seg ${segId} code changes (${diff.summary})`,
              detail: diff.lines.join('\n'),
              group: 'doing',
              severity: 'normal',
              groupKey: `diff:${segId}:${diff.dedupeKey}`,
            });
          }
          segmentCodeCacheRef.current.set(segId, nextCode);
        }
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
        setCompletedStages(prev => [...prev, completed]);
        addLog({ type: 'stage-complete', stage: completed });
      }
      setCurrentStageTracked('done');
      batchStage = 'done';

      if (latest.error) {
        setScreen('error');
      } else {
        setScreen('complete');

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

      addLog({
        type: 'log',
        text: `[Fixing] Retrying failed segments (${visibleHistory} prior run line${visibleHistory === 1 ? '' : 's'} collapsed)`,
        color: themeColors.warn,
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
          }}
          onRerun={(rerunConcept, rerunFromDir) => {
            setConcept(rerunConcept);
            addRunMarker(rerunConcept);
            pipeline.start({ concept: rerunConcept, max_retries: maxRetries, is_lite: isLite, skip_audio: skipAudio, resume_dir: rerunFromDir, force_restart: true, render_timeout: renderTimeout, tts_timeout: ttsTimeout, system_prompt_prefix: buildSystemPrompt(), max_turns: maxTurns, model: currentModel });
            setScreen('running');
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

  // ── Running / Complete / Error screens ────────────────────────
  const finalUpdate = pipeline.finalUpdate;

  return (
    <Box flexDirection="column" paddingX={1}>
      {/* Banner rendered once at the top — NOT in Static to avoid double-render on screen transitions */}
      <Banner concept={concept} />
      {collapsedHistoryCount > 0 && (
        <Box paddingLeft={1} marginBottom={1}>
          <Text color={themeColors.muted}>
            Previous run logs collapsed ({collapsedHistoryCount} line{collapsedHistoryCount === 1 ? '' : 's'} hidden)
          </Text>
        </Box>
      )}

      {/* Scrolling log region — concept header, completed stages, segment events */}
      <Static items={logEntries.slice(activeRunLogStart)}>
        {(entry) => {
          if (entry.type === 'header') {
            return (
              <Box key={entry.id} marginBottom={1}>
                <Text color={themeColors.dim}>{entry.text}</Text>
              </Box>
            );
          }

          if (entry.type === 'stage-complete' && entry.stage) {
            return (
              <Box key={entry.id}>
                <StagePanel
                  name={entry.stage.name}
                  summary={entry.stage.summary}
                  elapsed={entry.stage.elapsed}
                  status={entry.stage.status}
                  error={entry.stage.error}
                />
              </Box>
            );
          }

          // Segment completion/failure line
          return (
            <Box key={entry.id} paddingLeft={3}>
              <Text>
                <Text color={entry.color ?? themeColors.dim}>
                  {entry.icon ?? '│'}{' '}
                </Text>
                {entry.bold ? (
                  <Text bold color={entry.color}>{entry.text}</Text>
                ) : (
                  <Text color={themeColors.dim}>{entry.text}</Text>
                )}
              </Text>
            </Box>
          );
        }}
      </Static>

      {/* Live section: status bar activity stream + agent activity panel */}
      {screen === 'running' && currentStage && currentStage !== 'done' && (
        <>
          <StatusBar
            stage={currentStage}
            elapsed={elapsed}
            activity={activityLines}
            segmentsCompleted={segmentsCompleted}
            totalSegments={stageSegmentsTotal}
            progressPct={progressPct}
            progressMode={progressMode}
            stageProgressPct={stageProgressPct}
            hintText={runtimeHintText}
            verbose={verboseLive}
            maxLines={(currentStage === 'code' || currentStage === 'code_retry')
              ? (verboseLive ? 6 : 3)
              : 6}
          />
          <Box flexDirection="column" paddingLeft={1} marginTop={1}>
            {(segments.size > 0 || currentStage === 'pipeline' || currentStage === 'tts' || currentStage === 'code' || currentStage === 'render' || currentStage === 'stitch' || currentStage === 'code_retry') && (
              <>
                <Text bold color={themeColors.primary}>Segment Health</Text>
                {segments.size > 0 ? (
                  <SegmentStatus segments={segments} verbose={verboseLive} />
                ) : (
                  <Box paddingLeft={2}>
                    <Text color={themeColors.dim}>
                      {waitingForFirstSegmentUpdate
                        ? `Queued ${stageSegmentsTotal} segment${stageSegmentsTotal === 1 ? '' : 's'}; waiting for the first worker update...`
                        : 'Preparing segment workers...'}
                    </Text>
                  </Box>
                )}
                {(currentStage === 'code' || currentStage === 'code_retry') && segments.size > 0 && (
                  <AgentActivityPanel
                    segments={segments}
                    verbose={verboseLive}
                  />
                )}
              </>
            )}
          </Box>
        </>
      )}

      {showHelp && screen === 'running' && (
        <KeyboardShortcuts verboseMode={verboseLive} />
      )}

      {/* Summary + success on completion */}
      {screen === 'complete' && finalUpdate && (
        <Box flexDirection="column">
          <SummaryTable
            stages={completedStages}
            toolCallCounts={finalUpdate.tool_call_counts}
            totalToolCalls={finalUpdate.total_tool_calls}
            tokenSummary={finalUpdate.token_summary}
          />
          {finalUpdate.video_path && (
            <SuccessPanel videoPath={finalUpdate.video_path} />
          )}
        </Box>
      )}

      {/* Error display */}
      {screen === 'error' && (
        <ErrorPanel
          message={pipeline.errorMessage || 'Pipeline failed'}
          failedSegments={pipeline.finalUpdate?.failed_segments}
          numSegments={pipeline.finalUpdate?.num_segments}
          videoPath={pipeline.finalUpdate?.video_path}
          projectDir={pipeline.finalUpdate?.project_dir}
          tokenSummary={pipeline.finalUpdate?.token_summary}
          stages={completedStages}
        />
      )}

      {/* Ctrl+C warning */}
      {ctrlCPending && (
        <Box paddingLeft={1} marginTop={1}>
          <Text color={themeColors.dim}>Press <Text bold>Ctrl+C</Text> again to exit</Text>
        </Box>
      )}

      {/* Permission prompt (default mode) */}
      {pipeline.permissionPending && (
        <PermissionPrompt
          operation={pipeline.permissionPending.operation}
          path={pipeline.permissionPending.path}
          onAllow={() => pipeline.answerPermission(true)}
          onDeny={() => pipeline.answerPermission(false)}
          onAllowAlways={() => pipeline.answerPermission(true, true)}
        />
      )}

      {/* Footer status line — always at bottom */}
      <FooterStatusLine
        stage={currentStage}
        progress={progressPct}
        progressMode={progressMode}
        verboseModeOverride={verboseLive}
        hintText={!verboseLive ? '? help · Ctrl+O verbose · Ctrl+C twice exits' : undefined}
        elapsedSeconds={elapsed}
        segmentsCompleted={segmentsCompleted}
        totalSegments={stageSegmentsTotal}
        stageProgressPct={stageProgressPct}
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
