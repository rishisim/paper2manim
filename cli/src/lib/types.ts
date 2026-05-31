/**
 * TypeScript types for the Python pipeline NDJSON protocol.
 */

import type { StageName } from './theme.js';

// ── Permission Modes ─────────────────────────────────────────────────────────

export type PermissionMode =
  | 'default'            // Prompt for all file writes / shell commands
  | 'acceptEdits'        // Accept all file ops without prompting
  | 'plan'               // Read-only — plan storyboard only, no generation
  | 'auto'               // All operations with background safety check
  | 'bypassPermissions'; // All operations, no checks

export const PERMISSION_MODES: PermissionMode[] = [
  'default', 'acceptEdits', 'plan', 'auto', 'bypassPermissions',
];

export const PERMISSION_MODE_LABELS: Record<PermissionMode, string> = {
  default:            'default',
  acceptEdits:        'accept edits',
  plan:               'plan',
  auto:               'auto',
  bypassPermissions:  'bypass',
};

// ── Theme ───────────────────────────────────────────────────────────────────

export type ThemeName = 'dark' | 'light' | 'minimal' | 'colorblind' | 'ansi';

// ── Token Usage ──────────────────────────────────────────────────────────────

export interface TokenUsage {
  input: number;
  output: number;
  cacheRead: number;
}

// ── Hooks ────────────────────────────────────────────────────────────────────

export type HookEvent =
  | 'SessionStart'
  | 'SessionEnd'
  | 'UserPromptSubmit'
  | 'PreGenerate'
  | 'PostGenerate'
  | 'Notification'
  | 'PreCompact';

export type HookHandler =
  | { type: 'command'; command: string }
  | { type: 'http'; url: string };

export type HooksConfig = Partial<Record<HookEvent, HookHandler[]>>;

// ── Permission Rules ─────────────────────────────────────────────────────────

export interface PermissionRules {
  allow?: string[];
  ask?: string[];
  deny?: string[];
}

// ── Settings ─────────────────────────────────────────────────────────────────

export interface Settings {
  model: string;
  theme: ThemeName;
  defaultMode: PermissionMode;
  outputStyle: 'default' | 'verbose' | 'minimal';
  editorMode: 'vim' | 'normal';
  quality: 'low' | 'medium' | 'high';
  hooks: HooksConfig;
  permissions: PermissionRules;
  statusLine: string | null;
  disableAllHooks: boolean;
  promptColor: string;
}

export const DEFAULT_SETTINGS: Settings = {
  model: 'openai-default',
  theme: 'dark',
  defaultMode: 'default',
  outputStyle: 'verbose',
  editorMode: 'normal',
  quality: 'high',
  hooks: {},
  permissions: {},
  statusLine: null,
  disableAllHooks: false,
  promptColor: '#64B4FF',
};

// ── Session ──────────────────────────────────────────────────────────────────

export interface SessionCheckpoint {
  ts: number;
  concept: string;
  stage: StageName | null;
}

export interface Session {
  id: string;
  name: string | null;
  startedAt: string;
  concept: string;
  stage: StageName | null;
  checkpoints: SessionCheckpoint[];
  tokenUsage: TokenUsage;
  permissionMode: PermissionMode;
}

// ── Slash Commands ────────────────────────────────────────────────────────────

export type CommandCategory =
  | 'generation'
  | 'workspace'
  | 'navigation'
  | 'settings'
  | 'display'
  | 'tools'
  | 'memory'
  | 'session';

export interface AppDispatch {
  setScreen: (screen: string) => void;
  setPermissionMode: (mode: PermissionMode) => void;
  setVerboseMode: (v: boolean) => void;
  toggleVerboseMode: () => void;
  setThinkingVisible: (v: boolean) => void;
  setPromptColor: (color: string) => void;
  setCurrentModel: (model: string) => void;
  setTheme: (theme: ThemeName) => void;
  setQuality: (q: 'low' | 'medium' | 'high') => void;
  startPipeline: (concept: string) => void;
  resumePipeline: (dir: string) => void;
  retryPipeline: () => void;
  compactLogs: (instructions?: string) => void;
  exportSession: (filename?: string) => string | null;
  killPipeline: () => void;
  exit: () => void;
  showMessage: (text: string, color?: string) => void;
  setPromptText: (text: string) => void;
}

export interface SlashCommand {
  name: string;
  aliases: string[];
  description: string;
  args?: string;
  category: CommandCategory;
  handler: (args: string[], dispatch: AppDispatch) => void;
}

// ── Pipeline types ────────────────────────────────────────────────────────────

/** A single status update from the pipeline. */
export interface PipelineUpdate {
  stage: StageName;
  status: string;

  // Stage-specific
  num_segments?: number;
  storyboard?: Record<string, unknown>;
  tts_results?: Record<number, { success: boolean; error?: string; audio_path?: string; duration?: number }>;
  code_results?: Record<number, { video_path?: string; code?: string; error?: string; tool_call_counts?: Record<string, number> }>;

