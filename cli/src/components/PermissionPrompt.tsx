/**
 * PermissionPrompt — Inline permission confirmation overlay.
 * Shown when the pipeline requests permission to write files/run commands.
 * Mirrors Claude Code CLI's permission dialog.
 */

import React from 'react';
import { Box, Text, useInput } from 'ink';
import { useAppContext } from '../context/AppContext.js';

interface PermissionPromptProps {
  operation: string;
  path?: string;
  onAllow: () => void;
  onDeny: () => void;
  onAllowAlways: () => void;
}

export function PermissionPrompt({ operation, path, onAllow, onDeny, onAllowAlways }: PermissionPromptProps) {
  const { themeColors, permissionMode } = useAppContext();

  // In acceptEdits/auto/bypassPermissions mode — auto-allow without showing prompt
  React.useEffect(() => {
    if (permissionMode === 'acceptEdits' || permissionMode === 'auto' || permissionMode === 'bypassPermissions') {
      onAllow();
    } else if (permissionMode === 'plan') {
      onDeny();
    }
  }, [permissionMode]); // eslint-disable-line react-hooks/exhaustive-deps

  useInput((_input, key) => {
    const lower = _input.toLowerCase();
    if (lower === 'y' || key.return) {
      onAllow();
      return;
    }
    if (lower === 'n' || key.escape) {
      onDeny();
      return;
    }
    if (lower === 'a') {
      onAllowAlways();
      return;
    }
  });

  // In non-default mode, the useEffect handles it automatically
  if (permissionMode !== 'default') return null;

  const opLabel = operation === 'write_file' ? 'write file' : operation;

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={themeColors.warn}
      paddingX={2}
      paddingY={1}
      marginTop={1}
    >
      <Text bold color={themeColors.warn}>Permission Required</Text>
      <Box marginTop={1}>
        <Text color={themeColors.text}>
          The pipeline wants to <Text bold color={themeColors.primary}>{opLabel}</Text>
          {path && (
            <Text color={themeColors.dim}>{'\n  '}{path}</Text>
          )}
        </Text>
      </Box>
      <Box marginTop={1}>
        <Text color={themeColors.dim}>
          <Text color={themeColors.success} bold>y</Text>
          <Text color={themeColors.dim}> allow  </Text>
          <Text color={themeColors.error} bold>n</Text>
          <Text color={themeColors.dim}> deny  </Text>
          <Text color={themeColors.warn} bold>a</Text>
          <Text color={themeColors.dim}> allow always</Text>
        </Text>
      </Box>
    </Box>
  );
}
