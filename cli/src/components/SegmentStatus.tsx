import React from 'react';
import { Box, Text } from 'ink';
import Spinner from 'ink-spinner';
import { useAppContext } from '../context/AppContext.js';
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
  const { themeColors } = useAppContext();

  if (segment.done) {
    const attemptStr = segment.attempt > 1 ? ` (attempt ${segment.attempt})` : '';
    return (
      <Text wrap="wrap">
        <Text color={themeColors.success} bold>✔</Text>
        <Text bold> Segment {segment.id}</Text>
        <Text color={themeColors.dim}>{attemptStr}</Text>
      </Text>
    );
  }

  if (segment.failed) {
    const attemptStr = segment.attempt > 1 ? ` (attempt ${segment.attempt})` : '';
    return (
      <Text wrap="wrap">
        <Text color={themeColors.error} bold>✘</Text>
        <Text bold> Segment {segment.id}</Text>
        <Text color={themeColors.error}> failed{attemptStr}</Text>
      </Text>
    );
  }

  const retryStr = segment.attempt > 1
    ? <Text color={themeColors.warn} bold>{` retry ${segment.attempt - 1}/3`}</Text>
    : null;

  return (
    <Text wrap="wrap">
      <Text color={themeColors.primary}>
        <Spinner type="dots" />
      </Text>
      <Text bold> Segment {segment.id}</Text>
      {retryStr}
      <Text color={themeColors.dim}> {segment.prettyPhase}</Text>
    </Text>
  );
}
