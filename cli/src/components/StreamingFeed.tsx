/**
 * StreamingFeed — Claude Code-style scrolling feed for pipeline events.
 *
 * Renders a chronological stream of stage headers, segment headers,
 * tool calls, thinking text, code diffs, and completion summaries.
 */

import React from 'react';
import { Box, Text } from 'ink';
import { getStageConfig, RESULT_MARKER, type StageName } from '../lib/theme.js';
import { formatDuration } from '../lib/format.js';
import { useAppContext } from '../context/AppContext.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';
import { useClaudeSpinner } from '../hooks/useClaudeSpinner.js';
import { highlightLine } from '../lib/pythonHighlight.js';
import {
  normalizeActivityKind,
  truncatePreserveTail,
  type ActivityLine,
} from './StatusBar.js';
import { SummaryTable } from './SummaryTable.js';
import { SuccessPanel } from './SuccessPanel.js';
import { ErrorPanel } from './ErrorPanel.js';
import type { FeedItem } from '../lib/feedItems.js';
import type { ThemeColors } from '../lib/theme.js';

interface StreamingFeedProps {
  feedItems: FeedItem[];
  scrollOffset: number;
  selectedIndex: number;
  expandedItems: Set<string>;
  viewportHeight: number;
  verbose: boolean;
  segmentCodes?: Map<number, string>;
}

export function StreamingFeed({
  feedItems,
  scrollOffset,
  selectedIndex,
  expandedItems,
  viewportHeight,
  verbose,
  segmentCodes,
}: StreamingFeedProps) {
  const { themeColors } = useAppContext();
  const termWidth = useTerminalWidth();
  const spinnerChar = useClaudeSpinner();

  // Estimate total "lines" for viewport windowing
  const itemHeights = feedItems.map(item => estimateHeight(item, expandedItems, verbose, termWidth));
  const totalLines = itemHeights.reduce((sum, h) => sum + h, 0);

  const safeViewport = Math.max(5, viewportHeight - 2); // room for scroll indicators
  const maxScroll = Math.max(0, totalLines - safeViewport);
  const safeOffset = Math.max(0, Math.min(scrollOffset, maxScroll));

  // Find which items are visible based on cumulative line heights
  let cumulative = 0;
  let startIdx = 0;
  let startLineOffset = 0;
  for (let i = 0; i < feedItems.length; i++) {
    const h = itemHeights[i]!;
    if (cumulative + h > safeOffset) {
      startIdx = i;
      startLineOffset = safeOffset - cumulative;
      break;
    }
    cumulative += h;
    if (i === feedItems.length - 1) {
      startIdx = feedItems.length;
      startLineOffset = 0;
    }
  }

  // Collect visible items until viewport is filled
  let linesShown = -startLineOffset;
  const visibleItems: FeedItem[] = [];
  for (let i = startIdx; i < feedItems.length && linesShown < safeViewport; i++) {
    visibleItems.push(feedItems[i]!);
    linesShown += itemHeights[i]!;
  }

  const canScrollUp = safeOffset > 0;
  const canScrollDown = safeOffset < maxScroll;

  return (
    <Box flexDirection="column" paddingLeft={1}>
      {canScrollUp && <Text color={themeColors.dim}>↑ more</Text>}

      {visibleItems.map(item => (
        <FeedItemRow
          key={item.id}
          item={item}
          themeColors={themeColors}
          termWidth={termWidth}
          spinnerChar={spinnerChar}
          expanded={expandedItems.has(item.id)}
          selected={feedItems[selectedIndex]?.id === item.id}
          verbose={verbose}
          segmentCodes={segmentCodes}
        />
      ))}

      {canScrollDown && <Text color={themeColors.dim}>↓ more</Text>}
    </Box>
  );
}

// ── Height estimation ──────────────────────────────────────────

