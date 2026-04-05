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
  model: 'claude-opus-4-6',
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

  // Completion
  final?: boolean;
  error?: string;
  video_path?: string;
  project_dir?: string;
  timings?: Array<[string, string, number]>;
  tool_call_counts?: Record<string, number>;
  total_tool_calls?: number;
  stitch_errors?: string[];

  // Token summary (emitted with the final "done" update)
  token_summary?: {
    total_input_tokens: number;
    total_output_tokens: number;
    total_api_calls: number;
    tts_api_calls?: number;
    estimated_cost_usd: number;
    breakdown?: Record<string, {
      input_tokens: number;
      output_tokens: number;
      api_calls: number;
      cost_usd: number;
    }>;
  };

  // Phase 5 extensions — token usage, thinking, tool calls
  token_usage?: { input: number; output: number; cache_read?: number };
  thinking?: string | boolean;
  tool_call?: { name: string; params: Record<string, unknown>; output?: string };
  tool_result?: { name: string; output: string };
}

/** Questionnaire question from Python. */
export interface QuestionDef {
  id: string;
  question: string;
  options: string[];
  default?: string;
}

/** Messages from Python runner (questionnaire + pipeline protocol). */
export type RunnerMessage =
  | { type: 'questions'; questions: QuestionDef[] }
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
  phase: string;
  prettyPhase: string;
  attempt: number;
  done: boolean;
  failed: boolean;
  startedAt?: number;
  finishedAt?: number;
  // Agent activity (Claude Code-style display)
  isThinking?: boolean;
  lastToolCall?: { name: string; params: Record<string, unknown> };
  lastToolResult?: { name: string; output: string };
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
}

/** A tool call log entry. */
export interface ToolCallEntry {
  id: string;
  name: string;
  params: Record<string, unknown>;
  output?: string;
  collapsed: boolean;
}
