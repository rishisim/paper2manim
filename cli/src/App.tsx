import { execSync, execFileSync } from 'node:child_process';
import os from 'node:os';
import React, { useState, useEffect, useRef } from 'react';
import { Box, Text, Static, useApp, useInput } from 'ink';
import { Banner } from './components/Banner.js';
import { ConceptInput } from './components/ConceptInput.js';
import { WelcomeScreen } from './components/WelcomeScreen.js';
import { Questionnaire } from './components/Questionnaire.js';
import { StagePanel, StageHeader } from './components/StagePanel.js';
import { SegmentStatus } from './components/SegmentStatus.js';
import { StatusBar, type ActivityLine } from './components/StatusBar.js';
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
import { AppContextProvider, useAppContext } from './context/AppContext.js';
import { exportSessionToText } from './lib/session.js';
import { loadMemory } from './lib/memory.js';
import { getStageConfig, segmentPhaseLabels, cleanStatus, type StageName } from './lib/theme.js';
import { formatDuration, formatToolCall } from './lib/format.js';
import type { CompletedStage, SegmentState, Settings, Session } from './lib/types.js';
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
  type: 'header' | 'stage-header' | 'stage-complete' | 'log' | 'segment';
  // For stage-complete
  stage?: CompletedStage;
  // For log / segment lines
  text?: string;
  color?: string;
  icon?: string;
  bold?: boolean;
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

  const initialScreen: Screen = workspace ? 'workspace' : (initialConcept || resumeDir) ? 'running' : 'input';
  const [screen, setScreen] = useState<Screen>(initialScreen);
  const [concept, setConcept] = useState(initialConcept ?? '');

  // All rendered log items (scroll region via Static)
  const [logEntries, setLogEntries] = useState<LogEntry[]>([]);
  const logIdCounter = useRef(0);

  const addLog = (entry: Omit<LogEntry, 'id'>) => {
    const id = `log-${logIdCounter.current++}`;
    setLogEntries(prev => {
      // Dedup: skip if the last entry has the same type and text (Ink double-render guard)
      const last = prev[prev.length - 1];
      if (last && last.type === entry.type && 'text' in last && 'text' in entry && last.text === entry.text) {
        return prev;
      }
      return [...prev, { id, ...entry }];
    });
  };

  // Pipeline state
  const [currentStage, setCurrentStage] = useState<StageName | null>(null);
  const [stageStartTime, setStageStartTime] = useState(Date.now());
  const [segments, setSegments] = useState<Map<number, SegmentState>>(new Map());
  const [totalSegments, setTotalSegments] = useState(0);
  const [statusDetail, setStatusDetail] = useState('');
  const [completedStages, setCompletedStages] = useState<CompletedStage[]>([]);

  // Activity stream (Claude Code-style) — recent activity lines for live display
  const [activityLines, setActivityLines] = useState<ActivityLine[]>([]);
  const activityIdCounter = useRef(0);

  const addActivity = (line: Omit<ActivityLine, 'id'>) => {
    const id = `act-${activityIdCounter.current++}`;
    setActivityLines(prev => {
      // Keep a rolling window of last 50 lines (only last N are displayed)
      const next = [...prev, { id, ...line }];
      return next.length > 50 ? next.slice(-50) : next;
    });
  };

  // Track previous segment phases to only log on phase transitions
  const prevSegPhases = useRef<Map<number, string>>(new Map());

  const isRunning = screen === 'running' && currentStage !== null && currentStage !== 'done';
  const elapsed = useElapsed(isRunning);

  // Compute overall pipeline progress (0-100)
  const progressPct = (() => {
    if (!currentStage || currentStage === 'done') return 100;
    const total = totalSegments || Math.max(segments.size, 1);
    const segsDone = [...segments.values()].filter(s => s.done || s.failed).length;
    switch (currentStage) {
      case 'plan':        return 5;
      case 'tts':         return 20;
      case 'code':        return 20 + Math.floor((segsDone / total) * 30);
      case 'code_retry':  return 50 + Math.floor((segsDone / total) * 15);
      case 'verify':      return 65;
      case 'render':      return 75;
      case 'timing':      return 85;
      case 'concat':      return 90;
      case 'overlay':     return 95;
      default:            return 0;
    }
  })();

  // ── Double Ctrl+C to exit (Claude Code style) ──────────────
  const [ctrlCPending, setCtrlCPending] = useState(false);
  const ctrlCTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inlineMsgTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Keyboard shortcut state ─────────────────────────────────
  const [showHelp, setShowHelp] = useState(false);
  // Sync verboseLive with context verboseMode
  const verboseLive = ctxVerboseMode;
  const verboseLiveRef = useRef(ctxVerboseMode);
  useEffect(() => { verboseLiveRef.current = ctxVerboseMode; }, [ctxVerboseMode]);

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
      setVerboseMode(v => !v);
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

    // Alt+P — cycle model opus ↔ sonnet
    if (key.meta && _input === 'p') {
      const next = currentModel.includes('opus') ? 'claude-sonnet-4-6' : 'claude-opus-4-6';
      setCurrentModel(next);
      return;
    }

    // Esc+Esc — rewind to last checkpoint (quick double-Esc)
    if (key.escape) {
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

  // Add only the concept header to the static log (banner is rendered separately, not in Static)
  const addConceptHeader = (c: string, isResume = false) => {
    const qualityLabel = ctxQuality.charAt(0).toUpperCase() + ctxQuality.slice(1);
    const modelLabel = currentModel ? `  Model: ${currentModel}` : '';
    const prefix = isResume ? 'Resuming' : 'Concept';
    addLog({
      type: 'header',
      text: `${prefix}: ${c}  Quality: ${qualityLabel}${modelLabel}`,
    });
  };

  // Start pipeline when concept is set (from CLI arg) or resuming
  useEffect(() => {
    if (resumeDir) {
      addConceptHeader('project from: ' + resumeDir, true);
      pipeline.start({ concept: 'resume', max_retries: maxRetries, is_lite: isLite, skip_audio: skipAudio, resume_dir: resumeDir, render_timeout: renderTimeout, tts_timeout: ttsTimeout, system_prompt_prefix: buildSystemPrompt(), max_turns: maxTurns, model: currentModel });
    } else if (initialConcept) {
      addConceptHeader(initialConcept);
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
    addConceptHeader(c);
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
  const processedIdx = useRef(0);
  useEffect(() => {
    if (pipeline.updates.length === 0) return;

    // Process all updates since last render, not just the latest
    const unprocessed = pipeline.updates.slice(processedIdx.current);
    processedIdx.current = pipeline.updates.length;

    for (const latest of unprocessed) {
    const stage = latest.stage as StageName;

    // Track total segments
    if (latest.num_segments) {
      setTotalSegments(latest.num_segments);
    }

    // ── Stage transitions ───────────────────────────────────────
    if (stage !== currentStage && stage !== 'done') {
      // Complete the previous stage → add panel to log
      if (currentStage && currentStage !== 'done') {
        const stageElapsed = (Date.now() - stageStartTime) / 1000;
        const config = getStageConfig(themeColors)[currentStage];
        const completed: CompletedStage = {
          name: currentStage,
          summary: statusDetail || `${config?.label ?? currentStage} complete`,
          elapsed: stageElapsed,
          status: 'ok',
        };
        setCompletedStages(prev => [...prev, completed]);
        addLog({ type: 'stage-complete', stage: completed });
      }

      // New stage header
      setCurrentStage(stage);
      setStageStartTime(Date.now());
      setStatusDetail('');
      setActivityLines([]);  // Clear activity stream on stage transition
      addLog({ type: 'stage-header', text: stage });

      if (stage === 'code') {
        setSegments(new Map());
        prevSegPhases.current = new Map();
      }
      // code_retry reuses existing segment state — don't clear
    }

    // ── Intermediate status updates ─────────────────────────────
    if (latest.status && stage !== 'code' && stage !== 'code_retry') {
      const cleaned = cleanStatus(latest.status);
      setStatusDetail(cleaned);
      if (cleaned) {
        addActivity({ type: 'status', text: cleaned });
      }
      // In verbose mode, log each status update to the scroll region
      if (verboseLiveRef.current && cleaned) {
        addLog({ type: 'log', text: cleaned, color: themeColors.dim });
      }
    }

    // ── Tool call events for ALL stages (Claude Code-style) ─────
    if (latest.tool_call && stage !== 'code' && stage !== 'code_retry') {
      const tc = latest.tool_call;
      const displayText = formatToolCall(tc.name, tc.params);
      addActivity({ type: 'tool_call', text: displayText });
      addLog({
        type: 'log',
        text: `  ⎿ ${displayText}`,
        color: themeColors.accent,
      });
    }

    // ── Thinking events for ALL stages ──────────────────────────
    if (latest.thinking !== undefined && stage !== 'code' && stage !== 'code_retry') {
      if (latest.thinking) {
        const thinkText = typeof latest.thinking === 'string'
          ? latest.thinking.slice(0, 120)
          : 'Reasoning...';
        addActivity({ type: 'thinking', text: thinkText });
      }
    }

    // ── Segment-level updates during code / code_retry stage ────
    if ((stage === 'code' || stage === 'code_retry') && latest.segment_id !== undefined) {
      const segId = latest.segment_id;
      const phase = latest.segment_phase ?? 'running';
      const prettyPhase = segmentPhaseLabels[phase] ?? phase;

      // Track attempt number
      const attemptMatch = latest.status?.match(/Attempt (\d+)\//);

      setSegments(prev => {
        const next = new Map(prev);
        const existing = next.get(segId);
        let attempt = existing?.attempt ?? 1;
        if (attemptMatch) attempt = parseInt(attemptMatch[1]!, 10);

        const now = Date.now();
        const segState: SegmentState = {
          id: segId,
          phase,
          prettyPhase,
          attempt,
          done: phase === 'done',
          failed: phase === 'failed',
          startedAt: existing?.startedAt ?? now,
          finishedAt: (phase === 'done' || phase === 'failed') ? now : existing?.finishedAt,
          // Carry forward agent activity from previous state
          isThinking: existing?.isThinking,
          lastToolCall: existing?.lastToolCall,
          lastToolResult: existing?.lastToolResult,
        };

        // Update agent activity based on pipeline event
        if (latest.thinking !== undefined) {
          segState.isThinking = !!latest.thinking;
          if (latest.thinking) segState.lastToolCall = undefined;
        }
        if (latest.tool_call) {
          segState.isThinking = false;
          segState.lastToolCall = latest.tool_call;
        }
        if (latest.tool_result) {
          segState.lastToolResult = latest.tool_result;
        }
        // Clear activity on completion
        if (phase === 'done' || phase === 'failed') {
          segState.isThinking = false;
          segState.lastToolCall = undefined;
          segState.lastToolResult = undefined;
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
          const seg = segments.get(segId);
          const segElapsed = seg?.startedAt ? ((Date.now() - seg.startedAt) / 1000) : 0;
          const timeStr = segElapsed > 0 ? ` in ${formatDuration(segElapsed)}` : '';
          addLog({
            type: 'segment',
            text: `Segment ${segId} completed${attemptStr}${timeStr}`,
            icon: 'OK',
            color: themeColors.success,
            bold: true,
          });
        } else if (phase === 'failed') {
          const seg = segments.get(segId);
          const segElapsed = seg?.startedAt ? ((Date.now() - seg.startedAt) / 1000) : 0;
          const timeStr = segElapsed > 0 ? ` after ${formatDuration(segElapsed)}` : '';
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
        addActivity({ type: 'tool_call', text: `Seg ${segId}: ${displayText}` });
        addLog({
          type: 'log',
          text: `  ⎿ Seg ${segId}: ${displayText}`,
          color: themeColors.accent,
        });
      }

      // Thinking events during code stages
      if (latest.thinking !== undefined) {
        if (latest.thinking) {
          const thinkText = typeof latest.thinking === 'string'
            ? `Seg ${segId}: ${latest.thinking.slice(0, 100)}`
            : `Seg ${segId}: Reasoning...`;
          addActivity({ type: 'thinking', text: thinkText });
        }
      }

      // Update status bar detail
      if (latest.status) {
        setStatusDetail(cleanStatus(latest.status));
      }
    } else if ((stage === 'code' || stage === 'code_retry') && latest.status) {
      // Code stage summary updates (not segment-specific)
      setStatusDetail(cleanStatus(latest.status));
    }

    // ── Final update ────────────────────────────────────────────
    if (latest.final) {
      if (currentStage && currentStage !== 'done') {
        const stageElapsed = (Date.now() - stageStartTime) / 1000;
        const completed: CompletedStage = {
          name: currentStage,
          summary: latest.status ?? 'Complete',
          elapsed: stageElapsed,
          status: latest.error ? 'failed' : 'ok',
          error: latest.error,
        };
        setCompletedStages(prev => [...prev, completed]);
        addLog({ type: 'stage-complete', stage: completed });
      }
      setCurrentStage('done');

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
    setVerboseMode: (v: boolean) => setVerboseMode(v),
    toggleVerboseMode: () => setVerboseMode(v => !v),
    setThinkingVisible: (v: boolean) => setThinkingVisible(v),
    setPromptColor: (color) => setPromptColor(color),
    setCurrentModel: (model) => setCurrentModel(model),
    setTheme: (theme) => updateSetting('theme', theme),
    setQuality: (q) => setQuality(q),
    startPipeline: (c) => handleConceptSubmit(c),
    resumePipeline: (dir) => {
      setConcept(dir);
      addConceptHeader(dir, true);
      pipeline.start({ concept: 'resume', max_retries: maxRetries, is_lite: isLite, skip_audio: skipAudio, resume_dir: dir, render_timeout: renderTimeout, tts_timeout: ttsTimeout, system_prompt_prefix: buildSystemPrompt(), max_turns: maxTurns, model: currentModel });
      setScreen('running');
    },
    compactLogs: (_instructions) => {
      setLogEntries(prev => prev.slice(-5));
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
            addConceptHeader(project.concept, true);
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
            addConceptHeader(resumeConcept, true);
            pipeline.start({ concept: resumeConcept, max_retries: maxRetries, is_lite: isLite, skip_audio: skipAudio, resume_dir: resumeFromDir, render_timeout: renderTimeout, tts_timeout: ttsTimeout, system_prompt_prefix: buildSystemPrompt(), max_turns: maxTurns, model: currentModel });
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

      {/* Scrolling log region — concept header, completed stages, segment events */}
      <Static items={logEntries}>
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

          if (entry.type === 'stage-header' && entry.text) {
            return (
              <Box key={entry.id}>
                <StageHeader name={entry.text as StageName} />
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
            maxLines={(currentStage === 'code' || currentStage === 'code_retry') ? 3 : 6}
          />
          {(currentStage === 'code' || currentStage === 'code_retry') && segments.size > 0 && (
            <AgentActivityPanel
              segments={segments}
              verbose={verboseLive}
            />
          )}
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
      <FooterStatusLine stage={currentStage} progress={progressPct} />
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
