/**
 * SlashCommandOverlay — command palette dropdown.
 *
 * Dynamic height: renders only the actual number of matching commands
 * (up to MAX_VISIBLE). No blank padding rows.
 */

import React, { useState, useEffect } from 'react';
import { Box, Text, useInput } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import { COMMANDS, filterCommands } from '../lib/commands.js';
import type { SlashCommand, CommandCategory } from '../lib/types.js';

const MAX_VISIBLE = 9;

const CATEGORY_LABELS: Record<CommandCategory, string> = {
  generation: 'Generation',
  workspace:  'Workspace',
  navigation: 'Navigation',
  settings:   'Settings',
  display:    'Display',
  tools:      'Tools',
  memory:     'Memory',
  session:    'Session',
};

interface SlashCommandOverlayProps {
  query: string;
  onAccept: (command: SlashCommand) => void;
  onDismiss: () => void;
  isActive: boolean;
}

/** Render command name with the matched query portion bolded. */
function HighlightedName({
  name,
  query,
  isSelected,
  primaryColor,
  textColor,
}: {
  name: string;
  query: string;
  isSelected: boolean;
  primaryColor: string;
  textColor: string;
}) {
  const lowerName = name.toLowerCase();
  const lowerQuery = query.toLowerCase();
  const matchIdx = query ? lowerName.indexOf(lowerQuery) : -1;

  if (matchIdx === -1) {
    return (
      <Text color={isSelected ? primaryColor : textColor} bold={isSelected}>
        {name}
      </Text>
    );
  }

  const before = name.slice(0, matchIdx);
  const match  = name.slice(matchIdx, matchIdx + query.length);
  const after  = name.slice(matchIdx + query.length);

  return (
    <>
      {before && <Text color={isSelected ? primaryColor : textColor}>{before}</Text>}
      <Text color={primaryColor} bold>{match}</Text>
      {after  && <Text color={isSelected ? primaryColor : textColor}>{after}</Text>}
    </>
  );
}

export function SlashCommandOverlay({
  query,
  onAccept,
  onDismiss,
  isActive,
}: SlashCommandOverlayProps) {
  const { themeColors } = useAppContext();
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [scrollOffset, setScrollOffset] = useState(0);

  const filtered = filterCommands(query);

  // Reset on query change
  useEffect(() => {
    setSelectedIdx(0);
    setScrollOffset(0);
  }, [query]);

  // Keep selected item within the visible window
  useEffect(() => {
    if (selectedIdx < scrollOffset) {
      setScrollOffset(selectedIdx);
    } else if (selectedIdx >= scrollOffset + MAX_VISIBLE) {
      setScrollOffset(selectedIdx - MAX_VISIBLE + 1);
    }
  }, [selectedIdx, scrollOffset]);

  useInput((input, key) => {
    if (!isActive) return;

    if (filtered.length === 0) {
      if (key.escape) { onDismiss(); return; }
      return;
    }

    if (key.upArrow) {
      setSelectedIdx(i => Math.max(0, i - 1));
      return;
    }
    if (key.downArrow) {
      setSelectedIdx(i => Math.min(filtered.length - 1, i + 1));
      return;
    }
    if (key.return || key.tab || input === '\n') {
      const cmd = filtered[selectedIdx];
      if (cmd) onAccept(cmd);
      return;
    }
    if (key.escape) {
      onDismiss();
      return;
    }
  }, { isActive });

  if (!isActive) return null;

  // No matches — show feedback
  if (filtered.length === 0) {
    return (
      <Box flexDirection="column" borderStyle="round" borderColor={themeColors.separator} paddingX={1}>
        <Text color={themeColors.muted}>No matching commands</Text>
        <Text color={themeColors.dim} dimColor>esc dismiss</Text>
      </Box>
    );
  }

  // Dynamic visible window
  const visibleCount = Math.min(filtered.length, MAX_VISIBLE);
  const visible = filtered.slice(scrollOffset, scrollOffset + visibleCount);
  const aboveCount = scrollOffset;
  const belowCount = Math.max(0, filtered.length - scrollOffset - visibleCount);

  const selectedCmd = filtered[selectedIdx];
  const categoryLabel = selectedCmd ? (CATEGORY_LABELS[selectedCmd.category] ?? selectedCmd.category) : '';

  return (
    <Box flexDirection="column" borderStyle="round" borderColor={themeColors.separator} paddingX={1}>

      {/* Header: match count + selected category */}
      <Box>
        <Text color={themeColors.muted}>
          {query
            ? `${filtered.length} command${filtered.length !== 1 ? 's' : ''}`
            : `${COMMANDS.length} commands`}
        </Text>
        {categoryLabel ? (
          <Text color={themeColors.dim} dimColor>  {categoryLabel}</Text>
        ) : null}
      </Box>

      {/* Scroll indicator: above (only when scrollable) */}
      {aboveCount > 0 && (
        <Box paddingLeft={1}>
          <Text color={themeColors.dim}>{aboveCount} more</Text>
        </Box>
      )}

      {/* Command rows */}
      {visible.map((cmd, idx) => {
        const absIdx = scrollOffset + idx;
        const isSelected = absIdx === selectedIdx;

        return (
          <Box key={cmd.name}>
            <Text color={isSelected ? themeColors.primary : themeColors.dim}>
              {isSelected ? '❯ ' : '  '}
            </Text>
            <Text color={isSelected ? themeColors.primary : themeColors.dim}>/</Text>
            <HighlightedName
              name={cmd.name}
              query={query}
              isSelected={isSelected}
              primaryColor={themeColors.primary}
              textColor={themeColors.text}
            />
            {cmd.args && (
              <Text color={themeColors.muted}> {cmd.args}</Text>
            )}
            <Text color={themeColors.dim}>  {cmd.description}</Text>
          </Box>
        );
      })}

      {/* Scroll indicator: below (only when scrollable) */}
      {belowCount > 0 && (
        <Box paddingLeft={1}>
          <Text color={themeColors.dim}>{belowCount} more</Text>
        </Box>
      )}

      {/* Footer key hints */}
      <Box>
        <Text color={themeColors.dim} dimColor>
          ↑↓ navigate  tab/↵ accept  esc dismiss
        </Text>
      </Box>

    </Box>
  );
}