  // Segment-level (during code stage)
  segment_id?: number;
  segment_status?: string;
  segment_phase?: string;
  segment_final?: boolean;
  code?: string;

  // Streaming playback (emitted when a segment's stitch completes)
  playable_segment?: string;

  // Completion
  final?: boolean;
  error?: string;
  video_path?: string;
  project_dir?: string;
  timings?: Array<[string, string, number]>;
  total_elapsed_seconds?: number;
  tool_call_counts?: Record<string, number>;
  total_tool_calls?: number;
  stitch_errors?: string[];
  failed_segments?: Array<{ id: number; title: string; stage: string; error: string }>;
  runtime_metrics?: {
    planner_api_calls: number;
    segment_repairs: number;
    code_patch_repairs?: number;
    full_regen_repairs?: number;
    same_run_cache_hits: number;
    stitch_reencode_count: number;
    copy_trim_fast_paths?: number;
    stitch_mode_by_segment?: Record<string, string>;
  };

  // Token summary (emitted with the final "done" update)
  token_summary?: {
    total_input_tokens: number;
    total_output_tokens: number;
    cached_input_tokens?: number;
    total_api_calls: number;
    tts_api_calls?: number;
    estimated_cost_usd: number;
    estimated_cache_savings_usd?: number;
    fallback_invocations?: number;
    model_profile?: Record<string, string>;
    breakdown?: Record<string, {
      model?: string;
      input_tokens: number;
      output_tokens: number;
      cached_input_tokens?: number;
      api_calls: number;
      cost_usd: number;
    }>;
  };

  // Phase 5 extensions — token usage, thinking, tool calls
  token_usage?: { input: number; output: number; cache_read?: number };
  thinking?: string | boolean;
  tool_call?: { name: string; params: Record<string, unknown>; output?: string };
  tool_result?: { name: string; output: string };
  stream_event?: {
    channel: 'code' | 'thinking' | 'console';
    delta: string;
    snapshot?: string;
  };
  thinking_source?: 'raw_reasoning' | 'inferred_reasoning';
}

export type RunEventKind =
  | 'run_marker'
  | 'stage_transition'
  | 'stage_complete'
  | 'status'
  | 'activity'
  | 'segment_phase'
  | 'segment_terminal'
  | 'final'
  | 'diagnostic';

export type RunEventSource =
  | 'provider_stream'
  | 'tool_runtime'
  | 'pipeline_status'
  | 'ui_derived';

export type ReasoningKind =
  | 'raw_reasoning'
  | 'inferred_reasoning'
  | 'status_summary';

export interface RunEventToolPayload {
  name: string;
  params?: Record<string, unknown>;
  output_preview?: string;
}

export interface RunEventReasoningPayload {
  kind: ReasoningKind;
  text: string;
}

export interface InspectRow {
  id: string;
  event: RunEventRecord;
  summary: string;
  badges: string[];
  preview?: string;
  groupKey?: string;
  isExpandable: boolean;
}

export type BoardRowState = 'live' | 'warning' | 'done' | 'failed' | 'queued';

export type BoardActivityDot = 'reasoning' | 'tool' | 'code' | 'warning' | 'done';

export interface BoardRowModel {
  segmentId: number;
  title?: string;
  state: BoardRowState;
  statusPipState: BoardRowState;
  currentAction: string;
  primarySummary: string;
  secondarySummary?: string;
  reasoningLabel?: string;
  reasoningPreview?: string;
  toolPreview?: string;
  codePreview?: string[];
  selectedReasoningPreview?: string;
  selectedCodePreview?: string[];
  selectedToolPreview?: string;
  activityDots: BoardActivityDot[];
  updatedAgo?: string;
  lastUpdatedAt?: number;
  isExpandable: boolean;
}

export interface RunEventRecord {
  run_id: string;
  seq: number;
  ts: string;
  kind: RunEventKind;
  message: string;
  stage?: StageName | null;
  segment_id?: number;
  detail?: string;
  source?: RunEventSource;
  worker_role?: WorkerRole;
  channel?: 'code' | 'thinking' | 'console';
  tool?: RunEventToolPayload;
  reasoning?: RunEventReasoningPayload;
  data?: Record<string, unknown>;
}

export type QuestionnaireStage = 'goal' | 'refine';

export interface QuestionVisibilityRule {
  questionId: string;
  values: string[];
}

export interface QuestionVisibility {
  allOf?: QuestionVisibilityRule[];
  anyOf?: QuestionVisibilityRule[];
}

export interface QuestionOptionDef {
  value: string;
  label: string;
  description?: string;
  recommended?: boolean;
  summaryLabel?: string;
  mapsTo?: Record<string, string>;
}

