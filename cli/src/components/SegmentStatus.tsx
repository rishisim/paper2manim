import React from 'react';
import { Box, Text } from 'ink';
import Spinner from 'ink-spinner';
import { useAppContext } from '../context/AppContext.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';
import { formatToolCall } from '../lib/format.js';
import type { SegmentState } from '../lib/types.js';

interface SegmentStatusProps {
  segments: Map<number, SegmentState>;
  verbose?: boolean;
}

export function SegmentStatus({ segments, verbose = false }: SegmentStatusProps) {
  const sorted = [...segments.entries()].sort(([a], [b]) => a - b);
  const termWidth = useTerminalWidth();

  return (
    <Box flexDirection="column" paddingLeft={2}>
      {sorted.map(([id, seg]) => (
        <SegmentLine key={id} segment={seg} termWidth={termWidth} verbose={verbose} />
      ))}
    </Box>
  );
}

export interface SegmentLineViewModel {
  state: 'running' | 'retry' | 'failed' | 'done';
  label: string;
  detail?: string;
  hint?: string;
}

export function getSegmentLineViewModel(segment: SegmentState): SegmentLineViewModel {
  if (segment.done) {
    return {
      state: 'done',
      label: `Segment ${segment.id}`,
      detail: segment.attempt > 1 ? `done (attempt ${segment.attempt}/3)` : 'done',
    };
  }
  if (segment.failed) {
    return {
      state: 'failed',
      label: `Segment ${segment.id}`,
      detail: segment.attempt > 1 ? `failed (attempt ${segment.attempt}/3)` : 'failed',
      hint: segment.failHint,
    };
  }
  if (segment.attempt > 1) {
    return {
      state: 'retry',
      label: `Segment ${segment.id}`,
      detail: `${segment.prettyPhase} (attempt ${segment.attempt}/3)`,
    };
  }
  return {
    state: 'running',
    label: `Segment ${segment.id}`,
    detail: segment.prettyPhase,
  };
}

function truncateSegmentText(text: string, maxWidth: number): string {
  if (text.length <= maxWidth) return text;
  return `${text.slice(0, Math.max(0, maxWidth - 1))}…`;
}

export function formatSegmentViewModelForWidth(vm: SegmentLineViewModel, termWidth: number): SegmentLineViewModel {
  const detailMax = termWidth < 100 ? 38 : 64;
  const hintMax = termWidth < 100 ? 44 : 76;
  return {
    ...vm,
    detail: vm.detail ? truncateSegmentText(vm.detail, detailMax) : vm.detail,
    hint: vm.hint ? truncateSegmentText(vm.hint, hintMax) : vm.hint,
  };
}

function SegmentLine({ segment, termWidth, verbose }: { segment: SegmentState; termWidth: number; verbose: boolean }) {
  const { themeColors } = useAppContext();
  const vm = formatSegmentViewModelForWidth(getSegmentLineViewModel(segment), termWidth);
  const verboseMeta = verbose ? getVerboseSegmentMeta(segment, termWidth) : [];

  if (vm.state === 'done') {
    return (
      <Box flexDirection="column">
        <Text wrap="wrap">
          <Text color={themeColors.success} bold>✔</Text>
          <Text bold> {vm.label}</Text>
          {vm.detail ? <Text color={themeColors.dim}> {vm.detail}</Text> : null}
        </Text>
        {verboseMeta.map((line, idx) => (
          <Text key={`${segment.id}-done-meta-${idx}`} color={themeColors.dim}>   {line}</Text>
        ))}
      </Box>
    );
  }

  if (vm.state === 'failed') {
    return (
      <Box flexDirection="column">
        <Text wrap="wrap">
          <Text color={themeColors.error} bold>✘</Text>
          <Text bold> {vm.label}</Text>
          {vm.detail ? <Text color={themeColors.error}> {vm.detail}</Text> : null}
        </Text>
        {vm.hint ? (
          <Text color={themeColors.dim}>   hint: {vm.hint}</Text>
        ) : null}
        {verboseMeta.map((line, idx) => (
          <Text key={`${segment.id}-failed-meta-${idx}`} color={themeColors.dim}>   {line}</Text>
        ))}
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      <Text wrap="wrap">
        <Text color={vm.state === 'retry' ? themeColors.warn : themeColors.primary}>
          <Spinner type="dots" />
        </Text>
        <Text bold> {vm.label}</Text>
        {vm.detail ? (
          <Text color={vm.state === 'retry' ? themeColors.warn : themeColors.dim}> {vm.detail}</Text>
        ) : null}
      </Text>
      {verboseMeta.map((line, idx) => (
        <Text key={`${segment.id}-meta-${idx}`} color={themeColors.dim}>   {line}</Text>
      ))}
    </Box>
  );
}

function getVerboseSegmentMeta(segment: SegmentState, termWidth: number): string[] {
  const lines: string[] = [];
  const maxWidth = termWidth < 100 ? 44 : 84;

  if (segment.lastStatus && segment.lastStatus !== segment.prettyPhase) {
    lines.push(`status: ${truncateSegmentText(segment.lastStatus, maxWidth)}`);
  }
  if (segment.isThinking && segment.thinkingText) {
    lines.push(`thinking: ${truncateSegmentText(segment.thinkingText, maxWidth)}`);
  }
  if (segment.lastToolCall) {
    const toolCall = formatToolCall(segment.lastToolCall.name, segment.lastToolCall.params);
    lines.push(`tool: ${truncateSegmentText(toolCall, maxWidth)}`);
  }
  if (segment.lastToolResult?.output) {
    const preview = segment.lastToolResult.output.replace(/\s+/g, ' ').trim();
    lines.push(`result: ${truncateSegmentText(preview, maxWidth)}`);
  }

  return lines;
}
