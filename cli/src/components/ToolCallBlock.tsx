/**
 * ToolCallBlock — Collapsible display for a tool invocation.
 * Mirrors Claude Code CLI's inline tool call display.
 */

import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import type { ToolCallEntry } from '../lib/types.js';

interface ToolCallBlockProps {
  entry: ToolCallEntry;
  isFocused?: boolean;
}

export function ToolCallBlock({ entry, isFocused = false }: ToolCallBlockProps) {
  const { themeColors } = useAppContext();
  const [collapsed, setCollapsed] = useState(entry.collapsed);

  useInput((_input, key) => {
    if (!isFocused) return;
    if (key.return || _input === ' ') {
      setCollapsed(c => !c);
    }
  }, { isActive: isFocused });

  // Format params summary for collapsed view
  const paramsSummary = Object.entries(entry.params)
    .slice(0, 2)
    .map(([k, v]) => `${k}: ${String(v).slice(0, 30)}`)
    .join(', ');

  return (
    <Box flexDirection="column" paddingLeft={2}>
      {/* Tool name + summary (always visible) */}
      <Box>
        <Text color={themeColors.accent} bold>⏺ </Text>
        <Text color={themeColors.primary}>{entry.name}</Text>
        {paramsSummary && (
          <Text color={themeColors.dim}> ({paramsSummary})</Text>
        )}
        {!collapsed && (
          <Text color={themeColors.dim}> ▾</Text>
        )}
      </Box>

      {/* Expanded: full params + output */}
      {!collapsed && (
        <Box flexDirection="column" paddingLeft={2} marginTop={0}>
          {Object.entries(entry.params).map(([k, v]) => (
            <Box key={k}>
              <Text color={themeColors.muted}>{k}</Text>
              <Text color={themeColors.dim}>: </Text>
              <Text color={themeColors.text}>{String(v).slice(0, 200)}</Text>
            </Box>
          ))}
          {entry.output && (
            <Box marginTop={1}>
              <Text color={themeColors.dim}>
                {entry.output.slice(0, 300)}
                {entry.output.length > 300 ? '…' : ''}
              </Text>
            </Box>
          )}
        </Box>
      )}
    </Box>
  );
}
