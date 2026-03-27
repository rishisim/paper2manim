/**
 * SlashCommandOverlay — Dropdown autocomplete for slash commands.
 * Shown when the user starts typing "/" in the PromptBar.
 */

import React, { useState, useEffect } from 'react';
import { Box, Text, useInput } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import { filterCommands, COMMANDS } from '../lib/commands.js';
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

  const filtered = filterCommands(query);
  const visible = filtered.slice(0, MAX_VISIBLE);

  // Reset selection when query changes
  useEffect(() => {
    setSelectedIdx(0);
  }, [query]);

  useInput((_input, key) => {
    if (!isActive || visible.length === 0) return;

    if (key.upArrow) {
      setSelectedIdx(i => Math.max(0, i - 1));
      return;
    }
    if (key.downArrow) {
      setSelectedIdx(i => Math.min(visible.length - 1, i + 1));
      return;
    }
    if (key.return || key.tab) {
      const cmd = visible[selectedIdx];
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
      {visible.map((cmd, idx) => {
        const isSelected = idx === selectedIdx;
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
      {filtered.length > MAX_VISIBLE && (
        <Box paddingX={1}>
          <Text color={themeColors.dim}>  … {filtered.length - MAX_VISIBLE} more</Text>
        </Box>
      )}
    </Box>
  );
}
