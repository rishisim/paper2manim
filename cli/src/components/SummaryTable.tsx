import React from 'react';
import { Box, Text } from 'ink';
import { stageConfig, colors, type StageName } from '../lib/theme.js';
import type { CompletedStage } from '../lib/types.js';

interface SummaryTableProps {
  stages: CompletedStage[];
  toolCallCounts?: Record<string, number>;
  totalToolCalls?: number;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${seconds.toFixed(1)}s [${m}m ${s.toString().padStart(2, '0')}s]`;
}

export function SummaryTable({ stages, toolCallCounts, totalToolCalls }: SummaryTableProps) {
  const total = stages.reduce((sum, s) => sum + s.elapsed, 0);

  return (
    <Box flexDirection="column" marginTop={1} paddingLeft={1}>
      <Text bold>Pipeline Summary</Text>
      <Text>{''}</Text>
      {stages.map((stage, i) => {
        const config = stageConfig[stage.name] ?? stageConfig.done;
        const icon = stage.status === 'ok' ? 'OK' : 'ERR';
        const iconColor = stage.status === 'ok' ? colors.success : colors.error;
        const dur = formatDuration(stage.elapsed);
        const label = config.label.padEnd(28);

        return (
          <Text key={i}>
            <Text color={iconColor}>{icon}</Text>
            <Text> {label}</Text>
            <Text color={colors.dim}>{dur}</Text>
          </Text>
        );
      })}
      <Text color={colors.dim}>{'─'.repeat(40)}</Text>
      <Box>
        <Text bold>  {'Total'.padEnd(27)}</Text>
        <Text bold>{formatDuration(total)}</Text>
      </Box>

      {totalToolCalls !== undefined && totalToolCalls > 0 && (
        <>
          <Text>{''}</Text>
          <Text color={colors.dim}>Tool calls: {totalToolCalls}</Text>
          {toolCallCounts && Object.entries(toolCallCounts).map(([name, count]) => (
            <Text key={name} color={colors.dim}>  {name}: {count}</Text>
          ))}
        </>
      )}
    </Box>
  );
}
