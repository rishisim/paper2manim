/**
 * ContextVisualizer — Displays context window usage as a colored grid of blocks.
 * Mirrors Claude Code CLI's /context command.
 */

import React from 'react';
import { Box, Text, useInput } from 'ink';
import { useAppContext } from '../context/AppContext.js';

// Approximate context window sizes for models
const MODEL_CONTEXT_SIZES: Record<string, number> = {
  'openai-default': 1_050_000,
  'anthropic-legacy': 200_000,
  'gpt-5.4': 1_050_000,
  'gpt-5.3-codex': 400_000,
  'gpt-5.4-mini': 400_000,
  'claude-opus-4-6': 200000,
  'claude-sonnet-4-6': 200000,
  'claude-haiku-4-5': 200000,
};

const GRID_COLS = 50;
const GRID_ROWS = 8;
const TOTAL_CELLS = GRID_COLS * GRID_ROWS;

interface ContextVisualizerProps {
  onBack: () => void;
}

export function ContextVisualizer({ onBack }: ContextVisualizerProps) {
  const { themeColors, tokenUsage, currentModel } = useAppContext();

  const maxContext = MODEL_CONTEXT_SIZES[currentModel] ?? 200000;
  const usedTokens = tokenUsage.input + tokenUsage.output;
  const usedPct = Math.min(1, usedTokens / maxContext);
  const filledCells = Math.round(usedPct * TOTAL_CELLS);

  // Color based on usage
  const getCellColor = (cellIdx: number): string => {
    // L4: Guard against out-of-range index (defensive)
    if (cellIdx < 0 || cellIdx >= TOTAL_CELLS) return themeColors.dim;
    const cellPct = cellIdx / TOTAL_CELLS;
    if (cellIdx < filledCells) {
      if (cellPct < 0.5) return themeColors.success;
      if (cellPct < 0.8) return themeColors.warn;
      return themeColors.error;
    }
    return themeColors.dim;
  };

  useInput((_input, key) => {
    if (key.escape || _input === 'q') onBack();
  });

  // Build grid rows
  const rows: string[][] = [];
  for (let r = 0; r < GRID_ROWS; r++) {
    const row: string[] = [];
    for (let c = 0; c < GRID_COLS; c++) {
      const cellIdx = r * GRID_COLS + c;
      row.push(getCellColor(cellIdx));
    }
    rows.push(row);
  }

  return (
    <Box flexDirection="column" paddingX={1}>
      <Text bold color={themeColors.primary}>Context Window Usage</Text>
      <Box marginTop={1} flexDirection="column">
        {rows.map((row, rowIdx) => (
          <Box key={rowIdx} flexDirection="row">
            {row.map((color, colIdx) => (
              <Text key={colIdx} color={color}>█</Text>
            ))}
          </Box>
        ))}
      </Box>
      <Box marginTop={1} flexDirection="column">
        <Text color={themeColors.dim}>
          <Text color={themeColors.success}>█</Text> 0–50%{'  '}
          <Text color={themeColors.warn}>█</Text> 50–80%{'  '}
          <Text color={themeColors.error}>█</Text> 80–100%{'  '}
          <Text color={themeColors.dim}>█</Text> unused
        </Text>
        <Text color={themeColors.muted}>
          {usedTokens.toLocaleString()} / {maxContext.toLocaleString()} tokens ({(usedPct * 100).toFixed(1)}%)
        </Text>
        <Text color={themeColors.dim}>Model: {currentModel}</Text>
        <Text color={themeColors.dim}>Press Esc to go back</Text>
      </Box>
    </Box>
  );
}
