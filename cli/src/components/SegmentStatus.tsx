import React from 'react';
import { Box, Text } from 'ink';
import Spinner from 'ink-spinner';
import { colors } from '../lib/theme.js';
import type { SegmentState } from '../lib/types.js';

interface SegmentStatusProps {
  segments: Map<number, SegmentState>;
}

export function SegmentStatus({ segments }: SegmentStatusProps) {
  const sorted = [...segments.entries()].sort(([a], [b]) => a - b);

  return (
    <Box flexDirection="column" paddingLeft={2}>
      {sorted.map(([id, seg]) => (
        <SegmentLine key={id} segment={seg} />
      ))}
    </Box>
  );
}

function SegmentLine({ segment }: { segment: SegmentState }) {
  const attemptStr = segment.attempt > 1 ? ` (attempt ${segment.attempt})` : '';

  if (segment.done) {
    return (
      <Text>
        <Text color={colors.success} bold>OK</Text>
        <Text bold> Segment {segment.id}</Text>
        <Text color={colors.dim}>: Complete{attemptStr}</Text>
      </Text>
    );
  }

  if (segment.failed) {
    return (
      <Text>
        <Text color={colors.error} bold>ERR</Text>
        <Text bold> Segment {segment.id}</Text>
        <Text color={colors.error}>: Failed{attemptStr}</Text>
      </Text>
    );
  }

  return (
    <Text>
      <Text color={colors.primary}>
        <Spinner type="dots" />
      </Text>
      <Text bold> Segment {segment.id}</Text>
      <Text color={colors.dim}>: {segment.prettyPhase}{attemptStr}</Text>
    </Text>
  );
}
