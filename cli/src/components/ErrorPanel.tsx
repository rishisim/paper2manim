import React from 'react';
import { Box, Text } from 'ink';
import { RESULT_MARKER } from '../lib/theme.js';
import { useAppContext } from '../context/AppContext.js';
import type { CompletedStage } from '../lib/types.js';

interface FailedSegment {
  id: number;
  title: string;
  stage: string;
  error: string;
}

interface ErrorPanelProps {
  message: string;
  detail?: string;
  failedSegments?: FailedSegment[];
  numSegments?: number;
  videoPath?: string | null;
  projectDir?: string | null;
  tokenSummary?: {
    estimated_cost_usd: number;
    total_api_calls: number;
  } | null;
  stages?: CompletedStage[];
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

/** Format a stage name for display. */
function stageLabel(stage: string): string {
  switch (stage) {
    case 'code': return 'Code gen';
    case 'stitch': return 'Stitch';
    case 'render': return 'Render';
    case 'tts': return 'TTS';
    default: return stage;
  }
}

export function ErrorPanel({ message, detail, failedSegments, numSegments, videoPath, projectDir, tokenSummary, stages }: ErrorPanelProps) {
  const { themeColors } = useAppContext();
  const hint = extractHint(detail ?? message);
  const trimmed = detail ? truncateDetail(detail) : null;

  const numFailed = failedSegments?.length ?? 0;
  const numSucceeded = (numSegments ?? 0) - numFailed;
  const hasPartialSuccess = numSucceeded > 0 && numFailed > 0;

  // Build stage summary from completed stages
  const stageOk = stages?.filter(s => s.status === 'ok').length ?? 0;
  const stageFail = stages?.filter(s => s.status === 'failed').length ?? 0;

  return (
    <Box flexDirection="column" paddingLeft={1} marginTop={1}>
      <Text bold color={themeColors.error}>✘ Pipeline Failed</Text>
      <Box paddingLeft={2}>
        <Text color={themeColors.error}>{RESULT_MARKER} {message}</Text>
      </Box>

      {/* Stage summary row */}
      {stages && stages.length > 0 && (
        <Box paddingLeft={2} marginTop={1}>
          <Text color={themeColors.dim}>
            Stages: {stageOk} passed, {stageFail} failed
            {tokenSummary ? ` · $${tokenSummary.estimated_cost_usd.toFixed(2)} spent` : ''}
          </Text>
        </Box>
      )}

      {/* Segment breakdown */}
      {numSegments != null && numSegments > 0 && (
        <Box flexDirection="column" paddingLeft={2} marginTop={1}>
          <Text bold color={themeColors.dim}>
            Segments: {hasPartialSuccess
              ? <Text><Text color={themeColors.success}>{numSucceeded} ok</Text> · <Text color={themeColors.error}>{numFailed} failed</Text> / {numSegments}</Text>
              : <Text color={themeColors.error}>{numFailed} failed / {numSegments}</Text>
            }
          </Text>

          {failedSegments && failedSegments.length > 0 && (
            <Box flexDirection="column" paddingLeft={2} marginTop={0}>
              {failedSegments.slice(0, 8).map((seg) => (
                <Box key={seg.id}>
                  <Text color={themeColors.error}>  ✗ </Text>
                  <Text color={themeColors.dim}>
                    Seg {seg.id} ({seg.title}) — {stageLabel(seg.stage)}: {seg.error.split('\n')[0]}
                  </Text>
                </Box>
              ))}
              {failedSegments.length > 8 && (
                <Text color={themeColors.dim}>  ... and {failedSegments.length - 8} more</Text>
              )}
            </Box>
          )}
        </Box>
      )}

      {/* Detail (traceback) */}
      {trimmed && (
        <Box paddingLeft={4} flexDirection="column" marginTop={1}>
          <Text color={themeColors.dim}>{trimmed.text}</Text>
        </Box>
      )}
      {trimmed?.truncated && (
        <Box paddingLeft={4}>
          <Text color={themeColors.dim}>(full traceback in pipeline_summary.txt)</Text>
        </Box>
      )}

      {/* Contextual hint */}
      {hint && (
        <Box paddingLeft={2} marginTop={1}>
          <Text color={themeColors.dim}>{RESULT_MARKER} {hint}</Text>
        </Box>
      )}

      {/* Partial video */}
      {videoPath && (
        <Box paddingLeft={2} marginTop={1}>
          <Text color={themeColors.accent}>{RESULT_MARKER} Partial video saved: {videoPath}</Text>
        </Box>
      )}

      {/* Recovery actions */}
      <Box flexDirection="column" paddingLeft={2} marginTop={1}>
        {projectDir && (
          <Text color={themeColors.dim}>
            {RESULT_MARKER} Run <Text bold>/retry</Text> to retry failed segments (cached stages are reused)
          </Text>
        )}
        {projectDir && (
          <Text color={themeColors.dim}>
            {RESULT_MARKER} Or <Text bold>/resume {projectDir.split('/').pop()}</Text> to resume manually
          </Text>
        )}
      </Box>
    </Box>
  );
}
