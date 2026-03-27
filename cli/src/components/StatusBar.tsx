import React from 'react';
import { Box, Text } from 'ink';
import Spinner from 'ink-spinner';
import { stageConfig, colors, type StageName } from '../lib/theme.js';
import type { SegmentState } from '../lib/types.js';

interface StatusBarProps {
  stage: StageName;
  detail: string;
  elapsed: number;
  segments?: Map<number, SegmentState>;
  totalSegments?: number;
  showShortcutHint?: boolean;
  progress?: number; // 0-100
}

function ProgressBar({ pct, width = 20 }: { pct: number; width?: number }) {
  const filled = Math.round((pct / 100) * width);
  const empty = width - filled;
  return (
    <Text>
      <Text color="#5B9DFF">{'█'.repeat(filled)}</Text>
      <Text color="#444444">{'░'.repeat(empty)}</Text>
      <Text color="#999999"> {String(pct).padStart(3)}%</Text>
    </Text>
  );
}

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}m ${s.toString().padStart(2, '0')}s`;
}

export function StatusBar({ stage, detail, elapsed, segments, totalSegments, showShortcutHint = true, progress }: StatusBarProps) {
  const config = stageConfig[stage] ?? stageConfig.done;

  // Build a compact segment summary for the code stage
  let segmentSummary: string | null = null;
  if (stage === 'code' && segments && segments.size > 0) {
    const done = [...segments.values()].filter(s => s.done).length;
    const failed = [...segments.values()].filter(s => s.failed).length;
    const total = totalSegments || segments.size;
    const active = [...segments.entries()]
      .filter(([, s]) => !s.done && !s.failed)
      .map(([, s]) => `Seg ${s.id}: ${s.prettyPhase}`)
      .slice(0, 3);

    const parts: string[] = [`${done}/${total} done`];
    if (failed > 0) parts.push(`${failed} failed`);
    if (active.length > 0) parts.push(active.join(', '));
    segmentSummary = parts.join('  ·  ');
  }

  return (
    <Box flexDirection="column" paddingLeft={1} marginTop={1}>
      <Box>
        <Text color={config.color}>
          <Spinner type="dots" />
        </Text>
        <Text bold color={config.color}> {config.label}</Text>
        <Text color={colors.muted}>  {formatElapsed(elapsed)}</Text>
        {progress !== undefined && (
          <Text>
            {'  '}
            <ProgressBar pct={progress} />
          </Text>
        )}
      </Box>
      {segmentSummary && (
        <Text color={colors.dim}>    {segmentSummary}</Text>
      )}
      {detail && !segmentSummary && (
        <Text color={colors.dim} wrap="wrap">    {detail}</Text>
      )}
      {showShortcutHint && (
        <Text color={colors.dim}>
          {'  '}<Text color="#5B9DFF">?</Text>{' for shortcuts  '}<Text color="#5B9DFF">esc</Text>{' to cancel'}
        </Text>
      )}
    </Box>
  );
}
