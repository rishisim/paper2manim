/**
 * PermissionPrompt — Inline permission confirmation overlay.
 * Shown when the pipeline requests permission to write files/run commands.
 * Claude Code CLI style — horizontal divider in permission color (lavender),
 * bold title, and action key hints.
 */

import React, { useRef } from 'react';
import { Box, Text, useInput } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';

interface PermissionPromptProps {
  operation: string;
  path?: string;
  onAllow: () => void;
  onDeny: () => void;
  onAllowAlways: () => void;
}

export function PermissionPrompt({ operation, path, onAllow, onDeny, onAllowAlways }: PermissionPromptProps) {
  const { themeColors, permissionMode } = useAppContext();
  const termWidth = useTerminalWidth();

  // H11: One-shot ref guard prevents onAllow/onDeny from firing more than once
  const called = useRef(false);

  // In acceptEdits/auto/bypassPermissions mode — auto-allow without showing prompt
  React.useEffect(() => {
    if (called.current) return;
    if (permissionMode === 'acceptEdits' || permissionMode === 'auto' || permissionMode === 'bypassPermissions') {
      called.current = true;
      onAllow();
    } else if (permissionMode === 'plan') {
      called.current = true;
      onDeny();
    }
  }, [permissionMode, onAllow, onDeny]);

  useInput((_input, key) => {
    if (called.current) return;
    const lower = _input.toLowerCase();
    if (lower === 'y' || key.return) {
      called.current = true;
      onAllow();
      return;
    }
    if (lower === 'n' || key.escape) {
      called.current = true;
      onDeny();
      return;
    }
    if (lower === 'a') {
      called.current = true;
      onAllowAlways();
      return;
    }
  });

  // In non-default mode, the useEffect handles it automatically
  if (permissionMode !== 'default') return null;

  const opLabel = operation === 'write_file' ? 'write file' : operation;
  const dividerWidth = Math.min(termWidth - 4, 60);

  return (
    <Box flexDirection="column" paddingX={2} marginTop={1}>
      {/* Horizontal divider in permission/accent color (Claude Code's lavender) */}
      <Text color={themeColors.accent}>{'─'.repeat(dividerWidth)}</Text>

      <Box paddingTop={1} flexDirection="column">
        <Text bold color={themeColors.accent}>Permission Required</Text>
        <Box paddingLeft={0} marginTop={0}>
          <Text color={themeColors.text}>
            The pipeline wants to <Text bold color={themeColors.primary}>{opLabel}</Text>
          </Text>
        </Box>
        {path && (
          <Box paddingLeft={2}>
            <Text color={themeColors.dim}>{path}</Text>
          </Box>
        )}
      </Box>

      <Box marginTop={1}>
        <Text dimColor>
          <Text color={themeColors.success} bold>y</Text>
          <Text dimColor>{' · '}allow  </Text>
          <Text color={themeColors.error} bold>n</Text>
          <Text dimColor>{' · '}deny  </Text>
          <Text color={themeColors.accent} bold>a</Text>
          <Text dimColor>{' · '}always allow</Text>
        </Text>
      </Box>
    </Box>
  );
}
