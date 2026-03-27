import React from 'react';
import { Box, Text } from 'ink';
import { stageConfig, colors, type StageName } from '../lib/theme.js';

interface StagePanelProps {
  name: StageName;
  summary: string;
  elapsed: number;
  status: 'ok' | 'failed';
  error?: string;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${seconds.toFixed(1)}s [${m}m ${s.toString().padStart(2, '0')}s]`;
}

export function StagePanel({ name, elapsed, status, error }: StagePanelProps) {
  const config = stageConfig[name] ?? stageConfig.done;
  const statusIcon = status === 'ok' ? 'OK' : 'ERR';
  const iconColor = status === 'ok' ? colors.success : colors.error;
  const durationStr = formatDuration(elapsed);

  return (
    <Box flexDirection="column" paddingLeft={1} marginTop={1}>
      <Text>
        <Text color={iconColor} bold>{statusIcon}</Text>
        <Text bold> {config.label}</Text>
        <Text color={colors.dim}>  {durationStr}</Text>
      </Text>
      {error && status === 'failed' && (
        <Text color={colors.dim}>      {error}</Text>
      )}
    </Box>
  );
}

/** Inline header printed when a stage starts. */
export function StageHeader({ name }: { name: StageName }) {
  const config = stageConfig[name] ?? stageConfig.done;

  return (
    <Box paddingLeft={1} marginTop={1}>
      <Text bold>{config.label}</Text>
    </Box>
  );
}
