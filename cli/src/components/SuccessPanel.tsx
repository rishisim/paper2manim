import React from 'react';
import { Box, Text } from 'ink';
import { RESULT_MARKER } from '../lib/theme.js';
import { useAppContext } from '../context/AppContext.js';

interface SuccessPanelProps {
  videoPath: string;
}

export function SuccessPanel({ videoPath }: SuccessPanelProps) {
  const { themeColors } = useAppContext();
  return (
    <Box flexDirection="column" marginTop={1} paddingLeft={1}>
      <Text bold color={themeColors.success}>✔ Output ready</Text>
      <Box paddingLeft={2}>
        <Text color={themeColors.dim}>{RESULT_MARKER} </Text>
        <Text bold>{videoPath}</Text>
      </Box>
    </Box>
  );
}
