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
import { useClaudeSpinner } from '../hooks/useClaudeSpinner.js';
import { formatToolCall } from '../lib/format.js';
import type { SegmentState } from '../lib/types.js';

interface AgentActivityPanelProps {
  segments: Map<number, SegmentState>;
  verbose?: boolean;
}

export function AgentActivityPanel({ segments, verbose = false }: AgentActivityPanelProps) {
  const sorted = [...segments.entries()].sort(([a], [b]) => a - b);

  // Only show segments that are active (not done/failed) — completed ones are in the scroll log
  const active = sorted.filter(([, seg]) => !seg.done && !seg.failed);
  const done = sorted.filter(([, seg]) => seg.done);
  const failed = sorted.filter(([, seg]) => seg.failed);

  return (
    <Box flexDirection="column" paddingLeft={1} marginTop={0}>
      {active.map(([id, seg]) => (
        <ActiveSegmentLine key={id} segment={seg} verbose={verbose} />
      ))}
      {done.map(([id, seg]) => (
        <CompletedSegmentLine key={id} segment={seg} status="ok" />
      ))}
      {failed.map(([id, seg]) => (
        <CompletedSegmentLine key={id} segment={seg} status="failed" />
      ))}
    </Box>
  );
}

function ActiveSegmentLine({ segment, verbose }: { segment: SegmentState; verbose: boolean }) {
  const { themeColors } = useAppContext();
  const spinnerChar = useClaudeSpinner();

  const retryBadge = segment.attempt > 1
    ? <Text color={themeColors.warn} bold>{` Retry ${segment.attempt - 1}/3`}</Text>
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

function CompletedSegmentLine({ segment, status }: { segment: SegmentState; status: 'ok' | 'failed' }) {
  const { themeColors } = useAppContext();

  const icon = status === 'ok' ? '✔' : '✘';
  const iconColor = status === 'ok' ? themeColors.success : themeColors.error;
  const attemptStr = segment.attempt > 1 ? ` (attempt ${segment.attempt})` : '';

  return (
    <Box>
      <Text color={iconColor} bold>{icon} </Text>
      <Text bold>Segment {segment.id}</Text>
      <Text color={themeColors.dim}>
        {status === 'ok' ? `: Complete${attemptStr}` : `: Failed${attemptStr}`}
      </Text>
    </Box>
  );
}
