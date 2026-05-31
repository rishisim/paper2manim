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
import type { ProgressMode } from '../lib/types.js';

interface FooterStatusLineProps {
  stage: StageName | null;
  progress?: number; // 0-100, shown as compact percentage
  progressMode?: ProgressMode;
  verboseModeOverride?: boolean;
  hintText?: string;
  elapsedSeconds?: number;
  segmentsCompleted?: number;
  totalSegments?: number;
}

interface FooterVisibility {
  showElapsed: boolean;
  showSegments: boolean;
  showProgress: boolean;
  showTokens: boolean;
  showHint: boolean;
}

export function getFooterProgressLabel(progress: number, progressMode: ProgressMode): string {
  if (progressMode === 'indeterminate') return 'estimating...';
  return `${Math.round(progress)}%`;
}

export function getFooterVisibility(termWidth: number, isRunning: boolean, hasTokens: boolean): FooterVisibility {
  return {
    showElapsed: isRunning && termWidth >= 60,
    showSegments: isRunning && termWidth >= 76,
    showProgress: isRunning && termWidth >= 68,
    showTokens: hasTokens && termWidth >= 160,
    showHint: isRunning && termWidth >= 80,
  };
}

export function FooterStatusLine({
  stage,
  progress,
  progressMode = 'indeterminate',
  verboseModeOverride,
  hintText,
  elapsedSeconds,
  segmentsCompleted,
  totalSegments,
}: FooterStatusLineProps) {
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
    .replace('openai-default', 'openai hybrid')
    .replace('anthropic-legacy', 'anthropic legacy')
    .replace('gpt-5.3-codex', 'gpt 5.3 codex')
    .replace('gpt-5.4-mini', 'gpt 5.4 mini')
    .replace('gpt-5.4', 'gpt 5.4')
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

  const isRunning = !!stage && stage !== 'done';
  const visibility = getFooterVisibility(termWidth, isRunning, totalTokens > 0);
  const segDone = Math.max(0, segmentsCompleted ?? 0);

  return (
    <Box flexDirection="column" marginTop={1} paddingLeft={1}>
      {/* Line 1: status info */}
      <Text dimColor>
        <Text color={themeColors.muted}>{modelShort}</Text>
        <Text dimColor>{' · '}</Text>
        <Text color={modeColor}>{modeSymbol}{modeSymbol ? ' ' : ''}{modeLabel}</Text>
        {visibility.showElapsed && elapsedSeconds !== undefined && (
          <Text><Text dimColor>{' · '}</Text><Text color={themeColors.muted}>{Math.round(elapsedSeconds)}s</Text></Text>
        )}
        {visibility.showSegments && totalSegments !== undefined && totalSegments > 0 && (
          <Text><Text dimColor>{' · '}</Text><Text color={themeColors.primary}>{segDone}/{totalSegments} done</Text></Text>
        )}
        {visibility.showProgress && progress !== undefined && (
          <Text>
            <Text dimColor>{' · '}</Text>
            <Text color={progressMode === 'determinate' ? themeColors.dim : themeColors.warn}>
              {getFooterProgressLabel(progress, progressMode)}
            </Text>
          </Text>
        )}
        {visibility.showTokens && (
          <Text><Text dimColor>{' · '}</Text><Text color={tokenColor}>{tokenStr} tokens</Text></Text>
        )}
      </Text>

      {/* Line 2: hint footnotes — always visible */}
      {hintText && (
        <Text color={themeColors.dim}>{hintText}</Text>
      )}
    </Box>
  );
}
