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
  onEmptySubmit?: () => void;
  onSlashMode?: (partialCommand: string) => void;
  onBashMode?: (command: string) => void;
  onFileRef?: (partial: string) => void;
  placeholder?: string;
  isDisabled?: boolean;
  focus?: boolean;
  /** When true the slash-command overlay is visible — suppress up/down so only the overlay navigates. */
  slashModeActive?: boolean;
  /** When true, skip command-history handling for Up/Down and allow custom navigation callbacks. */
  disableHistoryNavigation?: boolean;
  /** Optional section-level navigation callback for Up arrow. */
  onNavigateUp?: () => void;
  /** Optional section-level navigation callback for Down arrow. */
  onNavigateDown?: () => void;
  /** Keep the input text after Enter instead of clearing it. */
  clearOnSubmit?: boolean;
}

export function ControlledTextInput({
  value,
  onChange,
  onSubmit,
  onEmptySubmit,
  onSlashMode,
  onBashMode,
  placeholder,
  isDisabled = false,
  focus = true,
  slashModeActive = false,
  disableHistoryNavigation = false,
  onNavigateUp,
  onNavigateDown,
  clearOnSubmit = true,
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

  // Double-Esc to clear prompt
  const lastEscTime = useRef(0);

  // Live refs — updated synchronously inside useInput so that rapid input
  // (e.g. paste or pty sends all chars in a single event-loop task, before
  // React can flush batched state updates) is tracked correctly.
  const liveValueRef = useRef(value);
  const liveCursorRef = useRef(value.length);
  const liveSlashModeRef = useRef(slashModeActive);

  // Sync value ref when the parent re-renders with updated props.
  // Keep cursor stable instead of snapping to end on every edit.
  useEffect(() => {
    liveValueRef.current = value;
    const clamped = Math.min(liveCursorRef.current, value.length);
    liveCursorRef.current = clamped;
    setCursor(prev => Math.min(prev, value.length));
  }, [value]);
  // Sync slash mode ref SYNCHRONOUSLY during render so useInput handlers always see the
  // current value (useEffect is deferred and the ref can be stale by the time Enter fires).
  liveSlashModeRef.current = slashModeActive;

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

    // Esc+Esc — clear prompt text
    if (key.escape) {
      const now = Date.now();
      if (now - lastEscTime.current < 500 && liveValueRef.current.length > 0) {
        liveValueRef.current = '';
        liveCursorRef.current = 0;
        onChange('');
        setCursor(0);
        setHistoryIdx(-1);
      }
      lastEscTime.current = now;
      return;
    }

    // Enter — submit (unless it's a modifier+enter for newline, or slash overlay is active)
    // Also handle input==='\n': pty ICRNL converts \r→\n, which Ink parses as name='enter'
    // (key.return=false), so we need to catch both.
    if ((key.return || input === '\n') && !key.meta && !key.shift && !liveSlashModeRef.current) {
      const trimmed = liveValueRef.current.trim();
      if (trimmed) {
        // Handle ! prefix — bash mode
        if (trimmed.startsWith('!') && onBashMode) {
          onBashMode(trimmed.slice(1).trim());
          liveValueRef.current = '';
          liveCursorRef.current = 0;
          onChange('');
          setCursor(0);
          setHistoryIdx(-1);
          return;
        }
        onSubmit(trimmed);
        if (clearOnSubmit) {
          liveValueRef.current = '';
          liveCursorRef.current = 0;
          onChange('');
          setCursor(0);
        } else {
          const endPos = liveValueRef.current.length;
          liveCursorRef.current = endPos;
          setCursor(endPos);
        }
        setHistoryIdx(-1);
      }
      else {
        onEmptySubmit?.();
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
    if (liveSlashModeRef.current && (key.upArrow || key.downArrow)) return;

    // Up arrow — navigate history backwards
    if (key.upArrow) {
      if (onNavigateUp) {
        onNavigateUp();
        return;
      }
      if (disableHistoryNavigation) return;
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
      if (onNavigateDown) {
        onNavigateDown();
        return;
      }
      if (disableHistoryNavigation) return;
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
      const newC = Math.max(0, liveCursorRef.current - 1);
      liveCursorRef.current = newC;
      setCursor(newC);
      return;
    }

    // Right arrow
    if (key.rightArrow) {
      const newC = Math.min(liveValueRef.current.length, liveCursorRef.current + 1);
      liveCursorRef.current = newC;
      setCursor(newC);
      return;
    }

    // Ctrl+A — move to start
    if (key.ctrl && input === 'a') {
      liveCursorRef.current = 0;
      setCursor(0);
      return;
    }

    // Ctrl+E — move to end
    if (key.ctrl && input === 'e') {
      const endPos = liveValueRef.current.length;
      liveCursorRef.current = endPos;
      setCursor(endPos);
      return;
    }

    // Ctrl+K — delete from cursor to end
    if (key.ctrl && input === 'k') {
      const lv = liveValueRef.current;
      const lc = liveCursorRef.current;
      const next = lv.slice(0, lc);
      liveValueRef.current = next;
      onChange(next);
      return;
    }

    // Ctrl+U — delete from start to cursor
    if (key.ctrl && input === 'u') {
      const lv = liveValueRef.current;
      const lc = liveCursorRef.current;
      const next = lv.slice(lc);
      liveValueRef.current = next;
      liveCursorRef.current = 0;
      onChange(next);
      setCursor(0);
      return;
    }

    // Ctrl+W — delete word before cursor
    if (key.ctrl && input === 'w') {
      const lv = liveValueRef.current;
      const lc = liveCursorRef.current;
      const start = findWordBoundaryLeft(lv, lc);
      const next = deleteRange(lv, start, lc);
      liveValueRef.current = next;
      liveCursorRef.current = start;
      onChange(next);
      setCursor(start);
      return;
    }

    // Alt+B — move back one word
    if (key.meta && input === 'b') {
      const newC = findWordBoundaryLeft(liveValueRef.current, liveCursorRef.current);
      liveCursorRef.current = newC;
      setCursor(newC);
      return;
    }

    // Alt+F — move forward one word
    if (key.meta && input === 'f') {
      const newC = findWordBoundaryRight(liveValueRef.current, liveCursorRef.current);
      liveCursorRef.current = newC;
      setCursor(newC);
      return;
    }

    // Backspace
    if (key.backspace || key.delete) {
      const lv = liveValueRef.current;
      const lc = liveCursorRef.current;
      if (lc > 0) {
        const next = deleteRange(lv, lc - 1, lc);
        const newC = lc - 1;
        liveValueRef.current = next;
        liveCursorRef.current = newC;
        onChange(next);
        setCursor(newC);
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
    if (input === '/' && liveCursorRef.current === 0 && liveValueRef.current === '' && onSlashMode) {
      const next = '/';
      liveValueRef.current = next;
      liveCursorRef.current = 1;
      onChange(next);
      setCursor(1);
      onSlashMode('');
      return;
    }

    // Regular character input — explicitly exclude special keys that have their
    // own handlers above (return is handled above; '\n' from pty ICRNL must also
    // be excluded here, or it would be inserted as a literal newline character
    // when slash mode is active and intercepts the Enter).
    if (input && !key.ctrl && !key.meta && !key.return && input !== '\n' && input.length > 0) {
      const lv = liveValueRef.current;
      const lc = liveCursorRef.current;
      const next = insertAt(lv, lc, input);
      const newCursor = lc + input.length;
      liveValueRef.current = next;
      liveCursorRef.current = newCursor;
      onChange(next);
      setCursor(newCursor);

      // Notify slash mode only while the query has no space yet (mirrors PromptBar.handleChange logic)
      if (next.startsWith('/') && onSlashMode) {
        const q = next.slice(1);
        if (!q.includes(' ')) onSlashMode(q);
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
