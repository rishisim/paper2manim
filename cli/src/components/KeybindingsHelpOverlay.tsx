/**
 * KeybindingsHelpOverlay — Full listing of all keyboard shortcuts.
 * Shown on /keybindings command or the ? key during generation.
 */

import React from 'react';
import { Box, Text, useInput } from 'ink';
import { useAppContext } from '../context/AppContext.js';

interface Shortcut {
  key: string;
  description: string;
}

interface ShortcutGroup {
  label: string;
  shortcuts: Shortcut[];
}

const SHORTCUT_GROUPS: ShortcutGroup[] = [
  {
    label: 'Global',
    shortcuts: [
      { key: 'Ctrl+C',    description: 'Cancel current generation (press twice outside run to exit)' },
      { key: 'Ctrl+D',    description: 'Exit paper2manim immediately' },
      { key: 'Ctrl+L',    description: 'Clear terminal screen (preserves log history)' },
      { key: 'Ctrl+O',    description: 'Toggle verbose output mode' },
      { key: 'Shift+Tab', description: 'Cycle permission mode (default → acceptEdits → plan → auto → bypass)' },
      { key: 'Alt+T',     description: 'Toggle thinking/planning text display' },
      { key: 'Alt+O',     description: 'Toggle fast/lite mode (quality low ↔ high)' },
      { key: 'Alt+P',     description: 'Cycle model (opus ↔ sonnet), persists to settings' },
      { key: 'Esc+Esc',   description: 'Rewind to previous checkpoint or go back to input' },
      { key: '?',         description: 'Toggle this help (during generation)' },
    ],
  },
  {
    label: 'Text Input',
    shortcuts: [
      { key: 'Ctrl+K',     description: 'Delete from cursor to end of line' },
      { key: 'Ctrl+U',     description: 'Clear entire input line' },
      { key: 'Ctrl+W',     description: 'Delete word before cursor' },
      { key: 'Ctrl+A',     description: 'Move cursor to start of line' },
      { key: 'Ctrl+E',     description: 'Move cursor to end of line' },
      { key: 'Ctrl+R',     description: 'Reverse history search (type to filter)' },
      { key: 'Alt+B',      description: 'Move cursor back one word' },
      { key: 'Alt+F',      description: 'Move cursor forward one word' },
      { key: '↑/↓',        description: 'Navigate command history' },
      { key: '\\+Enter',   description: 'Insert newline (multiline input)' },
      { key: 'Alt+Enter',  description: 'Insert newline (multiline input)' },
    ],
  },
  {
    label: 'Commands',
    shortcuts: [
      { key: '/',          description: 'Open slash command menu (e.g. /generate, /help)' },
      { key: '!',          description: 'Run shell command directly (bash mode)' },
      { key: 'Tab',        description: 'Accept first slash command autocomplete suggestion' },
      { key: 'Esc',        description: 'Dismiss slash command dropdown / cancel prompt' },
    ],
  },
  {
    label: 'Key Slash Commands',
    shortcuts: [
      { key: '/generate <concept>', description: 'Start video generation' },
      { key: '/list',               description: 'Open workspace project browser' },
      { key: '/config',             description: 'Open settings panel' },
      { key: '/theme [name]',       description: 'Switch color theme' },
      { key: '/model [name]',       description: 'Switch AI model' },
      { key: '/quality [level]',    description: 'Set render quality' },
      { key: '/doctor',             description: 'Diagnose installation' },
      { key: '/clear',              description: 'Clear screen and reset to input' },
      { key: '/help',               description: 'Show this page' },
      { key: '/exit',               description: 'Exit paper2manim' },
    ],
  },
];

interface KeybindingsHelpOverlayProps {
  onBack: () => void;
}

export function KeybindingsHelpOverlay({ onBack }: KeybindingsHelpOverlayProps) {
  const { themeColors } = useAppContext();

  useInput((_input, key) => {
    if (key.escape || _input === 'q') onBack();
  });

  return (
    <Box flexDirection="column" paddingX={1}>
      <Box marginBottom={1}>
        <Text bold color={themeColors.primary}>Keyboard Shortcuts  ·  paper2manim</Text>
      </Box>

      {SHORTCUT_GROUPS.map(group => (
        <Box key={group.label} flexDirection="column" marginBottom={1}>
          <Text bold color={themeColors.accent}>{group.label}</Text>
          {group.shortcuts.map(shortcut => (
            <Box key={shortcut.key} paddingLeft={2}>
              <Text color={themeColors.primary} bold>{shortcut.key.padEnd(22)}</Text>
              <Text color={themeColors.dim}>{shortcut.description}</Text>
            </Box>
          ))}
        </Box>
      ))}

      <Box marginTop={1}>
        <Text color={themeColors.dim}>Press <Text color={themeColors.primary} bold>Esc</Text> or <Text color={themeColors.primary} bold>q</Text> to go back</Text>
      </Box>
    </Box>
  );
}
