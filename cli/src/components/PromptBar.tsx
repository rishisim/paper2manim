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
import { useAppContext } from '../context/AppContext.js';
import { ControlledTextInput } from './ControlledTextInput.js';
import { SlashCommandOverlay } from './SlashCommandOverlay.js';
import { findCommand } from '../lib/commands.js';
import type { SlashCommand, AppDispatch } from '../lib/types.js';

interface PromptBarProps {
  onSubmit: (value: string) => void;
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
}

export function PromptBar({ onSubmit, dispatch, isDisabled = false, placeholder, onSlashModeChange, prefill, onPrefillConsumed }: PromptBarProps) {
  const {
    themeColors,
    promptColor,
  } = useAppContext();

  const [value, setValue] = useState('');
  const [slashMode, setSlashMode] = useState(false);
  const [slashQuery, setSlashQuery] = useState('');

  // Apply external prefill when it changes
  useEffect(() => {
    if (prefill !== undefined && prefill !== '') {
      setValue(prefill);
      onPrefillConsumed?.();
    }
  }, [prefill]); // eslint-disable-line react-hooks/exhaustive-deps

  /** Open or close slash mode, notifying the parent synchronously. */
  const setSlash = useCallback((active: boolean, query = '') => {
    setSlashMode(active);
    setSlashQuery(active ? query : '');
    onSlashModeChange?.(active);
  }, [onSlashModeChange]);

  const handleChange = useCallback((v: string) => {
    setValue(v);
    if (v.startsWith('/')) {
      const query = v.slice(1);
      // Only keep slash mode active while user is still typing the command name.
      // Once a space appears the overlay has no matches anyway, and leaving
      // slashMode=true would block Enter (ControlledTextInput line 131).
      setSlash(!query.includes(' '), query);
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
      // Leave in input so user can fill in the required argument.
      // Disable slash mode so Enter is no longer blocked by ControlledTextInput.
      setValue(`/${cmd.name} `);
      setSlash(false);
    } else {
      setValue('');
      setSlash(false);
      cmd.handler([], dispatch);
    }
  }, [dispatch, setSlash]);

  const handleDismissSlash = useCallback(() => {
    setSlash(false);
  }, [setSlash]);

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
      <Box borderStyle="round" borderColor={promptColor} paddingX={1}>
        <Text color={themeColors.success} bold>{'> '}</Text>
        <ControlledTextInput
          value={value}
          onChange={handleChange}
          onSubmit={handleSubmit}
          onSlashMode={handleSlashMode}
          placeholder={placeholder ?? 'Type a concept, or / for commands…'}
          isDisabled={isDisabled}
          focus={!isDisabled}
          slashModeActive={slashMode}
        />
      </Box>
    </Box>
  );
}