function estimateHeight(item: FeedItem, expandedItems: Set<string>, verbose: boolean, _termWidth: number): number {
  switch (item.type) {
    case 'stage_header': return 2; // separator line + blank margin
    case 'segment_header': return 1;
    case 'activity': {
      const kind = normalizeActivityKind(item.line);
      const isExpanded = expandedItems.has(item.id);
      if (kind === 'diff') {
        const detailLines = (item.line.detail ?? '').split('\n').filter(Boolean);
        const shown = isExpanded ? Math.min(detailLines.length, 30) : Math.min(detailLines.length, 6);
        return 1 + shown + (detailLines.length > shown ? 1 : 0);
      }
      if (kind === 'tool_call' && isExpanded && item.line.detail) {
        return 1 + Math.min(item.line.detail.split('\n').length, 20);
      }
      if (kind === 'tool_result' && (isExpanded || verbose) && item.line.detail) {
        return 1 + Math.min(item.line.detail.split('\n').length, 10);
      }
      return 1;
    }
    case 'code_snapshot': {
      if (!expandedItems.has(item.id)) return 1;
      return 1 + Math.min(item.code.split('\n').length, 40) + 1; // header + code + footer
    }
    case 'completion': return 15; // approximate
    case 'error': return 10; // approximate
    default: return 1;
  }
}

// ── Feed item renderers ────────────────────────────────────────

function FeedItemRow({
  item,
  themeColors,
  termWidth,
  spinnerChar,
  expanded,
  selected,
  verbose,
  segmentCodes: _segmentCodes,
}: {
  item: FeedItem;
  themeColors: ThemeColors;
  termWidth: number;
  spinnerChar: string;
  expanded: boolean;
  selected: boolean;
  verbose: boolean;
  segmentCodes?: Map<number, string>;
}) {
  switch (item.type) {
    case 'stage_header':
      return <StageHeader item={item} themeColors={themeColors} termWidth={termWidth} selected={selected} />;
    case 'segment_header':
      return <SegmentHeader item={item} themeColors={themeColors} spinnerChar={spinnerChar} selected={selected} />;
    case 'activity':
      return <ActivityRow item={item} themeColors={themeColors} termWidth={termWidth} expanded={expanded} selected={selected} verbose={verbose} />;
    case 'code_snapshot':
      return <CodeSnapshotRow item={item} themeColors={themeColors} termWidth={termWidth} expanded={expanded} selected={selected} />;
    case 'completion':
      return <CompletionRow item={item} />;
    case 'error':
      return <ErrorRow item={item} />;
    default:
      return null;
  }
}

// ── Stage header ───────────────────────────────────────────────

function StageHeader({
  item,
  themeColors,
  selected,
}: {
  item: Extract<FeedItem, { type: 'stage_header' }>;
  themeColors: ThemeColors;
  termWidth?: number;
  selected: boolean;
}) {
  const stageConfig = getStageConfig(themeColors);
  const config = stageConfig[item.stage] ?? stageConfig.done;
  const icon = item.status === 'complete' ? '✔' : item.status === 'error' ? '✘' : '●';
  const iconColor = item.status === 'complete' ? themeColors.success : item.status === 'error' ? themeColors.error : config.color;

  return (
    <Box marginTop={1}>
      <Text color={selected ? themeColors.text : iconColor}>{selected ? '›' : icon} </Text>
      <Text bold color={config.color}>{config.label}</Text>
    </Box>
  );
}

// ── Segment header ─────────────────────────────────────────────

function SegmentHeader({
  item,
  themeColors,
  spinnerChar,
  selected,
}: {
  item: Extract<FeedItem, { type: 'segment_header' }>;
  themeColors: ThemeColors;
  spinnerChar: string;
  selected: boolean;
}) {
  const icon = item.status === 'done' ? '✔' :
    item.status === 'failed' ? '✘' : spinnerChar;
  const iconColor = item.status === 'done' ? themeColors.success :
    item.status === 'failed' ? themeColors.error : themeColors.accent;
  const elapsedStr = item.elapsed ? ` in ${formatDuration(item.elapsed)}` : '';
  const attemptStr = item.attempt && item.attempt > 1 ? ` (attempt ${item.attempt})` : '';

  return (
    <Box paddingLeft={1} marginTop={0}>
      <Text color={selected ? themeColors.text : iconColor}>{selected ? '›' : icon} </Text>
      <Text bold color={themeColors.text}>{item.label}</Text>
      <Text color={themeColors.dim}>{attemptStr}{elapsedStr}</Text>
    </Box>
  );
}

// ── Activity row ───────────────────────────────────────────────

