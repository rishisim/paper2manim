/**
 * PromptBar — The main input component, styled like Claude Code CLI.
 *
 * Features:
 * - Colored left border (promptColor from settings)
 * - "/ for commands" hint when empty
 * - Slash command autocomplete via SlashCommandOverlay
 * - "!" prefix routes to bash mode
 * - ControlledTextInput with full cursor control
 * - Model + permission mode shown below input
 */

import React, { useState, useCallback } from 'react';
import { Box, Text } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import { ControlledTextInput } from './ControlledTextInput.js';
import { SlashCommandOverlay } from './SlashCommandOverlay.js';
import { findCommand } from '../lib/commands.js';
import type { SlashCommand, AppDispatch } from '../lib/types.js';
import { PERMISSION_MODE_LABELS } from '../lib/types.js';

interface PromptBarProps {
  onSubmit: (value: string) => void;
  dispatch: AppDispatch;
  isDisabled?: boolean;
  placeholder?: string;
  /** Called synchronously when slash mode opens or closes, so the parent can
   *  immediately suspend any competing key handlers. */
  onSlashModeChange?: (active: boolean) => void;
}

export function PromptBar({ onSubmit, dispatch, isDisabled = false, placeholder, onSlashModeChange }: PromptBarProps) {
  const {
    themeColors,
    promptColor,
    permissionMode,
    currentModel,
  } = useAppContext();

  const [value, setValue] = useState('');
  const [slashMode, setSlashMode] = useState(false);
  const [slashQuery, setSlashQuery] = useState('');

  /** Open or close slash mode, notifying the parent synchronously. */
  const setSlash = useCallback((active: boolean, query = '') => {
    setSlashMode(active);
    setSlashQuery(active ? query : '');
    onSlashModeChange?.(active);
  }, [onSlashModeChange]);

  const handleChange = useCallback((v: string) => {
    setValue(v);
    if (v.startsWith('/')) {
      setSlash(true, v.slice(1));
    } else {
      setSlash(false);
    }
  }, [setSlash]);

  const handleSubmit = useCallback((v: string) => {
    const trimmed = v.trim();
    if (!trimmed) return;

    if (trimmed.startsWith('/')) {
      const parts = trimmed.slice(1).split(' ');
      const cmdName = parts[0] ?? '';
      const args = parts.slice(1);
      const cmd = findCommand(cmdName);
      if (cmd) {
        setValue('');
        setSlash(false);
        cmd.handler(args, dispatch);
      } else {
        dispatch.showMessage(`Unknown command: /${cmdName}  — type /help for a list`, undefined);
        setValue('');
        setSlash(false);
      }
      return;
    }

    if (trimmed.startsWith('!')) {
      dispatch.showMessage(`Bash: ${trimmed.slice(1).trim()}`, undefined);
      setValue('');
      return;
    }

    setValue('');
    setSlash(false);
    onSubmit(trimmed);
  }, [dispatch, onSubmit, setSlash]);

  const handleSlashMode = useCallback((query: string) => {
    setSlash(true, query);
  }, [setSlash]);

  const handleAcceptCommand = useCallback((cmd: SlashCommand) => {
    if (cmd.args) {
      // Leave in input so user can fill in the required argument
      setValue(`/${cmd.name} `);
      setSlash(true, cmd.name + ' ');
    } else {
      setValue('');
      setSlash(false);
      cmd.handler([], dispatch);
    }
  }, [dispatch, setSlash]);

  const handleDismissSlash = useCallback(() => {
    setSlash(false);
  }, [setSlash]);

  const modelShort = currentModel
    .replace('claude-', '')
    .replace('-4-6', ' 4.6')
    .replace('-4-5', ' 4.5');

  const modeLabel = PERMISSION_MODE_LABELS[permissionMode] ?? permissionMode;
  const modeColor =
    permissionMode === 'plan' ? themeColors.warn :
    permissionMode === 'auto' ? themeColors.success :
    permissionMode === 'bypassPermissions' ? themeColors.error :
    themeColors.dim;

  return (
    <Box flexDirection="column">
      {/* Slash command dropdown — shown above input */}
      {slashMode && (
        <SlashCommandOverlay
          query={slashQuery}
          onAccept={handleAcceptCommand}
          onDismiss={handleDismissSlash}
          isActive={slashMode && !isDisabled}
        />
      )}

      {/* Input box — colored round border, Claude Code style */}
      <Box borderStyle="round" borderColor={promptColor} paddingX={1}>
        <ControlledTextInput
          value={value}
          onChange={handleChange}
          onSubmit={handleSubmit}
          onSlashMode={handleSlashMode}
          placeholder={placeholder ?? 'Type a concept, or / for commands, ! for bash…'}
          isDisabled={isDisabled}
          focus={!isDisabled}
          slashModeActive={slashMode}
        />
      </Box>

      {/* Sub-row: model · mode · hint */}
      <Box paddingLeft={1}>
        <Text color={themeColors.dim}>
          <Text color={themeColors.muted}>{modelShort}</Text>
          <Text> · </Text>
          <Text color={modeColor}>{modeLabel}</Text>
          <Text color={themeColors.dim}>  (</Text>
          <Text color={themeColors.primary} bold>/</Text>
          <Text color={themeColors.dim}> for commands · </Text>
          <Text color={themeColors.primary} bold>!</Text>
          <Text color={themeColors.dim}> for bash · </Text>
          <Text color={themeColors.primary} bold>Shift+Tab</Text>
          <Text color={themeColors.dim}> to cycle mode)</Text>
        </Text>
      </Box>
    </Box>
  );
}
