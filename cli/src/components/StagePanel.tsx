import React from 'react';
import { Box, Text } from 'ink';
import { getStageConfig, RESULT_MARKER, type StageName } from '../lib/theme.js';
import { formatDuration } from '../lib/format.js';
import { useAppContext } from '../context/AppContext.js';

interface StagePanelProps {
  name: StageName;
  summary: string;
  elapsed: number;
  status: 'ok' | 'failed';
  error?: string;
  toolCallCount?: number;
}

export function StagePanel({ name, elapsed, status, error, toolCallCount }: StagePanelProps) {
  const { themeColors } = useAppContext();
  const stageConfig = getStageConfig(themeColors);
  const config = stageConfig[name] ?? stageConfig.done;
  const statusIcon = status === 'ok' ? '✔' : '✘';
  const iconColor = status === 'ok' ? themeColors.success : themeColors.error;
  const durationStr = formatDuration(elapsed);

  return (
    <Box flexDirection="column" paddingLeft={1} marginTop={1}>
      <Text>
        <Text color={iconColor} bold>{statusIcon}</Text>
        <Text bold> {config.label}</Text>
        <Text color={themeColors.dim}>  {durationStr}</Text>
        {toolCallCount !== undefined && toolCallCount > 0 && (
          <Text color={themeColors.dim}>  ({toolCallCount} calls)</Text>
        )}
      </Text>
      {error && status === 'failed' && (
        <Box paddingLeft={2}>
          <Text color={themeColors.dim}>{RESULT_MARKER} {error}</Text>
        </Box>
      )}
    </Box>
  );
}

/** Inline header printed when a stage starts. */
export function StageHeader({ name }: { name: StageName }) {
  const { themeColors } = useAppContext();
  const stageConfig = getStageConfig(themeColors);
  const config = stageConfig[name] ?? stageConfig.done;

  return (
    <Box paddingLeft={1} marginTop={1}>
      <Text bold>{config.label}</Text>
    </Box>
  );
}
