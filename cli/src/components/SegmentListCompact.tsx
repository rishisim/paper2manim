import React from 'react';
import { Box, Text } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';
import { useBrailleSpinner, getSpinnerChar, segmentToSpinnerState } from '../hooks/useBrailleSpinner.js';
import type { BoardRowModel, SegmentState } from '../lib/types.js';

interface SegmentListCompactProps {
  boardRows: BoardRowModel[];
  segments: Map<number, SegmentState>;
  selectedSegmentId?: number;
  scrollOffset: number;
  maxVisible: number;
}

export function SegmentListCompact({
  boardRows,
  segments,
  selectedSegmentId,
  scrollOffset,
  maxVisible,
}: SegmentListCompactProps) {
  const { themeColors } = useAppContext();
  const termWidth = useTerminalWidth();
  const frame = useBrailleSpinner();

  if (boardRows.length === 0) {
    return (
      <Box paddingLeft={1} marginTop={1}>
        <Text color={themeColors.dim}>Waiting for segments…</Text>
      </Box>
    );
  }

  const start = Math.max(0, Math.min(scrollOffset, Math.max(0, boardRows.length - maxVisible)));
  const end = Math.min(boardRows.length, start + maxVisible);
  const visible = boardRows.slice(start, end);

  return (
    <Box flexDirection="column" marginTop={1} paddingLeft={1}>
      {start > 0 && <Text color={themeColors.dim}>  ↑ {start} more</Text>}
      {visible.map(row => {
        const seg = segments.get(row.segmentId);
        const spinnerState = seg ? segmentToSpinnerState(seg) : 'queued';
        const spinnerChar = getSpinnerChar(frame, spinnerState);
        const isSelected = row.segmentId === selectedSegmentId;
        const spinnerColor = spinnerStateColor(spinnerState, themeColors);

        // Build columns: prefix + spinner + id/title ... action ... age
        const prefix = isSelected ? '›' : ' ';
        const idTitle = row.title
          ? `S${row.segmentId} ${row.title}`
          : `S${row.segmentId}`;
        const action = row.currentAction || '';
        const age = row.updatedAgo || '';

        // Calculate available space for title and action
        const fixedWidth = 6 + age.length + 4; // prefix+spinner+space + age + padding
        const availableForContent = Math.max(30, termWidth - fixedWidth);
        const titleMaxLen = Math.floor(availableForContent * 0.45);
        const actionMaxLen = Math.max(10, availableForContent - titleMaxLen - 2);

        const displayTitle = truncate(idTitle, titleMaxLen);
        const displayAction = truncate(action, actionMaxLen);

        // Pad title to align actions
        const titlePadded = displayTitle.padEnd(titleMaxLen);

        return (
          <Text key={`seg-${row.segmentId}`}>
            <Text color={isSelected ? themeColors.text : themeColors.dim}>{prefix} </Text>
            <Text color={spinnerColor}>{spinnerChar} </Text>
            <Text bold={isSelected} color={isSelected ? themeColors.text : themeColors.muted}>
              {titlePadded}
            </Text>
            <Text color={isSelected ? themeColors.muted : themeColors.dim}>
              {'  '}{displayAction}
            </Text>
            {age && (
              <Text color={themeColors.dim}>{'  '}{age}</Text>
            )}
          </Text>
        );
      })}
      {end < boardRows.length && <Text color={themeColors.dim}>  ↓ {boardRows.length - end} more</Text>}
    </Box>
  );
}

function spinnerStateColor(
  state: ReturnType<typeof segmentToSpinnerState>,
  themeColors: ReturnType<typeof useAppContext>['themeColors'],
): string {
  switch (state) {
    case 'done': return themeColors.success;
    case 'failed': return themeColors.error;
    case 'queued': return themeColors.dim;
    case 'thinking': return themeColors.accent;
    case 'rendering': return themeColors.accent;
    case 'coding': return themeColors.primary;
    default: return themeColors.primary;
  }
}

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, Math.max(0, maxLen - 1)) + '…';
}
