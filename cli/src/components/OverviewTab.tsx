import React from 'react';
import { Box, Text } from 'ink';
import { getStageConfig, type StageName } from '../lib/theme.js';
import { useAppContext } from '../context/AppContext.js';
import { SegmentStatus } from './SegmentStatus.js';
import { AgentActivityPanel } from './AgentActivityPanel.js';
import { collapseActivityLines, type ActivityLine } from './StatusBar.js';
import type { CompletedStage, SegmentState } from '../lib/types.js';

// The main stages shown in the pipeline diagram (ordered)
const PIPELINE_STAGES: StageName[] = ['plan', 'tts', 'code', 'render', 'concat'];

// Short labels for the pipeline diagram
const SHORT_LABELS: Record<string, string> = {
  plan: 'Plan',
  tts: 'TTS',
  code: 'Code',
  render: 'Render',
  concat: 'Assemble',
};

interface OverviewTabProps {
  currentStage: StageName | null;
  completedStages: CompletedStage[];
  segments: Map<number, SegmentState>;
  activityLines: ActivityLine[];
  totalSegments: number;
  verbose: boolean;
  runState: 'active' | 'complete' | 'error';
}

export function OverviewTab({
  currentStage,
  completedStages,
  segments,
  activityLines,
  totalSegments,
  verbose,
  runState,
}: OverviewTabProps) {
  const { themeColors } = useAppContext();
  const stageConfig = getStageConfig(themeColors);
  const completedNames = new Set(completedStages.map(s => s.name));
  // 'code_retry' counts as 'code', 'stitch'/'timing' as part of 'render', etc.
  const activeStage = currentStage === 'code_retry' ? 'code' :
    currentStage === 'stitch' || currentStage === 'timing' ? 'render' :
    currentStage === 'subtitles' || currentStage === 'overlay' ? 'concat' :
    currentStage === 'pipeline' ? 'tts' :
    currentStage;

  const collapsed = collapseActivityLines(activityLines).slice(-3);

  return (
    <Box flexDirection="column" paddingLeft={1}>
      {/* Stage Pipeline Diagram */}
      <Box marginBottom={1}>
        {PIPELINE_STAGES.map((stage, idx) => {
          const config = stageConfig[stage];
          const isDone = completedNames.has(stage) ||
            (stage === 'tts' && (completedNames.has('tts') || completedNames.has('pipeline'))) ||
            (stage === 'code' && (completedNames.has('code') || completedNames.has('code_retry'))) ||
            (stage === 'render' && completedNames.has('render')) ||
            (stage === 'concat' && (runState === 'complete'));
          const isActive = activeStage === stage && runState === 'active';
          const isFailed = runState === 'error' && activeStage === stage;

          const icon = isDone ? '✔' : isFailed ? '✘' : isActive ? '●' : '·';
          const color = isDone ? themeColors.success :
            isFailed ? themeColors.error :
            isActive ? config.color :
            themeColors.dim;

          return (
            <React.Fragment key={stage}>
              <Text color={color} bold={isActive}>
                {icon} {SHORT_LABELS[stage] ?? stage}
              </Text>
              {idx < PIPELINE_STAGES.length - 1 && (
                <Text color={themeColors.dim}> → </Text>
              )}
            </React.Fragment>
          );
        })}
      </Box>

      {/* Segment Health */}
      {(segments.size > 0 || totalSegments > 0) && (
        <Box flexDirection="column" marginBottom={1}>
          <Text bold color={themeColors.primary}>Segments</Text>
          {segments.size > 0 ? (
            <SegmentStatus segments={segments} verbose={verbose} />
          ) : (
            <Box paddingLeft={2}>
              <Text color={themeColors.dim}>
                Waiting for {totalSegments} segment{totalSegments === 1 ? '' : 's'}...
              </Text>
            </Box>
          )}
        </Box>
      )}

      {/* Agent Activity (during code stages) */}
      {(currentStage === 'code' || currentStage === 'code_retry') && segments.size > 0 && runState === 'active' && (
        <Box flexDirection="column" marginBottom={1}>
          <Text bold color={themeColors.primary}>Agent Activity</Text>
          <AgentActivityPanel segments={segments} verbose={verbose} />
        </Box>
      )}

      {/* Recent Activity Stream (compact) */}
      {collapsed.length > 0 && (
        <Box flexDirection="column">
          <Text bold color={themeColors.primary}>Recent Activity</Text>
          {collapsed.map(line => (
            <Box key={line.id} paddingLeft={2}>
              <Text color={themeColors.dim} wrap="truncate">{line.text}</Text>
            </Box>
          ))}
        </Box>
      )}
    </Box>
  );
}
