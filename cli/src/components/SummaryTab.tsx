import React from 'react';
import { Box, Text } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import { SummaryTable } from './SummaryTable.js';
import { SuccessPanel } from './SuccessPanel.js';
import { ErrorPanel } from './ErrorPanel.js';
import type { CompletedStage, PipelineUpdate } from '../lib/types.js';

interface SummaryTabProps {
  completedStages: CompletedStage[];
  finalUpdate: PipelineUpdate | null;
  runState: 'active' | 'complete' | 'error';
  errorMessage?: string;
  totalToolCalls: number;
  toolCallCounts: Record<string, number>;
}

export function SummaryTab({
  completedStages,
  finalUpdate,
  runState,
  errorMessage,
  totalToolCalls,
  toolCallCounts,
}: SummaryTabProps) {
  const { themeColors } = useAppContext();

  if (runState === 'active' && completedStages.length === 0) {
    return (
      <Box paddingLeft={1}>
        <Text color={themeColors.dim}>Pipeline is running. Summary will appear as stages complete.</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" paddingLeft={1}>
      {/* Summary table — works for both partial and complete data */}
      <SummaryTable
        stages={completedStages}
        timings={finalUpdate?.timings}
        totalElapsedSeconds={finalUpdate?.total_elapsed_seconds}
        toolCallCounts={runState !== 'active' ? toolCallCounts : undefined}
        totalToolCalls={runState !== 'active' ? totalToolCalls : 0}
        tokenSummary={finalUpdate?.token_summary}
      />

      {/* Success panel */}
      {runState === 'complete' && finalUpdate?.video_path && (
        <SuccessPanel videoPath={finalUpdate.video_path} />
      )}

      {/* Error panel */}
      {runState === 'error' && (
        <ErrorPanel
          message={errorMessage ?? 'Pipeline failed'}
          failedSegments={finalUpdate?.failed_segments}
          numSegments={finalUpdate?.num_segments}
          videoPath={finalUpdate?.video_path}
          projectDir={finalUpdate?.project_dir}
          tokenSummary={finalUpdate?.token_summary}
          stages={completedStages}
        />
      )}

      {/* Navigation hint on completion */}
      {runState !== 'active' && (
        <Box marginTop={1}>
          <Text color={themeColors.dim}>
            Press 2 to browse generated code · 1 for overview · 4 for full event timeline
          </Text>
        </Box>
      )}
    </Box>
  );
}
