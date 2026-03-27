/**
 * FooterStatusLine — Fixed bottom status line shown on every screen.
 * Displays: model · permission-mode · token-usage · stage · git-branch
 * Mirrors Claude Code CLI's status line.
 */

import React from 'react';
import { Box, Text } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import { PERMISSION_MODE_LABELS } from '../lib/types.js';
import type { StageName } from '../lib/theme.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';

interface FooterStatusLineProps {
  stage: StageName | null;
}

export function FooterStatusLine({ stage }: FooterStatusLineProps) {
  const {
    themeColors,
    permissionMode,
    currentModel,
    tokenUsage,
    gitBranch,
    quality,
    verboseMode,
  } = useAppContext();

  const termWidth = useTerminalWidth();

  // Format token count compactly
  const totalTokens = tokenUsage.input + tokenUsage.output;
  const tokenStr = totalTokens > 0
    ? totalTokens >= 1000
      ? `${(totalTokens / 1000).toFixed(1)}k`
      : `${totalTokens}`
    : '0';

  const modeLabel = PERMISSION_MODE_LABELS[permissionMode] ?? permissionMode;

  // H14: Short model name — strip date suffixes generically so new models work
  const modelShort = currentModel
    .replace('claude-', '')
    .replace(/-\d{8}$/, '')         // strip -YYYYMMDD date suffix
    .replace(/-preview$/, '')       // strip -preview suffix
    .replace(/-4-6/, ' 4.6')
    .replace(/-4-5/, ' 4.5')
    .replace(/-4-0/, ' 4.0');

  const qualityIcon = quality === 'low' ? '⚡' : quality === 'medium' ? '◆' : '◈';

  const stageStr = stage && stage !== 'done' ? ` · ${stage}` : '';
  const branchStr = gitBranch ? ` · ⎇ ${gitBranch}` : '';
  const verboseStr = verboseMode ? ' · verbose' : '';

  // Dim separator between sections
  const sep = ' · ';

  return (
    <Box marginTop={1}>
      <Text color={themeColors.dim} dimColor>
        <Text color={themeColors.muted}>{modelShort}</Text>
        <Text>{sep}</Text>
        <Text color={
          permissionMode === 'plan' ? themeColors.warn :
          permissionMode === 'auto' ? themeColors.success :
          permissionMode === 'bypassPermissions' ? themeColors.error :
          themeColors.dim
        }>{modeLabel}</Text>
        {totalTokens > 0 && (
          <Text>{sep}<Text color={themeColors.muted}>💬 {tokenStr}</Text></Text>
        )}
        {stage && stage !== 'done' && (
          <Text>{sep}<Text color={themeColors.primary}>{stage}</Text></Text>
        )}
        {gitBranch && (
          <Text>{sep}<Text color={themeColors.muted}>⎇ {gitBranch}</Text></Text>
        )}
        {verboseMode && (
          <Text>{sep}<Text color={themeColors.warn}>verbose</Text></Text>
        )}
      </Text>
    </Box>
  );
}
