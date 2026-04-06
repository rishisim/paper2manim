/**
 * PromptBar — The main input component, styled like Claude Code CLI.
 *
 * Features:
 * - Round-bordered input box with gray border (Claude Code style)
 * - ">" prompt character in success (green) color
 * - Slash command autocomplete via SlashCommandOverlay
 * - "!" prefix routes to bash mode
 * - ControlledTextInput with full cursor control
 */

import React, { useState, useCallback, useEffect } from 'react';
import { Box, Text } from 'ink';
import { spawnSync } from 'node:child_process';
import { useAppContext } from '../context/AppContext.js';
import { ControlledTextInput } from './ControlledTextInput.js';
import { SlashCommandOverlay } from './SlashCommandOverlay.js';
import { findCommand } from '../lib/commands.js';
import { getSafePromptBorderColor } from '../lib/theme.js';
import type { SlashCommand, AppDispatch } from '../lib/types.js';

interface PromptBarProps {
  onSubmit: (value: string) => void;
  onEmptySubmit?: () => void;
  onValueChange?: (value: string) => void;
  externalValue?: string;
  dispatch: AppDispatch;
  isDisabled?: boolean;
  placeholder?: string;
  /** Called synchronously when slash mode opens or closes, so the parent can
   *  immediately suspend any competing key handlers. */
  onSlashModeChange?: (active: boolean) => void;
  /** External text to inject into the input (e.g. from /surprise). */
  prefill?: string;
  /** Called after prefill has been consumed, so the parent can clear it. */
  onPrefillConsumed?: () => void;
  /** Keep text in the input after plain Enter submits. */
  preserveInputOnSubmit?: boolean;
  /** Disable command-history navigation in the input. */
  disableHistoryNavigation?: boolean;
  /** Optional section-level navigation callback for Up arrow. */
  onNavigateUp?: () => void;
  /** Optional section-level navigation callback for Down arrow. */
  onNavigateDown?: () => void;
}

export function PromptBar({
  onSubmit,
  onEmptySubmit,
  onValueChange,
  externalValue,
  dispatch,
  isDisabled = false,
  placeholder,
  onSlashModeChange,
  prefill,
  onPrefillConsumed,
  preserveInputOnSubmit = false,
  disableHistoryNavigation = false,
  onNavigateUp,
  onNavigateDown,
}: PromptBarProps) {
  const {
    themeColors,
    promptColor,
  } = useAppContext();
  const resolvedPromptColor = getSafePromptBorderColor(promptColor, themeColors);

  const [value, setValue] = useState('');
  const [slashMode, setSlashMode] = useState(false);
  const [slashQuery, setSlashQuery] = useState('');

  // Apply external prefill when it changes
  useEffect(() => {
    if (prefill !== undefined && prefill !== '') {
      setValue(prefill);
      onValueChange?.(prefill);
      onPrefillConsumed?.();
    }
  }, [onValueChange, prefill, onPrefillConsumed]);

  // Keep input persistent when parent manages draft state across remounts.
  useEffect(() => {
    if (externalValue !== undefined && externalValue !== value) {
      setValue(externalValue);
    }
  }, [externalValue]);

  /** Open or close slash mode, notifying the parent synchronously. */
  const setSlash = useCallback((active: boolean, query = '') => {
    setSlashMode(active);
    setSlashQuery(active ? query : '');
    onSlashModeChange?.(active);
  }, [onSlashModeChange]);

  const handleChange = useCallback((v: string) => {
    setValue(v);
    onValueChange?.(v);
    if (v.startsWith('/')) {
      const query = v.slice(1);
      // Only keep slash mode active while user is still typing the command name.
      // Once a space appears the overlay has no matches anyway, and leaving
      // slashMode=true would block Enter (ControlledTextInput line 131).
      setSlash(!query.includes(' '), query);
    } else {
      setSlash(false);
    }
  }, [onValueChange, setSlash]);

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
        onValueChange?.('');
        setSlash(false);
        cmd.handler(args, dispatch);
      } else {
        dispatch.showMessage(`Unknown command: /${cmdName}  — type /help for a list`, undefined);
        setValue('');
        onValueChange?.('');
        setSlash(false);
      }
      return;
    }

    if (trimmed.startsWith('!')) {
      const bashCommand = trimmed.slice(1).trim();
      if (!bashCommand) {
        dispatch.showMessage('Usage: !<shell-command>', undefined);
        setValue('');
        onValueChange?.('');
        setSlash(false);
        return;
      }
      const result = spawnSync(bashCommand, {
        shell: true,
        encoding: 'utf8',
        timeout: 30_000,
        maxBuffer: 1024 * 1024,
      });
      const combinedOutput = `${result.stdout ?? ''}${result.stderr ?? ''}`.trim();
      const outputPreview = combinedOutput
        ? combinedOutput.slice(0, 400) + (combinedOutput.length > 400 ? '…' : '')
        : '(no output)';
      if (result.error) {
        dispatch.showMessage(`Bash failed: ${result.error.message}`, 'red');
      } else if (result.status === 0) {
        dispatch.showMessage(`$ ${bashCommand}\n${outputPreview}`, undefined);
      } else {
        dispatch.showMessage(`$ ${bashCommand}\nExit ${result.status}: ${outputPreview}`, 'red');
      }
      setValue('');
      onValueChange?.('');
      setSlash(false);
      return;
    }

    onSubmit(trimmed);
    if (!preserveInputOnSubmit) {
      setValue('');
      onValueChange?.('');
    }
    setSlash(false);
  }, [dispatch, onSubmit, onValueChange, setSlash]);

  const handleSlashMode = useCallback((query: string) => {
    setSlash(true, query);
  }, [setSlash]);

  const handleAcceptCommand = useCallback((cmd: SlashCommand) => {
    if (cmd.args) {
      // Leave in input so user can fill in the required argument.
      // Disable slash mode so Enter is no longer blocked by ControlledTextInput.
      setValue(`/${cmd.name} `);
      onValueChange?.(`/${cmd.name} `);
      setSlash(false);
    } else {
      setValue('');
      onValueChange?.('');
      setSlash(false);
      cmd.handler([], dispatch);
    }
  }, [dispatch, onValueChange, setSlash]);

  const handleDismissSlash = useCallback(() => {
    if (externalValue !== undefined) {
      setValue(externalValue);
      onValueChange?.(externalValue);
    }
    setSlash(false);
  }, [externalValue, onValueChange, setSlash]);

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

      {/* Input box — round border in gray, Claude Code style */}
      <Box
        borderStyle="round"
        borderColor={isDisabled ? themeColors.separator : slashMode ? themeColors.accent : resolvedPromptColor}
        paddingX={1}
      >
        <Text color={themeColors.success} bold>{'> '}</Text>
        <ControlledTextInput
          value={value}
          onChange={handleChange}
          onSubmit={handleSubmit}
          onEmptySubmit={onEmptySubmit}
          onSlashMode={handleSlashMode}
          placeholder={placeholder ?? 'Type a topic + goal, or / for commands…'}
          isDisabled={isDisabled}
          focus={!isDisabled}
          slashModeActive={slashMode}
          disableHistoryNavigation={disableHistoryNavigation}
          onNavigateUp={onNavigateUp}
          onNavigateDown={onNavigateDown}
          clearOnSubmit={!preserveInputOnSubmit}
        />
      </Box>
    </Box>
  );
}
