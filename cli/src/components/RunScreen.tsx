import React from 'react';
import { Box } from 'ink';
import { useTerminalHeight } from '../hooks/useTerminalHeight.js';
import { getStageConfig } from '../lib/theme.js';
import { useAppContext } from '../context/AppContext.js';
import { LeanHeader } from './LeanHeader.js';
import { SegmentListCompact } from './SegmentListCompact.js';
import { LiveCodePanel } from './LiveCodePanel.js';
import { ActiveSegmentStatus } from './ActiveSegmentStatus.js';
import { SummaryTable } from './SummaryTable.js';
import { SuccessPanel } from './SuccessPanel.js';
import { ErrorPanel } from './ErrorPanel.js';
import type { StageName } from '../lib/theme.js';
import type {
  BoardRowModel,
  CompletedStage,
  PipelineUpdate,
  ProgressMode,
  SegmentState,
} from '../lib/types.js';

export interface RunScreenErrorInfo {
  message: string;
  failedSegments?: Array<{ id: number; title: string; stage: string; error: string }>;
  projectDir?: string;
  videoPath?: string;
  tokenSummary?: {
    estimated_cost_usd: number;
    total_api_calls: number;
  } | null;
}

interface RunScreenProps {
  concept: string;
  stage: StageName | null;
  elapsed: number;
  runState: 'active' | 'complete' | 'error';
  segments: Map<number, SegmentState>;
  segmentCodes: Map<number, string>;
  boardRows: BoardRowModel[];
  totalSegments: number;
  progressPct: number;
  progressMode: ProgressMode;
  selectedSegmentId?: number;
  scrollOffset: number;
  completedStages: CompletedStage[];
  finalUpdate?: PipelineUpdate;
  errorInfo?: RunScreenErrorInfo;
}

export function RunScreen({
  concept,
  stage,
  elapsed,
  runState,
  segments,
  segmentCodes,
  boardRows,
  totalSegments,
  progressPct,
  progressMode,
  selectedSegmentId,
  scrollOffset,
  completedStages,
  finalUpdate,
  errorInfo,
}: RunScreenProps) {
  const { themeColors } = useAppContext();
  const termHeight = useTerminalHeight();

  const orderedSegments = [...segments.values()].sort((a, b) => a.id - b.id);
  const doneCount = orderedSegments.filter(seg => seg.done).length;

  // Calculate layout sizes
  const segmentListSize = Math.min(boardRows.length, 8);
  // header(2) + segmentList + status(1) + footer(3) + margins(3)
  const chromeLines = 2 + segmentListSize + 1 + 3 + 3;
  const maxCodeLines = Math.max(8, termHeight - chromeLines);

  // Determine which segment to show code for
  const activeSegId = selectedSegmentId ?? findActiveSegmentId(orderedSegments);
  const activeSeg = activeSegId !== undefined ? segments.get(activeSegId) : undefined;
  const activeCode = activeSegId !== undefined
    ? (activeSeg?.liveCode ?? segmentCodes.get(activeSegId) ?? '')
    : '';
  const isStreaming = activeSeg ? !activeSeg.done && !activeSeg.failed : false;

  return (
    <Box flexDirection="column">
      <LeanHeader
        concept={concept}
        stage={stage}
        elapsed={elapsed}
        segmentsDone={doneCount}
        totalSegments={totalSegments || orderedSegments.length}
        progressPct={progressPct}
        progressMode={progressMode}
        runState={runState}
      />

      <SegmentListCompact
        boardRows={boardRows}
        segments={segments}
        selectedSegmentId={activeSegId}
        scrollOffset={scrollOffset}
        maxVisible={segmentListSize}
      />

      {runState === 'complete' && finalUpdate ? (
        <Box flexDirection="column" marginTop={1} paddingLeft={1}>
          <SummaryTable
            stages={completedStages}
            timings={finalUpdate.timings}
            totalElapsedSeconds={finalUpdate.total_elapsed_seconds}
            toolCallCounts={finalUpdate.tool_call_counts}
            totalToolCalls={finalUpdate.total_tool_calls}
            tokenSummary={finalUpdate.token_summary}
          />
          {finalUpdate.video_path && <SuccessPanel videoPath={finalUpdate.video_path} />}
        </Box>
      ) : runState === 'error' && errorInfo ? (
        <Box flexDirection="column" marginTop={1} paddingLeft={1}>
          <ErrorPanel
            message={errorInfo.message}
            failedSegments={errorInfo.failedSegments}
            projectDir={errorInfo.projectDir}
            videoPath={errorInfo.videoPath}
            stages={completedStages}
            tokenSummary={errorInfo.tokenSummary}
          />
        </Box>
      ) : (
        <>
          <LiveCodePanel
            code={activeCode}
            segmentId={activeSegId ?? 0}
            segmentTitle={activeSeg?.title}
            isStreaming={isStreaming}
            maxLines={maxCodeLines}
          />
          <ActiveSegmentStatus segment={activeSeg} />
        </>
      )}
    </Box>
  );
}

/** Find the first non-done, non-failed segment (the one currently being worked on). */
function findActiveSegmentId(segments: SegmentState[]): number | undefined {
  const active = segments.find(seg => !seg.done && !seg.failed && seg.updatedAt);
  if (active) return active.id;
  // Fallback: last done segment, or first segment
  const lastDone = [...segments].reverse().find(seg => seg.done);
  return lastDone?.id ?? segments[0]?.id;
}
