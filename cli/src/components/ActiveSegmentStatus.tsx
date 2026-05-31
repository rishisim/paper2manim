import React from 'react';
import { Box, Text } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';
import { useBrailleSpinner, getSpinnerChar, segmentToSpinnerState } from '../hooks/useBrailleSpinner.js';
import { workerLabel } from '../lib/segmentBoard.js';
import { formatToolCall } from '../lib/format.js';
import type { SegmentState } from '../lib/types.js';

interface ActiveSegmentStatusProps {
  segment?: SegmentState;
}

export function ActiveSegmentStatus({ segment }: ActiveSegmentStatusProps) {
  const { themeColors } = useAppContext();
  const termWidth = useTerminalWidth();
  const frame = useBrailleSpinner();

  if (!segment || segment.done || segment.failed) {
    return null;
  }

  const spinnerState = segmentToSpinnerState(segment);
  const spinnerChar = getSpinnerChar(frame, spinnerState);
  const spinnerColor = spinnerState === 'thinking'
    ? themeColors.accent
    : spinnerState === 'rendering'
      ? themeColors.accent
      : themeColors.primary;

  const worker = segment.currentWorker ? workerLabel(segment.currentWorker) : 'Worker';
  const task = segment.currentTask ?? segment.prettyPhase;

  // Build tool info
  let toolInfo = '';
  if (segment.lastToolCall) {
    toolInfo = formatToolCall(segment.lastToolCall.name, segment.lastToolCall.params);
  }

  const parts = [task, toolInfo].filter(Boolean);
  const statusText = parts.join(' · ');
  const maxLen = Math.max(30, termWidth - 8);
  const displayText = statusText.length > maxLen
    ? statusText.slice(0, maxLen - 1) + '…'
    : statusText;

  return (
    <Box paddingLeft={2} marginTop={1}>
      <Text color={spinnerColor}>{spinnerChar} </Text>
      <Text color={themeColors.muted}>{displayText}</Text>
    </Box>
  );
}
