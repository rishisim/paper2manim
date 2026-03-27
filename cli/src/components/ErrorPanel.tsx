import React from 'react';
import { Box, Text } from 'ink';
import { colors } from '../lib/theme.js';

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

export function ErrorPanel({ message, detail }: ErrorPanelProps) {
  const hint = extractHint(detail ?? message);

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={colors.error}
      paddingX={2}
      paddingY={0}
      marginTop={1}
    >
      <Text bold color={colors.error}>✗ Error</Text>
      <Text color={colors.error}>{message}</Text>
      {detail && (
        <Text color={colors.dim}>  {detail}</Text>
      )}
      {hint && (
        <Text color={colors.dim}>  {hint}</Text>
      )}
    </Box>
  );
}