function ActivityRow({
  item,
  themeColors,
  termWidth,
  expanded,
  selected,
  verbose,
}: {
  item: Extract<FeedItem, { type: 'activity' }>;
  themeColors: ThemeColors;
  termWidth: number;
  expanded: boolean;
  selected: boolean;
  verbose: boolean;
}) {
  const line = item.line;
  const kind = normalizeActivityKind(line);
  const indent = item.segmentId !== undefined ? 4 : 2; // extra indent for segment-scoped
  const repeat = (line.count ?? 1) > 1 ? ` x${line.count}` : '';

  const severityColor = line.severity === 'critical'
    ? themeColors.error
    : line.severity === 'warning'
      ? themeColors.warn
      : themeColors.accent;
  const textColor = line.severity === 'critical' ? themeColors.error : themeColors.dim;

  if (kind === 'tool_call') {
    return (
      <Box flexDirection="column">
        <Box paddingLeft={indent}>
          <Text color={selected ? themeColors.text : themeColors.dim}>{selected ? '› ' : '  '}</Text>
          <Text color={severityColor}>{RESULT_MARKER} </Text>
          <Text bold color={themeColors.text}>
            {truncatePreserveTail(line.text, termWidth, indent + 4)}
          </Text>
          {repeat && <Text color={themeColors.warn}>{repeat}</Text>}
        </Box>
        {expanded && line.detail && (
          <Box flexDirection="column" paddingLeft={indent + 2}>
            {line.detail.split('\n').slice(0, 20).map((dl, idx) => (
              <Text key={`${item.id}-d-${idx}`} color={themeColors.dim}>
                {truncatePreserveTail(dl, termWidth, indent + 4)}
              </Text>
            ))}
          </Box>
        )}
      </Box>
    );
  }

  if (kind === 'diff') {
    const detailLines = (line.detail ?? '')
      .split('\n')
      .map(s => s.trimEnd())
      .filter(Boolean);
    const showLines = expanded ? detailLines.slice(0, 30) : detailLines.slice(0, 6);

    return (
      <Box flexDirection="column">
        <Box paddingLeft={indent}>
          <Text color={selected ? themeColors.text : themeColors.dim}>{selected ? '› ' : '  '}</Text>
          <Text color={severityColor}>{RESULT_MARKER} </Text>
          <Text bold color={themeColors.text}>
            {truncatePreserveTail(line.text, termWidth, indent + 4)}
          </Text>
          {repeat && <Text color={themeColors.warn}>{repeat}</Text>}
        </Box>
        {showLines.map((dl, idx) => {
          const first = dl[0] ?? '';
          const color = first === '+' ? themeColors.success :
            first === '-' ? themeColors.error :
            first === '@' ? themeColors.accent :
            themeColors.dim;
          return (
            <Box key={`${item.id}-diff-${idx}`} paddingLeft={indent + 2}>
              <Text color={color}>{truncatePreserveTail(dl, termWidth, indent + 4)}</Text>
            </Box>
          );
        })}
        {detailLines.length > showLines.length && (
          <Box paddingLeft={indent + 2}>
            <Text color={themeColors.dim}>... {detailLines.length - showLines.length} more lines</Text>
          </Box>
        )}
      </Box>
    );
  }

  if (kind === 'thinking') {
    const label = line.reasoningKind === 'raw_reasoning' ? 'Reasoning (model)' : 'Inference (UI summary)';
    return (
      <Box paddingLeft={indent}>
        <Text color={selected ? themeColors.text : themeColors.dim}>{selected ? '› ' : '  '}</Text>
        <Text color={themeColors.accent}>{label}: </Text>
        <Text color={textColor} italic>
          {truncatePreserveTail(line.text, termWidth, indent + 2)}
        </Text>
        {repeat && <Text color={themeColors.warn}>{repeat}</Text>}
      </Box>
    );
  }

  if (kind === 'tool_result') {
    return (
      <Box flexDirection="column">
        <Box paddingLeft={indent + 2}>
          <Text color={selected ? themeColors.text : themeColors.dim}>{selected ? '› ' : '  '}</Text>
          <Text color={textColor}>
            {truncatePreserveTail(line.text, termWidth, indent + 4)}
          </Text>
          {repeat && <Text color={themeColors.warn}>{repeat}</Text>}
        </Box>
        {(expanded || verbose) && line.detail && (
          <Box flexDirection="column" paddingLeft={indent + 4}>
            {line.detail.split('\n').slice(0, 10).map((dl, idx) => (
              <Text key={`${item.id}-out-${idx}`} color={themeColors.dim}>
                {truncatePreserveTail(dl, termWidth, indent + 6)}
              </Text>
            ))}
          </Box>
        )}
      </Box>
    );
  }

  // status
  return (
    <Box paddingLeft={indent}>
      <Text color={selected ? themeColors.text : themeColors.dim}>{selected ? '› ' : '  '}</Text>
      <Text color={textColor}>
        {truncatePreserveTail(line.text, termWidth, indent + 2)}
      </Text>
      {repeat && <Text color={themeColors.warn}>{repeat}</Text>}
    </Box>
  );
}

