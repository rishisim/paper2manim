/**
 * FooterStatusLine — Fixed bottom status line shown on every screen.
 * Displays: model · permission-mode · token-usage · stage · git-branch
 *
 * Matches Claude Code CLI's footer format with dimColor separators.
 * Token count uses three-tier color coding (green/yellow/red).
 */

import React from 'react';
import { Box, Text } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';
import { formatTokenCount } from '../lib/format.js';
import { MODE_SYMBOLS } from '../lib/theme.js';
import { PERMISSION_MODE_LABELS } from '../lib/types.js';
import type { StageName } from '../lib/theme.js';

interface FooterStatusLineProps {
  stage: StageName | null;
  progress?: number; // 0-100, shown as compact percentage
}

export function FooterStatusLine({ stage, progress }: FooterStatusLineProps) {
  const {
    themeColors,
    permissionMode,
    currentModel,
    tokenUsage,
    gitBranch,
    verboseMode,
  } = useAppContext();
  const termWidth = useTerminalWidth();

  const totalTokens = tokenUsage.input + tokenUsage.output;
  const tokenStr = formatTokenCount(totalTokens);

  // Three-tier context usage color (Claude Code style)
  const tokenColor = totalTokens > 150_000
    ? themeColors.contextHigh
    : totalTokens > 50_000
      ? themeColors.contextMid
      : themeColors.contextLow;

  const modeLabel = PERMISSION_MODE_LABELS[permissionMode] ?? permissionMode;
  const modeSymbol = MODE_SYMBOLS[permissionMode] ?? '';

  const modelShort = currentModel
    .replace('claude-', '')
    .replace(/-\d{8}$/, '')
    .replace(/-preview$/, '')
    .replace(/-4-6/, ' 4.6')
    .replace(/-4-5/, ' 4.5')
    .replace(/-4-0/, ' 4.0');

  // Claude Code mode colors
  const modeColor =
    permissionMode === 'plan' ? '#48968C' :           // Claude teal
    permissionMode === 'auto' ? themeColors.warn :     // Claude warning (yellow)
    permissionMode === 'acceptEdits' ? '#AF87FF' :     // Claude autoAccept (purple)
    permissionMode === 'bypassPermissions' ? themeColors.warn :
    themeColors.dim;

  // Progressive truncation based on terminal width
  const showTokens = termWidth >= 60 && totalTokens > 0;
  const showStage = termWidth >= 80 && stage && stage !== 'done';
  const showProgress = termWidth >= 70 && progress !== undefined && progress > 0 && progress < 100;
  const showBranch = termWidth >= 100 && gitBranch;
  const showVerbose = termWidth >= 100 && verboseMode;
  const showHint = termWidth >= 80 && stage && stage !== 'done';

  return (
    <Box marginTop={1} paddingLeft={1}>
      <Text dimColor>
        <Text color={themeColors.muted}>{modelShort}</Text>
        <Text dimColor>{' · '}</Text>
        <Text color={modeColor}>{modeSymbol}{modeSymbol ? ' ' : ''}{modeLabel}</Text>
        {showTokens && (
          <Text><Text dimColor>{' · '}</Text><Text color={tokenColor}>{tokenStr} tokens</Text></Text>
        )}
        {showStage && (
          <Text><Text dimColor>{' · '}</Text><Text color={themeColors.primary}>{stage}</Text></Text>
        )}
        {showProgress && (
          <Text><Text dimColor>{' · '}</Text><Text color={themeColors.muted}>{Math.round(progress!)}%</Text></Text>
        )}
        {showBranch && (
          <Text><Text dimColor>{' · '}</Text><Text color={themeColors.muted}>{gitBranch}</Text></Text>
        )}
        {showVerbose && (
          <Text><Text dimColor>{' · '}</Text><Text color={themeColors.warn}>verbose</Text></Text>
        )}
        {showHint && (
          <Text><Text dimColor>{' · '}</Text><Text color={themeColors.primary}>?</Text> help</Text>
        )}
      </Text>
    </Box>
  );
}
