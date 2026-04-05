import React from 'react';
import { Box, Text } from 'ink';
import { VERSION, BRAND_ICON, RESULT_MARKER, truncatePath } from '../lib/theme.js';
import { useAppContext } from '../context/AppContext.js';

interface BannerProps {
  concept?: string;
}

/** Minimal header for the running screen — Claude Code style. */
export function Banner({ concept }: BannerProps) {
  const { themeColors, quality } = useAppContext();
  const cwd = process.cwd();
  const home = process.env['HOME'] ?? '';
  const displayCwd = home ? cwd.replace(home, '~') : cwd;

  return (
    <Box flexDirection="column" paddingX={1} marginBottom={1}>
      <Box>
        <Text bold color={themeColors.primary}>{BRAND_ICON}</Text>
        <Text bold color={themeColors.text}> paper2manim</Text>
        <Text color={themeColors.dim}> v{VERSION}</Text>
        {concept && (
          <Text color={themeColors.muted}> — {concept}</Text>
        )}
      </Box>
      <Box>
        <Text color={themeColors.dim}>{RESULT_MARKER} {truncatePath(displayCwd, 40)}</Text>
        <Text color={themeColors.dim}>  quality: {quality}</Text>
      </Box>
    </Box>
  );
}
