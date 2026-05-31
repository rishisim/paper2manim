import React, { useMemo } from 'react';
import { Box, Text } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';
import { RESULT_MARKER } from '../lib/theme.js';
import {
  collapseActivityLines,
  normalizeActivityKind,
  truncatePreserveTail,
  type ActivityLine,
} from './StatusBar.js';
import type { SegmentState } from '../lib/types.js';

/**
 * Compute click regions for filter labels.
 * Returns array of {segmentId (null for "All"), startX, endX}.
 */
export function getActivityFilterClickRegions(segmentIds: number[]): Array<{ segmentId: number | null; startX: number; endX: number }> {
  const regions: Array<{ segmentId: number | null; startX: number; endX: number }> = [];
  // "Filter: " = 8 chars, paddingLeft=1 → starts at col 10
  let x = 10;
  // "All"
  regions.push({ segmentId: null, startX: x, endX: x + 2 });
  x += 3; // "All"
  for (const id of segmentIds) {
    x += 3; // " · "
    const label = `Seg ${id}`;
    regions.push({ segmentId: id, startX: x, endX: x + label.length - 1 });
    x += label.length;
  }
  return regions;
}

interface ActivityTabProps {
  activityLines: ActivityLine[];
  segments: Map<number, SegmentState>;
  scrollOffset: number;
  filterSegment: number | null;
  expandedItems: Set<string>;
  viewportHeight: number;
  verbose: boolean;
}

