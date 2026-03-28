/**
 * SlashCommandOverlay — Claude Code-style command palette.
 *
 * Design decisions for rendering stability:
 * - Fixed height: always emits exactly MAX_VISIBLE command rows (padded with
 *   blank rows when fewer commands are shown). This prevents Ink's live-render
 *   region from changing height as the user scrolls, which was causing stale
 *   content from the welcome box above to bleed through.
 * - Above/below scroll indicators are always rendered (blank when not needed)
 *   for the same reason.
 * - Category info is shown in the header (for the selected command) rather than
 *   as interleaved section headers that would add/remove rows mid-list.
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

  if (!isActive || filtered.length === 0) return null;

  // Slice the visible window — may be shorter than MAX_VISIBLE near the end
  const visible = filtered.slice(scrollOffset, scrollOffset + MAX_VISIBLE);
  const aboveCount = scrollOffset;
  const belowCount = Math.max(0, filtered.length - scrollOffset - MAX_VISIBLE);

  // Selected command for the header category label
  const selectedCmd = filtered[selectedIdx];
  const categoryLabel = selectedCmd ? (CATEGORY_LABELS[selectedCmd.category] ?? selectedCmd.category) : '';

  // Pad the visible slice to MAX_VISIBLE so the overlay height never changes
  const rows: (SlashCommand | null)[] = [...visible];
  while (rows.length < MAX_VISIBLE) rows.push(null);

  return (
    <Box flexDirection="column" borderStyle="round" borderColor={themeColors.dim}>

      {/* ── Header: match count + selected category ── */}
      <Box paddingX={1}>
        <Text color={themeColors.muted}>
          {query
            ? `${filtered.length} command${filtered.length !== 1 ? 's' : ''}`
            : `${COMMANDS.length} commands`}
        </Text>
        {categoryLabel ? (
          <Text color={themeColors.dim} dimColor>{'  '}{categoryLabel}</Text>
        ) : null}
      </Box>

      {/* ── Scroll indicator: above — always one line ── */}
      <Box paddingX={2}>
        {aboveCount > 0
          ? <Text color={themeColors.dim}>↑ {aboveCount} more</Text>
          : <Text> </Text>
        }
      </Box>

      {/* ── Fixed-height command rows ── */}
      {rows.map((cmd, idx) => {
        if (!cmd) {
          // Blank padding row — keeps the overlay height constant
          return <Box key={`pad-${idx}`} paddingX={1}><Text> </Text></Box>;
        }

        const absIdx = scrollOffset + idx;
        const isSelected = absIdx === selectedIdx;

        return (
          <Box key={cmd.name} paddingX={1}>
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
            <Text color={themeColors.dim}>{'  '}{cmd.description}</Text>
          </Box>
        );
      })}

      {/* ── Scroll indicator: below — always one line ── */}
      <Box paddingX={2}>
        {belowCount > 0
          ? <Text color={themeColors.dim}>↓ {belowCount} more</Text>
          : <Text> </Text>
        }
      </Box>

      {/* ── Footer key hints ── */}
      <Box paddingX={1}>
        <Text color={themeColors.dim} dimColor>
          {'↑↓ navigate  tab/↵ accept  esc dismiss'}
        </Text>
      </Box>

    </Box>
  );
}
