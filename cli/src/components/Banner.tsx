import React from 'react';
import { Box, Text } from 'ink';
import { colors, VERSION, MODEL_TAG, BRAND_ICON, TIPS, truncatePath } from '../lib/theme.js';

const tip = TIPS[Math.floor(Math.random() * TIPS.length)]!;

export function Banner() {
  const cwd = process.cwd();
  // Inner width = box width - 2 (border) - 4 (paddingX=2 each side)
  const innerWidth = 56;
  const boxWidth = innerWidth + 6;

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={colors.primary}
      paddingX={2}
      paddingY={0}
      marginBottom={1}
      width={boxWidth}
    >
      <Text>
        <Text bold color={colors.primary}>{BRAND_ICON}</Text>
        <Text bold color={colors.text}> paper2manim</Text>
        <Text color={colors.dim}>  v{VERSION}</Text>
      </Text>
      <Text> </Text>
      <Text color={colors.dim}>  Model: {MODEL_TAG}</Text>
      <Text color={colors.dim}>  cwd: {truncatePath(cwd, innerWidth - 7)}</Text>
      <Text> </Text>
      <Text color={colors.dim}>  Tip: {tip}</Text>
    </Box>
  );
}
