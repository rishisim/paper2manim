/**
 * TypeScript types for the Python pipeline NDJSON protocol.
 */

import type { StageName } from './theme.js';

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
  | { type: 'error'; message: string };

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
