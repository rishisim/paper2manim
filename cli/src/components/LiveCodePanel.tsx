import React from 'react';
import { Box, Text } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';
import { highlightLine } from '../lib/pythonHighlight.js';

interface LiveCodePanelProps {
  code: string;
  segmentId: number;
  segmentTitle?: string;
  isStreaming: boolean;
  maxLines: number;
}

export function LiveCodePanel({
  code,
  segmentId,
  segmentTitle,
  isStreaming,
  maxLines,
}: LiveCodePanelProps) {
  const { themeColors } = useAppContext();
  const termWidth = useTerminalWidth();

  if (!code) {
    return (
      <Box
        flexDirection="column"
        marginTop={1}
        marginLeft={1}
        borderStyle="round"
        borderColor={themeColors.dim}
        paddingX={1}
        paddingY={0}
      >
        <Text color={themeColors.dim}>Waiting for code generation…</Text>
      </Box>
    );
  }

  const allLines = code.split('\n').map(line => line.replace(/\t/g, '    '));
  const totalLines = allLines.length;

  // Show the tail of the code (most recent lines)
  const safeMaxLines = Math.max(5, maxLines);
  const startLine = Math.max(0, totalLines - safeMaxLines);
  const visibleLines = allLines.slice(startLine);

  const gutterWidth = String(totalLines).length;
  const contentWidth = Math.max(40, termWidth - gutterWidth - 8); // gutter + borders + padding

  // Header label
  const label = segmentTitle
    ? `S${segmentId} ${segmentTitle}`
    : `S${segmentId}`;
  const truncatedLabel = label.length > contentWidth - 10
    ? label.slice(0, contentWidth - 11) + '…'
    : label;

  // Footer info
  const footerText = isStreaming
    ? `writing ${totalLines} ln`
    : `${totalLines} lines`;

  const borderColor = isStreaming ? themeColors.primary : themeColors.separator;

  return (
    <Box flexDirection="column" marginTop={1} marginLeft={1}>
      {/* Top border with label */}
      <Text color={borderColor}>
        {'╭─ '}
        <Text color={themeColors.primary} bold>{truncatedLabel}</Text>
        <Text color={borderColor}>{' ' + '─'.repeat(Math.max(1, contentWidth - truncatedLabel.length - 2))}╮</Text>
      </Text>

      {/* Code lines */}
      {visibleLines.map((line, idx) => {
        const lineNum = startLine + idx + 1;
        const lineNumStr = String(lineNum).padStart(gutterWidth);
        const isLastLine = idx === visibleLines.length - 1;
        const tokens = highlightLine(line);

        // Truncate the rendered line to fit within borders
        const maxCodeWidth = Math.max(20, contentWidth - gutterWidth - 3);

        return (
          <Box key={`code-${lineNum}`}>
            <Text color={borderColor}>│</Text>
            <Text color={themeColors.dim}>{lineNumStr}</Text>
            <Text color={themeColors.dim}> │ </Text>
            <Text>
              {tokens.map((tok, ti) => (
                <Text key={ti} color={colorKeyToTheme(tok.colorKey, themeColors)}>
                  {tok.text.length > maxCodeWidth && ti === 0
                    ? tok.text.slice(0, maxCodeWidth - 1) + '…'
                    : tok.text}
                </Text>
              ))}
              {isLastLine && isStreaming && (
                <Text color={themeColors.primary}> █</Text>
              )}
            </Text>
          </Box>
        );
      })}

      {/* Bottom border with line count */}
      <Text color={borderColor}>
        {'╰' + '─'.repeat(Math.max(1, contentWidth - footerText.length - 2))}
        <Text color={themeColors.dim}>{' ' + footerText + ' '}</Text>
        <Text color={borderColor}>╯</Text>
      </Text>
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
