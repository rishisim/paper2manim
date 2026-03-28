/**
 * ControlledTextInput — A fully-controlled text input with cursor management.
 * Replaces @inkjs/ui TextInput for cases requiring cursor position control.
 *
 * Supports: Ctrl+K (delete to end), Ctrl+U (clear line), Ctrl+A (start),
 *           Ctrl+E (end), Alt+B/F (word navigation), Ctrl+R (history search),
 *           multiline input (\+Enter), Up/Down arrow history navigation.
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Box, Text, useInput, useApp } from 'ink';
import { useAppContext } from '../context/AppContext.js';

interface ControlledTextInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  onSlashMode?: (partialCommand: string) => void;
  onBashMode?: (command: string) => void;
  onFileRef?: (partial: string) => void;
  placeholder?: string;
  isDisabled?: boolean;
  focus?: boolean;
  /** When true the slash-command overlay is visible — suppress up/down so only the overlay navigates. */
  slashModeActive?: boolean;
}

export function ControlledTextInput({
  value,
  onChange,
  onSubmit,
  onSlashMode,
  onBashMode,
  placeholder,
  isDisabled = false,
  focus = true,
  slashModeActive = false,
}: ControlledTextInputProps) {
  const { themeColors, commandHistory } = useAppContext();
  const [cursor, setCursor] = useState(value.length);

  // History navigation state
  const [historyIdx, setHistoryIdx] = useState(-1);
  const [savedInput, setSavedInput] = useState('');

  // History search mode
  const [searchMode, setSearchMode] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResult, setSearchResult] = useState('');

  // Keep cursor at end when value changes externally
  useEffect(() => {
    setCursor(value.length);
  }, [value.length]);

  const insertAt = useCallback((str: string, pos: number, insert: string): string => {
    return str.slice(0, pos) + insert + str.slice(pos);
  }, []);

  const deleteRange = useCallback((str: string, start: number, end: number): string => {
    return str.slice(0, start) + str.slice(end);
  }, []);

  // L2: Memoize word-boundary helpers so they have stable identity across renders
  const findWordBoundaryLeft = useCallback((str: string, pos: number): number => {
    let i = pos - 1;
    while (i > 0 && str[i] === ' ') i--;
    while (i > 0 && str[i - 1] !== ' ') i--;
    return i;
  }, []);

  const findWordBoundaryRight = useCallback((str: string, pos: number): number => {
    let i = pos;
    while (i < str.length && str[i] === ' ') i++;
    while (i < str.length && str[i] !== ' ') i++;
    return i;
  }, []);

  useInput((input, key) => {
    if (!focus || isDisabled) return;

    // History search mode
    if (searchMode) {
      if (key.escape || (key.ctrl && input === 'r' && !searchQuery)) {
        setSearchMode(false);
        setSearchQuery('');
        setSearchResult('');
        return;
      }
      if (key.return) {
        setSearchMode(false);
        const found = searchResult || value;
        onChange(found);
        setCursor(found.length);
        setSearchQuery('');
        setSearchResult('');
        return;
      }
      if (key.backspace || key.delete) {
        const q = searchQuery.slice(0, -1);
        setSearchQuery(q);
        const found = commandHistory.slice().reverse().find(h => h.includes(q)) ?? '';
        setSearchResult(found);
        return;
      }
      if (input && !key.ctrl && !key.meta) {
        const q = searchQuery + input;
        setSearchQuery(q);
        const found = commandHistory.slice().reverse().find(h => h.includes(q)) ?? '';
        setSearchResult(found);
        return;
      }
      return;
    }

    // Ctrl+R — enter history search mode
    if (key.ctrl && input === 'r') {
      setSearchMode(true);
      setSearchQuery('');
      setSearchResult('');
      return;
    }

    // Ctrl+C — handled by parent
    if (key.ctrl && input === 'c') return;

    // Ctrl+D — handled by parent
    if (key.ctrl && input === 'd') return;

    // Enter — submit (unless it's a modifier+enter for newline)
    if (key.return && !key.meta && !key.shift) {
      const trimmed = value.trim();
      if (trimmed) {
        // Handle ! prefix — bash mode
        if (trimmed.startsWith('!') && onBashMode) {
          onBashMode(trimmed.slice(1).trim());
          onChange('');
          setCursor(0);
          setHistoryIdx(-1);
          return;
        }
        onSubmit(trimmed);
        onChange('');
        setCursor(0);
        setHistoryIdx(-1);
      }
      return;
    }

    // Multiline: \ + Enter or Alt/Meta + Enter — insert newline
    if (key.return && (key.meta || key.shift)) {
      const next = insertAt(value, cursor, '\n');
      onChange(next);
      setCursor(cursor + 1);
      return;
    }

    // Up/down arrow — yielded entirely to the slash-command overlay when it is open
    if (slashModeActive && (key.upArrow || key.downArrow)) return;

    // Up arrow — navigate history backwards
    if (key.upArrow) {
      const len = commandHistory.length;
      if (len === 0) return;
      const newIdx = historyIdx === -1 ? len - 1 : Math.max(0, historyIdx - 1);
      // M2: Only save the current input when first entering history navigation
      if (historyIdx === -1) setSavedInput(value ?? '');
      setHistoryIdx(newIdx);
      const entry = commandHistory[newIdx] ?? '';
      onChange(entry);
      setCursor(entry.length);
      return;
    }

    // Down arrow — navigate history forwards
    if (key.downArrow) {
      if (historyIdx === -1) return;
      const newIdx = historyIdx + 1;
      if (newIdx >= commandHistory.length) {
        setHistoryIdx(-1);
        onChange(savedInput);
        setCursor(savedInput.length);
      } else {
        setHistoryIdx(newIdx);
        const entry = commandHistory[newIdx] ?? '';
        onChange(entry);
        setCursor(entry.length);
      }
      return;
    }

    // Left arrow
    if (key.leftArrow) {
      setCursor(c => Math.max(0, c - 1));
      return;
    }

    // Right arrow
    if (key.rightArrow) {
      setCursor(c => Math.min(value.length, c + 1));
      return;
    }

    // Ctrl+A — move to start
    if (key.ctrl && input === 'a') {
      setCursor(0);
      return;
    }

    // Ctrl+E — move to end
    if (key.ctrl && input === 'e') {
      setCursor(value.length);
      return;
    }

    // Ctrl+K — delete from cursor to end
    if (key.ctrl && input === 'k') {
      onChange(value.slice(0, cursor));
      return;
    }

    // Ctrl+U — delete from start to cursor
    if (key.ctrl && input === 'u') {
      onChange(value.slice(cursor));
      setCursor(0);
      return;
    }

    // Ctrl+W — delete word before cursor
    if (key.ctrl && input === 'w') {
      const start = findWordBoundaryLeft(value, cursor);
      onChange(deleteRange(value, start, cursor));
      setCursor(start);
      return;
    }

    // Alt+B — move back one word
    if (key.meta && input === 'b') {
      setCursor(findWordBoundaryLeft(value, cursor));
      return;
    }

    // Alt+F — move forward one word
    if (key.meta && input === 'f') {
      setCursor(findWordBoundaryRight(value, cursor));
      return;
    }

    // Backspace
    if (key.backspace || key.delete) {
      if (cursor > 0) {
        const next = deleteRange(value, cursor - 1, cursor);
        onChange(next);
        setCursor(c => c - 1);
      }
      return;
    }

    // Tab — autocomplete trigger (slash mode) or accept suggestion
    if (key.tab && !key.shift) {
      if (value.startsWith('/') && onSlashMode) {
        onSlashMode(value.slice(1));
      }
      return;
    }

    // M3: Slash at start — only activate slash mode when cursor is at 0 AND field is empty
    // (If cursor is mid-string, '/' should be inserted normally)
    if (input === '/' && cursor === 0 && value === '' && onSlashMode) {
      const next = '/';
      onChange(next);
      setCursor(1);
      onSlashMode('');
      return;
    }

    // Regular character input
    if (input && !key.ctrl && !key.meta && input.length > 0) {
      const next = insertAt(value, cursor, input);
      onChange(next);
      const newCursor = cursor + input.length;
      setCursor(newCursor);

      // Notify slash mode if input starts with /
      if (next.startsWith('/') && onSlashMode) {
        onSlashMode(next.slice(1));
      }

      return;
    }
  }, { isActive: focus && !isDisabled });

  // Render the text with cursor
  const renderText = () => {
    if (searchMode) {
      return (
        <Text>
          <Text color={themeColors.warn}>(reverse-i-search)</Text>
          <Text color={themeColors.dim}>{`'${searchQuery}'`}</Text>
          <Text>: </Text>
          <Text>{searchResult}</Text>
        </Text>
      );
    }

    if (!value && !focus) {
      return <Text color={themeColors.dim}>{placeholder ?? ''}</Text>;
    }

    if (!value && focus) {
      return (
        <Text>
          <Text color={themeColors.dim}>{placeholder ? placeholder.slice(0) : ''}</Text>
          <Text backgroundColor={themeColors.dim}> </Text>
        </Text>
      );
    }

    // Render value with cursor block
    const before = value.slice(0, cursor);
    const atCursor = value[cursor] ?? ' ';
    const after = value.slice(cursor + 1);

    return (
      <Text>
        <Text>{before}</Text>
        <Text backgroundColor={themeColors.primary} color={themeColors.bg}>{atCursor}</Text>
        <Text>{after}</Text>
      </Text>
    );
  };

  return renderText();
}
