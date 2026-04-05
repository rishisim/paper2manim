import React from 'react';
import { Box, Text } from 'ink';
import { useAppContext } from '../context/AppContext.js';

interface KeyboardShortcutsProps {
  verboseMode: boolean;
}

const SHORTCUTS = [
  { key: '?',         pad: 9, desc: 'Toggle this help' },
  { key: 'Ctrl+O',    pad: 4, desc: 'Toggle verbose mode' },
  { key: 'Ctrl+C',    pad: 4, desc: 'Cancel (press twice)' },
  { key: 'Ctrl+D',    pad: 4, desc: 'Exit immediately' },
  { key: 'Shift+Tab', pad: 2, desc: 'Cycle permission mode' },
  { key: 'Alt+T',     pad: 4, desc: 'Toggle thinking display' },
  { key: 'Alt+O',     pad: 4, desc: 'Toggle fast/lite mode' },
  { key: 'Alt+P',     pad: 4, desc: 'Cycle model' },
] as const;

export function KeyboardShortcuts({ verboseMode }: KeyboardShortcutsProps) {
  const { themeColors } = useAppContext();

  return (
    <Box flexDirection="column" marginTop={1} paddingLeft={2}>
      <Text bold color={themeColors.primary}>Keyboard shortcuts</Text>
      {SHORTCUTS.map(({ key, pad, desc }) => {
        const suffix = key === 'Ctrl+O' ? (verboseMode ? ' (ON)' : ' (OFF)') : '';
        return (
          <Box key={key}>
            <Text color={themeColors.dim}>{'  '}  </Text>
            <Text color={themeColors.primary} bold>{key}</Text>
            <Text color={themeColors.dim}>{' '.repeat(pad)}{desc}{suffix}</Text>
          </Box>
        );
      })}
      <Box marginTop={0}>
        <Text color={themeColors.dim}>  Press </Text>
        <Text color={themeColors.primary} bold>?</Text>
        <Text color={themeColors.dim}> to close</Text>
      </Box>
    </Box>
  );
}