export function ActivityTab({
  activityLines,
  segments,
  scrollOffset,
  filterSegment,
  expandedItems,
  viewportHeight,
  verbose,
}: ActivityTabProps) {
  const { themeColors } = useAppContext();
  const termWidth = useTerminalWidth();

  // Get unique segment IDs for filter display
  const segmentIds = useMemo(() => {
    const ids = new Set<number>();
    for (const id of segments.keys()) ids.add(id);
    for (const line of activityLines) {
      if (line.segmentId !== undefined) ids.add(line.segmentId);
    }
    return [...ids].sort((a, b) => a - b);
  }, [segments, activityLines]);

  // Filter and collapse
  const filtered = useMemo(() => {
    const lines = filterSegment !== null
      ? activityLines.filter(l => l.segmentId === filterSegment || l.segmentId === undefined)
      : activityLines;
    return collapseActivityLines(lines);
  }, [activityLines, filterSegment]);

  const safeViewport = Math.max(5, viewportHeight - 3); // header + filter bar + hints
  const maxScroll = Math.max(0, filtered.length - safeViewport);
  const safeOffset = Math.max(0, Math.min(scrollOffset, maxScroll));
  const visible = filtered.slice(safeOffset, safeOffset + safeViewport);
  const canScrollUp = safeOffset > 0;
  const canScrollDown = safeOffset + safeViewport < filtered.length;

  return (
    <Box flexDirection="column" paddingLeft={1}>
      {/* Filter bar */}
      <Box marginBottom={0}>
        <Text color={themeColors.dim}>Filter: </Text>
        <Text color={filterSegment === null ? themeColors.text : themeColors.dim} bold={filterSegment === null} underline={filterSegment === null}>
          All
        </Text>
        {segmentIds.map(id => (
          <React.Fragment key={id}>
            <Text color={themeColors.dim}> · </Text>
            <Text
              color={filterSegment === id ? themeColors.text : themeColors.dim}
              bold={filterSegment === id}
              underline={filterSegment === id}
            >
              Seg {id}
            </Text>
          </React.Fragment>
        ))}
        <Text color={themeColors.dim}>  (click to filter)</Text>
      </Box>

      {/* Activity list */}
      {canScrollUp && <Text color={themeColors.dim}>↑ {safeOffset} more</Text>}
      {visible.map(line => {
        const kind = normalizeActivityKind(line);
        const isExpanded = expandedItems.has(line.id);
        const repeat = (line.count ?? 1) > 1 ? ` x${line.count}` : '';

        const severityColor = line.severity === 'critical'
          ? themeColors.error
          : line.severity === 'warning'
            ? themeColors.warn
            : themeColors.accent;
        const textColor = line.severity === 'critical' ? themeColors.error : themeColors.dim;

        if (kind === 'tool_call') {
          return (
            <Box key={line.id} flexDirection="column">
              <Box paddingLeft={1}>
                <Text color={severityColor}>{RESULT_MARKER} </Text>
                <Text bold color={themeColors.text}>
                  {truncatePreserveTail(line.text, termWidth, 6)}
                </Text>
                {repeat && <Text color={themeColors.warn}>{repeat}</Text>}
                {line.detail && <Text color={themeColors.dim}> [Enter to {isExpanded ? 'collapse' : 'expand'}]</Text>}
              </Box>
              {isExpanded && line.detail && (
                <Box flexDirection="column" paddingLeft={4}>
                  {line.detail.split('\n').slice(0, 20).map((dl, idx) => (
                    <Text key={`${line.id}-d-${idx}`} color={themeColors.dim}>{truncatePreserveTail(dl, termWidth, 8)}</Text>
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
          const showLines = isExpanded ? detailLines.slice(0, 30) : detailLines.slice(0, 6);

          return (
            <Box key={line.id} flexDirection="column">
              <Box paddingLeft={1}>
                <Text color={severityColor}>{RESULT_MARKER} </Text>
                <Text bold color={themeColors.text}>{truncatePreserveTail(line.text, termWidth, 6)}</Text>
                {repeat && <Text color={themeColors.warn}>{repeat}</Text>}
              </Box>
              {showLines.map((dl, idx) => {
                const first = dl[0] ?? '';
                const color = first === '+' ? themeColors.success :
                  first === '-' ? themeColors.error :
                  first === '@' ? themeColors.accent :
                  themeColors.dim;
                return (
                  <Box key={`${line.id}-diff-${idx}`} paddingLeft={3}>
                    <Text color={color}>{truncatePreserveTail(dl, termWidth, 6)}</Text>
                  </Box>
                );
              })}
              {detailLines.length > showLines.length && (
                <Box paddingLeft={3}>
                  <Text color={themeColors.dim}>... {detailLines.length - showLines.length} more lines [Enter to expand]</Text>
                </Box>
              )}
            </Box>
          );
        }

        if (kind === 'thinking') {
          return (
            <Box key={line.id} paddingLeft={1}>
              <Text color={textColor} italic>
                {truncatePreserveTail(line.text, termWidth, 4)}
                {repeat && <Text color={themeColors.warn}>{repeat}</Text>}
              </Text>
            </Box>
          );
        }

        if (kind === 'tool_result') {
          return (
            <Box key={line.id} flexDirection="column">
              <Box paddingLeft={3}>
                <Text color={textColor}>
                  {truncatePreserveTail(line.text, termWidth, 6)}
                  {repeat && <Text color={themeColors.warn}>{repeat}</Text>}
                </Text>
              </Box>
              {(isExpanded || verbose) && line.detail && (
                <Box flexDirection="column" paddingLeft={5}>
                  {line.detail.split('\n').slice(0, 10).map((dl, idx) => (
                    <Text key={`${line.id}-out-${idx}`} color={themeColors.dim}>
                      {truncatePreserveTail(dl, termWidth, 10)}
                    </Text>
                  ))}
                </Box>
              )}
            </Box>
          );
        }

        // status
        return (
          <Box key={line.id} paddingLeft={1}>
            <Text color={textColor}>
              {truncatePreserveTail(line.text, termWidth, 4)}
              {repeat && <Text color={themeColors.warn}>{repeat}</Text>}
            </Text>
          </Box>
        );
      })}
      {canScrollDown && <Text color={themeColors.dim}>↓ {Math.max(0, filtered.length - safeOffset - safeViewport)} more</Text>}

      {/* Hints */}
      <Box marginTop={0}>
        <Text color={themeColors.dim}>
          ↑/↓ scroll · click filter · Enter expand
          {filtered.length > 0 ? ` · ${filtered.length} events` : ''}
        </Text>
      </Box>
    </Box>
  );
}
