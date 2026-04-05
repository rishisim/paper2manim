import React from 'react';
import { Box, Text } from 'ink';
import { getStageConfig, RESULT_MARKER } from '../lib/theme.js';
import { formatDuration } from '../lib/format.js';
import { useAppContext } from '../context/AppContext.js';
import type { CompletedStage } from '../lib/types.js';

interface SummaryTableProps {
  stages: CompletedStage[];
  toolCallCounts?: Record<string, number>;
  totalToolCalls?: number;
}

export function SummaryTable({ stages, toolCallCounts, totalToolCalls }: SummaryTableProps) {
  const { themeColors } = useAppContext();
  const stageConfig = getStageConfig(themeColors);
  const total = stages.reduce((sum, s) => sum + s.elapsed, 0);

  return (
    <Box flexDirection="column" marginTop={1} paddingLeft={1}>
      <Text bold>Pipeline Summary</Text>
      {stages.map((stage, i) => {
        const config = stageConfig[stage.name] ?? stageConfig.done;
        const icon = stage.status === 'ok' ? '✔' : '✘';
        const iconColor = stage.status === 'ok' ? themeColors.success : themeColors.error;
        const dur = formatDuration(stage.elapsed);
        const label = config.label.padEnd(28);

        return (
          <Text key={i}>
            <Text color={iconColor} bold>{icon}</Text>
            <Text> {label}</Text>
            <Text color={themeColors.dim}>{dur}</Text>
          </Text>
        );
      })}
      <Text color={themeColors.separator}>{'─'.repeat(40)}</Text>
      <Box>
        <Text bold>  {'Total'.padEnd(27)}</Text>
        <Text bold>{formatDuration(total)}</Text>
      </Box>

      {totalToolCalls !== undefined && totalToolCalls > 0 && (
        <Box flexDirection="column" marginTop={1}>
          <Text color={themeColors.muted}>{RESULT_MARKER} Tool calls: {totalToolCalls}</Text>
          {toolCallCounts && Object.entries(toolCallCounts).map(([name, count]) => (
            <Text key={name} color={themeColors.dim}>    {name}: {count}</Text>
          ))}
        </Box>
      )}
    </Box>
  );
}
