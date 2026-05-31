import React from 'react';
import { Box, Text } from 'ink';
import { useAppContext } from '../context/AppContext.js';

interface KeyboardShortcutsProps {
  verboseMode?: boolean;
}

const SHORTCUTS = [
  { key: '↑ / ↓',   pad: 4, desc: 'Select segment' },
  { key: 'g',        pad: 9, desc: 'Follow active segment' },
  { key: 'Ctrl+O',   pad: 4, desc: 'Toggle verbose' },
  { key: 'Ctrl+C',   pad: 4, desc: 'Stop pipeline' },
] as const;

export function KeyboardShortcuts({ verboseMode: _verboseMode }: KeyboardShortcutsProps) {
  const { themeColors } = useAppContext();

  return (
    <Box flexDirection="column" marginTop={1} paddingLeft={2}>
      <Text bold color={themeColors.primary}>Keyboard shortcuts</Text>
      {SHORTCUTS.map(({ key, pad, desc }) => (
        <Box key={key}>
          <Text color={themeColors.dim}>{'  '}  </Text>
          <Text color={themeColors.primary} bold>{key}</Text>
          <Text color={themeColors.dim}>{' '.repeat(pad)}{desc}</Text>
        </Box>
      ))}
      <Box marginTop={0}>
        <Text color={themeColors.dim}>  Press </Text>
        <Text color={themeColors.primary} bold>?</Text>
        <Text color={themeColors.dim}> to close</Text>
      </Box>
    </Box>
  );
}
