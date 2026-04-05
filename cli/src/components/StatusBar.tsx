/**
 * StatusBar — Claude Code-style activity stream during pipeline execution.
 *
 * Shows the last N activity lines (tool calls, thinking, status updates)
 * scrolling like Claude Code, instead of a single detail line + progress bar.
 * The stage name + elapsed time header remains at the top.
 */

import React from 'react';
import { Box, Text } from 'ink';
import { getStageConfig, RESULT_MARKER, type StageName } from '../lib/theme.js';
import { formatDuration } from '../lib/format.js';
import { useAppContext } from '../context/AppContext.js';
import { useClaudeSpinner } from '../hooks/useClaudeSpinner.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';

export interface ActivityLine {
  id: string;
  type: 'tool_call' | 'thinking' | 'status' | 'tool_result';
  text: string;
  /** Optional secondary text (e.g., tool result preview) */
  detail?: string;
}

interface StatusBarProps {
  stage: StageName;
  elapsed: number;
  /** Recent activity lines to display (newest last) */
  activity: ActivityLine[];
  /** Max lines to show in the live region */
  maxLines?: number;
}

export function StatusBar({ stage, elapsed, activity, maxLines = 6 }: StatusBarProps) {
  const { themeColors } = useAppContext();
  const stageConfig = getStageConfig(themeColors);
  const config = stageConfig[stage] ?? stageConfig.done;
  const spinnerChar = useClaudeSpinner();
  const termWidth = useTerminalWidth();

  // Show only the last N activity lines
  const visible = activity.slice(-maxLines);

  return (
    <Box flexDirection="column" paddingLeft={1} marginTop={1}>
      {/* Stage header: spinner + stage label + duration */}
      <Box>
        <Text color={config.color}>{spinnerChar} </Text>
        <Text bold color={config.color}>{config.label}</Text>
        <Text color={themeColors.muted}>  {formatDuration(elapsed)}</Text>
      </Box>

      {/* Activity stream */}
      {visible.map((line) => (
        <ActivityLineRow key={line.id} line={line} termWidth={termWidth} />
      ))}
    </Box>
  );
}

/** Truncate text to fit terminal width with ellipsis. */
function truncateLine(text: string, maxWidth: number, indent: number): string {
  const available = maxWidth - indent - 1; // -1 for safety margin
  if (available <= 0 || text.length <= available) return text;
  return text.slice(0, available - 1) + '…';
}

function ActivityLineRow({ line, termWidth }: { line: ActivityLine; termWidth: number }) {
  const { themeColors } = useAppContext();

  if (line.type === 'thinking') {
    return (
      <Box paddingLeft={2}>
        <Text color={themeColors.dim} italic>
          {truncateLine(line.text, termWidth, 4)}
        </Text>
      </Box>
    );
  }

  if (line.type === 'tool_call') {
    return (
      <Box flexDirection="column">
        <Box paddingLeft={2}>
          <Text color={themeColors.accent} bold>{RESULT_MARKER} </Text>
          <Text bold>{line.text}</Text>
        </Box>
        {line.detail && (
          <Box paddingLeft={4}>
            <Text color={themeColors.dim}>{truncateLine(line.detail, termWidth, 4)}</Text>
          </Box>
        )}
      </Box>
    );
  }

  if (line.type === 'tool_result') {
    return (
      <Box paddingLeft={4}>
        <Text color={themeColors.dim}>{truncateLine(line.text, termWidth, 4)}</Text>
      </Box>
    );
  }

  // status
  return (
    <Box paddingLeft={2}>
      <Text color={themeColors.dim}>{line.text}</Text>
    </Box>
  );
}