export interface QuestionDef {
  id: string;
  question: string;
  options: Array<string | QuestionOptionDef>;
  default?: string;
  helperText?: string;
  stage?: QuestionnaireStage;
  summaryLabel?: string;
  showWhen?: QuestionVisibility;
}

export interface PreferencesSummaryItem {
  id: string;
  label: string;
  value: string;
  stage?: QuestionnaireStage;
}

/** Messages from Python runner (questionnaire + pipeline protocol). */
export type RunnerMessage =
  | { type: 'questions'; questions: QuestionDef[] }
  | { type: 'preferences_summary'; summary: string; summary_items?: PreferencesSummaryItem[] }
  | { type: 'pipeline'; update: PipelineUpdate }
  | { type: 'error'; message: string }
  | { type: 'token_usage'; input: number; output: number; cache_read?: number }
  | { type: 'thinking'; text: string }
  | { type: 'tool_call'; name: string; params: Record<string, unknown>; output?: string }
  | { type: 'permission_request'; operation: string; path?: string };

/** Arguments to pass to the pipeline runner. */
export interface PipelineArgs {
  concept: string;
  max_retries?: number;
  is_lite?: boolean;
  skip_audio?: boolean;
  resume_dir?: string;
  force_restart?: boolean;
  questionnaire_answers?: Record<string, unknown>;
  render_timeout?: number;
  tts_timeout?: number;
  // Phase 5-6 extensions
  system_prompt_prefix?: string;
  max_turns?: number;
  model?: string;
}

/** Completed stage info for display. */
export interface CompletedStage {
  name: StageName;
  summary: string;
  elapsed: number;
  status: 'ok' | 'failed';
  error?: string;
}

/** Per-segment state during code generation. */
export interface SegmentState {
  id: number;
  title?: string;
  phase: string;
  prettyPhase: string;
  attempt: number;
  done: boolean;
  failed: boolean;
  startedAt?: number;
  finishedAt?: number;
  updatedAt?: number;
  currentWorker?: WorkerRole;
  currentTask?: string;
  latestInference?: string;
  latestCodeSummary?: string;
  latestCheck?: string;
  latestWarning?: string;
  workerRoles?: WorkerRole[];
  workerStates?: Partial<Record<WorkerRole, WorkerStatus>>;
  completedBadges?: string[];
  trace?: SegmentTraceEntry[];
  liveCode?: string;
  liveThinking?: string;
  liveConsole?: string;
  latestReasoningKind?: ReasoningKind;
  // Agent activity (Claude Code-style display)
  isThinking?: boolean;
  thinkingText?: string;
  lastStatus?: string;
  lastToolCall?: { name: string; params: Record<string, unknown> };
  lastToolResult?: { name: string; output: string };
  /** First actionable hint shown when a segment fails. */
  failHint?: string;
}

export type WorkerRole =
  | 'planner'
  | 'tts'
  | 'coder'
  | 'verifier'
  | 'renderer'
  | 'stitcher';

export type WorkerStatus =
  | 'queued'
  | 'working'
  | 'blocked'
  | 'warning'
  | 'done'
  | 'failed';

export type SegmentTraceCategory =
  | 'status'
  | 'inference'
  | 'code'
  | 'check'
  | 'render'
  | 'warning'
  | 'completion';

export interface SegmentTraceEntry {
  id: string;
  category: SegmentTraceCategory;
  text: string;
  ts: number;
  workerRole?: WorkerRole;
}

/** A project entry from the workspace. */
export interface Project {
  dir: string;
  folder: string;
  concept: string;
  status: string;
  updated_at: string;
  progress_done: number;
  progress_total: number;
  progress_desc: string;
  // Enriched metadata (optional for backward compat)
  created_at?: string;
  total_segments?: number;
  total_time_secs?: number | null;
  estimated_cost_usd?: number | null;
  has_video?: boolean;
  video_path?: string | null;
  video_size_mb?: number | null;
}

/** UX-facing project badge state for workspace and onboarding surfaces. */
export type ProjectStateBadge = 'completed' | 'in_progress' | 'attention';

/** Recommended default action for a project row. */
export type ProjectPrimaryAction = 'resume' | 'rerun' | 'open_video' | 'view_summary';

/** Runtime activity grouping for status stream readability. */
export type ActivityGroup = 'doing' | 'checking' | 'fixing' | 'done';

/** Runtime activity severity to signal confidence and risk. */
export type ActivitySeverity = 'normal' | 'warning' | 'critical';

/** Progress display mode for run UI components. */
export type ProgressMode = 'determinate' | 'indeterminate';

/** Settings panel row with effective value and whether current scope overrides it. */
export interface EffectiveSettingRow {
  key: keyof Settings;
  effectiveValue: string;
  scopeValue: string;
  scopeOverride: boolean;
}

/** A tool call log entry. */
export interface ToolCallEntry {
  id: string;
  name: string;
  params: Record<string, unknown>;
  output?: string;
  collapsed: boolean;
}
