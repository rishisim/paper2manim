import React from 'react';
import { Box, Text } from 'ink';
import { getStageConfig, type StageName } from '../lib/theme.js';
import { formatDuration, renderProgressBar, renderProgressBarAscii, renderIndeterminateProgressBar } from '../lib/format.js';
import { useAppContext } from '../context/AppContext.js';
import { useClaudeSpinner } from '../hooks/useClaudeSpinner.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';
import type { ProgressMode } from '../lib/types.js';

interface ProgressStripProps {
  stage: StageName | null;
  elapsed: number;
  segmentsCompleted: number;
  totalSegments: number;
  progressPct: number;
  progressMode: ProgressMode;
  runState: 'active' | 'complete' | 'error';
}

export function ProgressStrip({
  stage,
  elapsed,
  segmentsCompleted,
  totalSegments,
  progressPct,
  progressMode,
  runState,
}: ProgressStripProps) {
  const { themeColors } = useAppContext();
  const stageConfig = getStageConfig(themeColors);
  const config = stage && stage !== 'done' ? stageConfig[stage] ?? stageConfig.plan : stageConfig.plan;
  const spinnerChar = useClaudeSpinner();
  const termWidth = useTerminalWidth();

  const deterministic = progressMode === 'determinate';
  const barWidth = termWidth < 84 ? 10 : termWidth < 110 ? 14 : 20;
  const frame = Math.floor(elapsed * 8);
  const pct = Math.max(0, Math.min(100, progressPct));

  const noStageYet = runState === 'active' && (!stage || stage === 'done');
  const bar = runState === 'complete'
    ? (termWidth >= 84 ? renderProgressBar(100, barWidth) : renderProgressBarAscii(100, barWidth))
    : runState === 'error'
      ? (termWidth >= 84 ? renderProgressBar(pct, barWidth) : renderProgressBarAscii(pct, barWidth))
      : noStageYet
        ? renderIndeterminateProgressBar(frame, barWidth)
        : deterministic
          ? (termWidth >= 84 ? renderProgressBar(pct, barWidth) : renderProgressBarAscii(pct, barWidth))
          : renderIndeterminateProgressBar(frame, barWidth);

  const icon = runState === 'complete' ? '✔' : runState === 'error' ? '✘' : spinnerChar;
  const iconColor = runState === 'complete' ? themeColors.success : runState === 'error' ? themeColors.error : config.color;
  const label = runState === 'complete' ? 'Complete' : runState === 'error' ? 'Failed' : stage && stage !== 'done' ? config.label : 'Starting...';

  const showSegments = totalSegments > 0;

  return (
    <Box paddingLeft={1}>
      <Text color={iconColor}>{icon} </Text>
      <Text bold color={iconColor}>{label}</Text>
      <Text color={themeColors.muted}>  {formatDuration(elapsed)}  </Text>
      <Text color={deterministic || runState !== 'active' ? themeColors.progressFill : themeColors.warn}>{bar}</Text>
      {showSegments && (
        <Text color={themeColors.muted}>  {segmentsCompleted}/{totalSegments}</Text>
      )}
      <Text color={themeColors.muted}>  {runState === 'complete' ? '100%' : `${Math.round(pct)}%`}</Text>
    </Box>
  );
}
