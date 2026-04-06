/**
 * SlashCommandOverlay — command palette dropdown.
 *
 * Fixed height: always renders exactly MAX_VISIBLE body rows.
 * This keeps Ink's render region stable so content from the welcome
 * screen cannot bleed through when the slash menu opens or filters.
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

  const selectedCmd = filtered[selectedIdx];
  const categoryLabel = selectedCmd ? (CATEGORY_LABELS[selectedCmd.category] ?? selectedCmd.category) : '';
  const visible = filtered.slice(scrollOffset, scrollOffset + MAX_VISIBLE);
  const aboveCount = scrollOffset;
  const belowCount = Math.max(0, filtered.length - scrollOffset - MAX_VISIBLE);
  const bodyRows = Array.from({ length: MAX_VISIBLE }, (_, idx) => {
    if (filtered.length === 0) {
      return idx === 0 ? { kind: 'message' as const } : { kind: 'blank' as const };
    }

    const cmd = visible[idx];
    if (!cmd) return { kind: 'blank' as const };

    return {
      kind: 'command' as const,
      cmd,
      absIdx: scrollOffset + idx,
    };
  });

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

      {bodyRows.map((row, idx) => {
        if (row.kind === 'message') {
          return (
            <Box key={`message-${idx}`}>
              <Text color={themeColors.muted}>No matching commands</Text>
            </Box>
          );
        }

        if (row.kind === 'blank') {
          return (
            <Box key={`blank-${idx}`}>
              <Text> </Text>
            </Box>
          );
        }

        const isSelected = row.absIdx === selectedIdx;
        const isTopVisibleRow = idx === 0;
        const isBottomVisibleRow = idx === MAX_VISIBLE - 1;
        const showAboveHint = isTopVisibleRow && aboveCount > 0;
        const showBelowHint = isBottomVisibleRow && belowCount > 0;

        if (showAboveHint) {
          return (
            <Box key={`above-${row.cmd.name}`} paddingLeft={1}>
              <Text color={themeColors.dim}>{aboveCount} more</Text>
            </Box>
          );
        }

        if (showBelowHint) {
          return (
            <Box key={`below-${row.cmd.name}`} paddingLeft={1}>
              <Text color={themeColors.dim}>{belowCount} more</Text>
            </Box>
          );
        }

        return (
          <Box key={row.cmd.name}>
            <Text color={isSelected ? themeColors.primary : themeColors.dim}>
              {isSelected ? '> ' : '  '}
            </Text>
            <Text color={isSelected ? themeColors.primary : themeColors.dim}>/</Text>
            <HighlightedName
              name={row.cmd.name}
              query={query}
              isSelected={isSelected}
              primaryColor={themeColors.primary}
              textColor={themeColors.text}
            />
            {row.cmd.args && (
              <Text color={themeColors.muted}> {row.cmd.args}</Text>
            )}
            <Text color={themeColors.dim}>  {row.cmd.description}</Text>
          </Box>
        );
      })}

      {/* Footer key hints */}
      <Box>
        <Text color={themeColors.dim} dimColor>
          ↑↓ navigate  tab/↵ accept  esc dismiss
        </Text>
      </Box>

    </Box>
  );
}
