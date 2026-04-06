/**
 * AgentActivityPanel — Claude Code-style per-segment agent activity display.
 *
 * Shows each active segment with:
 * - Spinner + segment ID + phase
 * - ⏺ marker for current tool call or thinking state
 * - Collapsed tool result output (expanded in verbose mode)
 */

import React from 'react';
import { Box, Text } from 'ink';
import { RESULT_MARKER } from '../lib/theme.js';
import { useAppContext } from '../context/AppContext.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';
import { useClaudeSpinner } from '../hooks/useClaudeSpinner.js';
import { formatToolCall } from '../lib/format.js';
import type { SegmentState } from '../lib/types.js';

interface AgentActivityPanelProps {
  segments: Map<number, SegmentState>;
  verbose?: boolean;
}

export function AgentActivityPanel({ segments, verbose = false }: AgentActivityPanelProps) {
  const { themeColors } = useAppContext();
  const sorted = [...segments.entries()].sort(([a], [b]) => a - b);
  const termWidth = useTerminalWidth();
  const maxActive = termWidth < 100 ? 3 : 5;

  // Only show segments that are active (not done/failed) — completed ones are in the scroll log
  const active = sorted.filter(([, seg]) => !seg.done && !seg.failed);
  const visible = active.slice(0, maxActive);
  const hidden = Math.max(0, active.length - visible.length);

  return (
    <Box flexDirection="column" paddingLeft={1} marginTop={0}>
      {visible.map(([id, seg]) => (
        <ActiveSegmentLine key={id} segment={seg} verbose={verbose} />
      ))}
      {hidden > 0 && (
        <Box paddingLeft={2}>
          <Text color={themeColors.dim}>+{hidden} more active segment{hidden === 1 ? '' : 's'}</Text>
        </Box>
      )}
    </Box>
  );
}

function ActiveSegmentLine({ segment, verbose }: { segment: SegmentState; verbose: boolean }) {
  const { themeColors } = useAppContext();
  const spinnerChar = useClaudeSpinner();

  const retryBadge = segment.attempt > 1
    ? <Text color={themeColors.warn} bold>{` attempt ${segment.attempt}/3`}</Text>
    : null;

  // Format tool call using human-readable names
  const toolDisplay = segment.lastToolCall
    ? formatToolCall(segment.lastToolCall.name, segment.lastToolCall.params)
    : '';

  return (
    <Box flexDirection="column">
      {/* Segment header line */}
      <Box>
        <Text color={themeColors.primary}>{spinnerChar} </Text>
        <Text bold>Segment {segment.id}</Text>
        {retryBadge}
        <Text color={themeColors.dim}>  {segment.prettyPhase}</Text>
      </Box>

      {/* Thinking indicator (Claude Code style) */}
      {segment.isThinking && !segment.lastToolCall && (
        <Box paddingLeft={2}>
          <Text color={themeColors.dim} italic>Reasoning…</Text>
        </Box>
      )}

      {/* Tool call with ⎿ marker */}
      {segment.lastToolCall && (
        <Box paddingLeft={2}>
          <Text>
            <Text color={themeColors.accent} bold>{RESULT_MARKER} </Text>
            <Text bold>{toolDisplay}</Text>
          </Text>
        </Box>
      )}

      {/* Verbose: show tool result output */}
      {verbose && segment.lastToolResult && (
        <Box paddingLeft={4}>
          <Text color={themeColors.dim} wrap="truncate">
            {segment.lastToolResult.output.slice(0, 200)}
            {segment.lastToolResult.output.length > 200 ? '…' : ''}
          </Text>
        </Box>
      )}
    </Box>
  );
}
