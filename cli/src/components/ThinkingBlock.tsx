/**
 * ThinkingBlock — Gray italic display for LLM thinking/reasoning text.
 * Only renders when verboseMode && thinkingVisible are both true.
 * Mirrors Claude Code CLI's extended thinking display.
 */

import React from 'react';
import { Box, Text } from 'ink';
import { useAppContext } from '../context/AppContext.js';

interface ThinkingBlockProps {
  text: string;
}

export function ThinkingBlock({ text }: ThinkingBlockProps) {
  const { themeColors, verboseMode, thinkingVisible } = useAppContext();

  if (!verboseMode || !thinkingVisible) return null;

  // Truncate very long thinking output
  const display = text.length > 500 ? text.slice(0, 500) + '…' : text;

  return (
    <Box paddingLeft={2} marginTop={0}>
      <Text color={themeColors.dim} italic>
        {'⊘ '}{display}
      </Text>
    </Box>
  );
}
