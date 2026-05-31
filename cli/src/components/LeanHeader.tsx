import React from 'react';
import { Box, Text } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';
import { useBrailleSpinner, getSpinnerChar } from '../hooks/useBrailleSpinner.js';
import { BRAND_ICON, VERSION, getStageConfig } from '../lib/theme.js';
import { formatDuration } from '../lib/format.js';
import type { StageName } from '../lib/theme.js';
import type { ProgressMode } from '../lib/types.js';

interface LeanHeaderProps {
  concept: string;
  stage: StageName | null;
  elapsed: number;
  segmentsDone: number;
  totalSegments: number;
  progressPct: number;
  progressMode: ProgressMode;
  runState: 'active' | 'complete' | 'error';
}

export function LeanHeader({
  concept,
  stage,
  elapsed,
  segmentsDone,
  totalSegments,
  progressPct,
  progressMode,
  runState,
}: LeanHeaderProps) {
  const { themeColors } = useAppContext();
  const termWidth = useTerminalWidth();
  const frame = useBrailleSpinner();

  const stageConfig = getStageConfig(themeColors);
  const stageLabel = stage && stage !== 'done'
    ? (stageConfig[stage]?.label ?? stage)
    : runState === 'complete'
      ? 'Complete'
      : runState === 'error'
        ? 'Failed'
        : 'Starting';

  const spinner = runState === 'active'
    ? getSpinnerChar(frame, 'coding')
    : runState === 'complete'
      ? '✔'
      : '✘';
  const spinnerColor = runState === 'active'
    ? themeColors.primary
    : runState === 'complete'
      ? themeColors.success
      : themeColors.error;

  const pctStr = progressMode === 'determinate'
    ? `${Math.round(progressPct)}%`
    : 'estimating';

  const segStr = totalSegments > 0 ? `${segmentsDone}/${totalSegments}` : '';

  // Right side: spinner + stage + elapsed + segments + progress
  const rightParts = [
    stageLabel,
    formatDuration(elapsed),
    segStr,
    pctStr,
  ].filter(Boolean);
  const rightText = rightParts.join(' · ');

  // Left side: brand + concept (truncated to fit)
  const brand = `${BRAND_ICON} paper2manim`;
  const rightLen = rightText.length + 4; // spinner + spaces
  const maxConceptLen = Math.max(10, termWidth - brand.length - rightLen - 6);
  const displayConcept = concept.length > maxConceptLen
    ? concept.slice(0, maxConceptLen - 1) + '…'
    : concept;

  const separator = '─'.repeat(Math.max(20, termWidth - 2));

  return (
    <Box flexDirection="column" paddingX={1}>
      <Box justifyContent="space-between">
        <Text>
          <Text bold color={themeColors.primary}>{BRAND_ICON}</Text>
          <Text bold color={themeColors.text}> paper2manim</Text>
          {concept && <Text color={themeColors.muted}> — {displayConcept}</Text>}
        </Text>
        <Text>
          <Text color={spinnerColor}>{spinner} </Text>
          <Text color={themeColors.muted}>{rightText}</Text>
        </Text>
      </Box>
      <Text color={themeColors.separator}>{separator}</Text>
    </Box>
  );
}
