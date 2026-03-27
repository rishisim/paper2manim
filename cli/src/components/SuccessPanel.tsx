import React from 'react';
import { Box, Text } from 'ink';
import { colors } from '../lib/theme.js';

interface SuccessPanelProps {
  videoPath: string;
}

export function SuccessPanel({ videoPath }: SuccessPanelProps) {
  return (
    <Box marginTop={1} paddingLeft={1}>
      <Text>
        <Text bold color={colors.success}>✓ Output ready</Text>
        <Text color={colors.dim}>  </Text>
        <Text bold>{videoPath}</Text>
      </Text>
    </Box>
  );
}
