import React, { useMemo } from 'react';
import { Box, Text } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';
import { highlightLine, type ColorKey } from '../lib/pythonHighlight.js';
import type { SegmentState } from '../lib/types.js';

interface CodeTabProps {
  segmentCodes: Map<number, string>;
  segments: Map<number, SegmentState>;
  selectedSegment: number;
  scrollOffset: number;
  recentChanges: Map<number, Set<number>>; // segmentId -> set of recently changed line numbers
  viewportHeight: number;
  onSelectSegment?: (id: number) => void;
}

/**
 * Compute click regions for segment labels in the selector bar.
 * Returns array of {id, startX, endX} for each segment label (1-indexed columns).
 * The selector bar starts at paddingLeft=1, then "< " (2 chars).
 */
export function getCodeSegmentClickRegions(segmentIds: number[]): Array<{ id: number; startX: number; endX: number }> {
  const regions: Array<{ id: number; startX: number; endX: number }> = [];
  let x = 4; // paddingLeft(1) + "< "(2) + 1-indexed
  for (let i = 0; i < segmentIds.length; i++) {
    const id = segmentIds[i]!;
    const label = `Seg ${id}`;
    regions.push({ id, startX: x, endX: x + label.length - 1 });
    x += label.length;
    if (i < segmentIds.length - 1) {
      x += 3; // " · " separator
    }
  }
  return regions;
}

function colorKeyToTheme(key: ColorKey, themeColors: { primary: string; success: string; dim: string; accent: string; warn: string; text: string }): string {
  switch (key) {
    case 'keyword': return themeColors.primary;
    case 'string': return themeColors.success;
    case 'comment': return themeColors.dim;
    case 'number': return themeColors.accent;
    case 'manim': return themeColors.warn;
    case 'decorator': return themeColors.accent;
    default: return themeColors.text;
  }
}

export function CodeTab({
  segmentCodes,
  segments,
  selectedSegment,
  scrollOffset,
  recentChanges,
  viewportHeight,
  onSelectSegment,
}: CodeTabProps) {
  const { themeColors } = useAppContext();
  const termWidth = useTerminalWidth();

  // Get sorted segment IDs
  const segmentIds = useMemo(() => {
    const ids = new Set<number>();
    for (const id of segmentCodes.keys()) ids.add(id);
    for (const id of segments.keys()) ids.add(id);
    return [...ids].sort((a, b) => a - b);
  }, [segmentCodes, segments]);

  const effectiveSegId = segmentIds.includes(selectedSegment) ? selectedSegment :
    segmentIds.length > 0 ? segmentIds[0]! : -1;

  const code = effectiveSegId >= 0 ? (segmentCodes.get(effectiveSegId) ?? '') : '';
  const segState = effectiveSegId >= 0 ? segments.get(effectiveSegId) : undefined;
  const changedLines = effectiveSegId >= 0 ? (recentChanges.get(effectiveSegId) ?? new Set<number>()) : new Set<number>();

  const lines = useMemo(() => code.split('\n'), [code]);
  const totalLines = lines.length;

  // Viewport
  const safeViewport = Math.max(5, viewportHeight - 4); // header + status + padding
  const maxScroll = Math.max(0, totalLines - safeViewport);
  const safeOffset = Math.max(0, Math.min(scrollOffset, maxScroll));
  const visibleLines = lines.slice(safeOffset, safeOffset + safeViewport);

  // Gutter width (based on total line count)
  const gutterWidth = Math.max(3, String(totalLines).length);
  const codeWidth = Math.max(20, termWidth - gutterWidth - 6); // 6 = padding + gutter separator + change marker

  // Phase display
  const phaseText = segState?.prettyPhase ?? (code ? 'Done' : 'Waiting...');
  const attemptText = segState && segState.attempt > 1 ? ` · Attempt ${segState.attempt}/3` : '';

  // Current segment index in the segmentIds list
  const currentIdx = segmentIds.indexOf(effectiveSegId);

  return (
    <Box flexDirection="column" paddingLeft={1}>
      {/* Segment selector */}
      <Box marginBottom={0}>
        <Text color={themeColors.dim}>{'< '}</Text>
        {segmentIds.map((id, idx) => {
          const isActive = id === effectiveSegId;
          return (
            <React.Fragment key={id}>
              <Text
                color={isActive ? themeColors.text : themeColors.dim}
                bold={isActive}
                underline={isActive}
              >
                Seg {id}
              </Text>
              {idx < segmentIds.length - 1 && (
                <Text color={themeColors.dim}> · </Text>
              )}
            </React.Fragment>
          );
        })}
        <Text color={themeColors.dim}>{' >'}</Text>
        <Text color={themeColors.muted}>  {phaseText}{attemptText}</Text>
      </Box>

      {/* Code display */}
      {code ? (
        <Box flexDirection="column">
          {visibleLines.map((line, viewIdx) => {
            const lineNum = safeOffset + viewIdx + 1;
            const isChanged = changedLines.has(lineNum);
            const gutterMark = isChanged ? '+' : ' ';
            const gutterColor = isChanged ? themeColors.success : themeColors.dim;

            // Highlight the line
            const spans = highlightLine(line);
            const truncatedLine = line.length > codeWidth ? line.slice(0, codeWidth - 1) + '…' : line;
            const truncatedSpans = truncatedLine === line ? spans : highlightLine(truncatedLine);

            return (
              <Box key={`${effectiveSegId}-${lineNum}`}>
                <Text color={gutterColor}>{gutterMark}</Text>
                <Text color={themeColors.dim}>
                  {String(lineNum).padStart(gutterWidth)}
                </Text>
                <Text color={themeColors.dim}> │ </Text>
                {truncatedSpans.map((span, si) => (
                  <Text key={si} color={colorKeyToTheme(span.colorKey, themeColors)}>
                    {span.text}
                  </Text>
                ))}
              </Box>
            );
          })}
        </Box>
      ) : (
        <Box paddingLeft={2} marginTop={1}>
          <Text color={themeColors.dim}>
            {segmentIds.length === 0
              ? 'No segments yet. Code will appear here when the agent starts generating.'
              : 'No code generated for this segment yet.'}
          </Text>
        </Box>
      )}

      {/* Status line */}
      <Box marginTop={0}>
        <Text color={themeColors.dim}>
          {code
            ? `Line ${safeOffset + 1}-${Math.min(safeOffset + safeViewport, totalLines)}/${totalLines}`
            : 'Waiting for code...'}
          {segmentIds.length > 1 ? ` · click or ←/→ to switch segments (${currentIdx + 1}/${segmentIds.length})` : ''}
          {code ? ' · ↑/↓ scroll' : ''}
        </Text>
      </Box>
    </Box>
  );
}
