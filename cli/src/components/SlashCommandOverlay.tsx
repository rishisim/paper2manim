/**
 * SlashCommandOverlay — Dropdown autocomplete for slash commands.
 * Shown when the user starts typing "/" in the PromptBar.
 * Supports scrolling through all commands with ↑/↓ arrows.
 */

import React, { useState, useEffect } from 'react';
import { Box, Text, useInput } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import { filterCommands } from '../lib/commands.js';
import type { SlashCommand } from '../lib/types.js';

const MAX_VISIBLE = 8;

interface SlashCommandOverlayProps {
  query: string; // text after the leading "/"
  onAccept: (command: SlashCommand) => void;
  onDismiss: () => void;
  isActive: boolean;
}

export function SlashCommandOverlay({ query, onAccept, onDismiss, isActive }: SlashCommandOverlayProps) {
  const { themeColors } = useAppContext();
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [scrollOffset, setScrollOffset] = useState(0);

  const filtered = filterCommands(query);

  // Reset selection and scroll when query changes
  useEffect(() => {
    setSelectedIdx(0);
    setScrollOffset(0);
  }, [query]);

  // Keep the selected item within the visible window
  useEffect(() => {
    if (selectedIdx < scrollOffset) {
      setScrollOffset(selectedIdx);
    } else if (selectedIdx >= scrollOffset + MAX_VISIBLE) {
      setScrollOffset(selectedIdx - MAX_VISIBLE + 1);
    }
  }, [selectedIdx, scrollOffset]);

  const visible = filtered.slice(scrollOffset, scrollOffset + MAX_VISIBLE);
  const aboveCount = scrollOffset;
  const belowCount = Math.max(0, filtered.length - scrollOffset - MAX_VISIBLE);

  useInput((_input, key) => {
    if (!isActive || filtered.length === 0) return;

    if (key.upArrow) {
      setSelectedIdx(i => Math.max(0, i - 1));
      return;
    }
    if (key.downArrow) {
      setSelectedIdx(i => Math.min(filtered.length - 1, i + 1));
      return;
    }
    if (key.return || key.tab) {
      const cmd = filtered[selectedIdx];
      if (cmd) onAccept(cmd);
      return;
    }
    if (key.escape) {
      onDismiss();
      return;
    }
  }, { isActive });

  if (!isActive || visible.length === 0) return null;

  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor={themeColors.dim}
      marginBottom={0}
    >
      {aboveCount > 0 && (
        <Box paddingX={1}>
          <Text color={themeColors.dim}>  ↑ {aboveCount} more above</Text>
        </Box>
      )}
      {visible.map((cmd, idx) => {
        const absIdx = scrollOffset + idx;
        const isSelected = absIdx === selectedIdx;
        return (
          <Box key={cmd.name} paddingX={1}>
            <Text color={isSelected ? themeColors.primary : themeColors.text} bold={isSelected}>
              {isSelected ? '▸ ' : '  '}
            </Text>
            <Text color={isSelected ? themeColors.primary : themeColors.text} bold={isSelected}>
              /{cmd.name}
            </Text>
            {cmd.args && (
              <Text color={themeColors.muted}> {cmd.args}</Text>
            )}
            <Text color={themeColors.dim}>
              {'  '}{cmd.description}
            </Text>
            {cmd.aliases.length > 0 && (
              <Text color={themeColors.dim}>
                {'  '}({cmd.aliases.map(a => `/${a}`).join(', ')})
              </Text>
            )}
          </Box>
        );
      })}
      {belowCount > 0 && (
        <Box paddingX={1}>
          <Text color={themeColors.dim}>  ↓ {belowCount} more below</Text>
        </Box>
      )}
    </Box>
  );
}
