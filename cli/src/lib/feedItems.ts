/**
 * FeedItem — structured items for the Claude Code-style streaming feed.
 *
 * Each item represents a discrete event in the pipeline run:
 * stage transitions, segment headers, activity (tool calls, thinking, diffs),
 * code snapshots, and completion/error summaries.
 */

import type { StageName } from './theme.js';
import type { ActivityLine } from '../components/StatusBar.js';
import type { CompletedStage, PipelineUpdate, RunEventRecord } from './types.js';

export interface FailedSegment {
  id: number;
  title: string;
  stage: string;
  error: string;
}

export type FeedItem =
  | { type: 'stage_header'; id: string; stage: StageName; status: 'active' | 'complete' | 'error' }
  | { type: 'segment_header'; id: string; segmentId: number; label: string; status: 'active' | 'done' | 'failed'; elapsed?: number; attempt?: number }
  | { type: 'activity'; id: string; line: ActivityLine; segmentId?: number; eventId?: string; event?: RunEventRecord }
  | { type: 'code_snapshot'; id: string; segmentId: number; code: string; summary: string }
  | { type: 'completion'; id: string; finalUpdate: PipelineUpdate; completedStages: CompletedStage[] }
  | { type: 'error'; id: string; message: string; failedSegments?: FailedSegment[]; projectDir?: string; videoPath?: string; completedStages?: CompletedStage[]; tokenSummary?: PipelineUpdate['token_summary'] };

/** Input type for addFeedItem — same as FeedItem but without `id` (auto-generated). */
export type FeedItemInput =
  | { type: 'stage_header'; stage: StageName; status: 'active' | 'complete' | 'error' }
  | { type: 'segment_header'; segmentId: number; label: string; status: 'active' | 'done' | 'failed'; elapsed?: number; attempt?: number }
  | { type: 'activity'; line: ActivityLine; segmentId?: number; eventId?: string; event?: RunEventRecord }
  | { type: 'code_snapshot'; segmentId: number; code: string; summary: string }
  | { type: 'completion'; finalUpdate: PipelineUpdate; completedStages: CompletedStage[] }
  | { type: 'error'; message: string; failedSegments?: FailedSegment[]; projectDir?: string; videoPath?: string; completedStages?: CompletedStage[]; tokenSummary?: PipelineUpdate['token_summary'] };