// ── Code snapshot ──────────────────────────────────────────────

function CodeSnapshotRow({
  item,
  themeColors,
  termWidth,
  expanded,
  selected,
}: {
  item: Extract<FeedItem, { type: 'code_snapshot' }>;
  themeColors: ThemeColors;
  termWidth: number;
  expanded: boolean;
  selected: boolean;
}) {
  if (!expanded) {
    return (
      <Box paddingLeft={4}>
        <Text color={selected ? themeColors.text : themeColors.dim}>{selected ? '› ' : '  '}</Text>
        <Text color={themeColors.accent}>{RESULT_MARKER} </Text>
        <Text color={themeColors.dim}>{item.summary}</Text>
      </Box>
    );
  }

  const lines = item.code.split('\n').slice(0, 40);
  const gutterWidth = String(lines.length).length;

  return (
    <Box flexDirection="column" paddingLeft={4}>
      <Text color={selected ? themeColors.text : themeColors.dim}>{selected ? '›' : ' '}</Text>
      <Text color={themeColors.accent}>{RESULT_MARKER} </Text>
      <Text bold color={themeColors.text}>{item.summary}</Text>
      {lines.map((codeLine, idx) => {
        const lineNum = String(idx + 1).padStart(gutterWidth);
        const tokens = highlightLine(codeLine);
        return (
          <Box key={`${item.id}-code-${idx}`}>
            <Text color={themeColors.dim}>{lineNum} │ </Text>
            {tokens.map((tok, ti) => (
              <Text key={ti} color={colorKeyToTheme(tok.colorKey, themeColors)}>
                {truncatePreserveTail(tok.text, termWidth, gutterWidth + 5)}
              </Text>
            ))}
          </Box>
        );
      })}
      {item.code.split('\n').length > 40 && (
        <Text color={themeColors.dim}>... {item.code.split('\n').length - 40} more lines</Text>
      )}
    </Box>
  );
}

function colorKeyToTheme(
  colorKey: string,
  t: { primary: string; success: string; dim: string; accent: string; warn: string; text: string },
): string {
  switch (colorKey) {
    case 'keyword': return t.primary;
    case 'string': return t.success;
    case 'comment': return t.dim;
    case 'number': return t.accent;
    case 'manim': return t.warn;
    case 'decorator': return t.accent;
    default: return t.text;
  }
}

// ── Completion ─────────────────────────────────────────────────

function CompletionRow({ item }: { item: Extract<FeedItem, { type: 'completion' }> }) {
  const fu = item.finalUpdate;
  return (
    <Box flexDirection="column">
      <SummaryTable
        stages={item.completedStages}
        timings={fu.timings}
        totalElapsedSeconds={fu.total_elapsed_seconds}
        toolCallCounts={fu.tool_call_counts}
        totalToolCalls={fu.total_tool_calls}
        tokenSummary={fu.token_summary}
      />
      {fu.video_path && <SuccessPanel videoPath={fu.video_path} />}
    </Box>
  );
}

// ── Error ──────────────────────────────────────────────────────

function ErrorRow({ item }: { item: Extract<FeedItem, { type: 'error' }> }) {
  return (
    <ErrorPanel
      message={item.message}
      failedSegments={item.failedSegments}
      projectDir={item.projectDir}
      videoPath={item.videoPath}
      stages={item.completedStages}
      tokenSummary={item.tokenSummary ? {
        estimated_cost_usd: item.tokenSummary.estimated_cost_usd,
        total_api_calls: item.tokenSummary.total_api_calls,
      } : undefined}
    />
  );
}
