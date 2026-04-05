import React from 'react';
import { Box, Text } from 'ink';
import { RESULT_MARKER } from '../lib/theme.js';
import { useAppContext } from '../context/AppContext.js';

interface ErrorPanelProps {
  message: string;
  detail?: string;
}

/** Extract a user-friendly hint from common error messages. */
function extractHint(msg: string): string | null {
  const lower = msg.toLowerCase();
  if (lower.includes('credit balance') || lower.includes('billing'))
    return 'Visit https://console.anthropic.com/settings/billing to add credits.';
  if (lower.includes('authentication') || lower.includes('invalid api key') || lower.includes('401'))
    return 'Check your ANTHROPIC_API_KEY in .env — it may be expired or invalid.';
  if (lower.includes('rate limit') || lower.includes('429'))
    return 'You are being rate-limited. Wait a moment and try again.';
  if (lower.includes('timeout') || lower.includes('timed out'))
    return 'The API request timed out. Check your internet connection and try again.';
  if (lower.includes('missing api key'))
    return 'Create a .env file in the project root with your API keys.';
  return null;
}

/** Truncate long error detail to max lines, keeping the most useful parts. */
function truncateDetail(detail: string, maxLines: number = 20): { text: string; truncated: boolean } {
  const lines = detail.split('\n');
  if (lines.length <= maxLines) return { text: detail, truncated: false };

  // Keep first 5 lines (context) and last (maxLines - 6) lines (root cause is usually at the bottom)
  const head = lines.slice(0, 5);
  const tail = lines.slice(-(maxLines - 6));
  const omitted = lines.length - head.length - tail.length;
  return {
    text: [...head, `  ... (${omitted} lines omitted)`, ...tail].join('\n'),
    truncated: true,
  };
}

export function ErrorPanel({ message, detail }: ErrorPanelProps) {
  const { themeColors } = useAppContext();
  const hint = extractHint(detail ?? message);
  const trimmed = detail ? truncateDetail(detail) : null;

  return (
    <Box flexDirection="column" paddingLeft={1} marginTop={1}>
      <Text bold color={themeColors.error}>✘ Error</Text>
      <Box paddingLeft={2}>
        <Text color={themeColors.error}>{RESULT_MARKER} {message}</Text>
      </Box>
      {trimmed && (
        <Box paddingLeft={4} flexDirection="column">
          <Text color={themeColors.dim}>{trimmed.text}</Text>
        </Box>
      )}
      {trimmed?.truncated && (
        <Box paddingLeft={4}>
          <Text color={themeColors.dim}>(full traceback in pipeline_summary.txt)</Text>
        </Box>
      )}
      {hint && (
        <Box paddingLeft={2}>
          <Text color={themeColors.dim}>{RESULT_MARKER} {hint}</Text>
        </Box>
      )}
    </Box>
  );
}
