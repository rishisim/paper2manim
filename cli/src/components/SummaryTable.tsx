import React from 'react';
import { Box, Text } from 'ink';
import { getStageConfig, RESULT_MARKER } from '../lib/theme.js';
import { formatDuration, formatTokenCount } from '../lib/format.js';
import { useAppContext } from '../context/AppContext.js';
import type { CompletedStage, PipelineUpdate } from '../lib/types.js';

interface SummaryTableProps {
  stages: CompletedStage[];
  toolCallCounts?: Record<string, number>;
  totalToolCalls?: number;
  tokenSummary?: PipelineUpdate['token_summary'];
}

function formatCost(usd: number): string {
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  if (usd < 1) return `$${usd.toFixed(3)}`;
  return `$${usd.toFixed(2)}`;
}

export function SummaryTable({ stages, toolCallCounts, totalToolCalls, tokenSummary }: SummaryTableProps) {
  const { themeColors } = useAppContext();
  const stageConfig = getStageConfig(themeColors);
  const total = stages.reduce((sum, s) => sum + s.elapsed, 0);

  return (
    <Box flexDirection="column" marginTop={1} paddingLeft={1}>
      <Text bold>Pipeline Summary</Text>
      {stages.map((stage, i) => {
        const config = stageConfig[stage.name] ?? stageConfig.done;
        const icon = stage.status === 'ok' ? '✔' : '✘';
        const iconColor = stage.status === 'ok' ? themeColors.success : themeColors.error;
        const dur = formatDuration(stage.elapsed);
        const label = config.label.padEnd(28);

        return (
          <Text key={i}>
            <Text color={iconColor} bold>{icon}</Text>
            <Text> {label}</Text>
            <Text color={themeColors.dim}>{dur}</Text>
          </Text>
        );
      })}
      <Text color={themeColors.separator}>{'─'.repeat(40)}</Text>
      <Box>
        <Text bold>  {'Total'.padEnd(27)}</Text>
        <Text bold>{formatDuration(total)}</Text>
      </Box>

      {totalToolCalls !== undefined && totalToolCalls > 0 && (
        <Box flexDirection="column" marginTop={1}>
          <Text color={themeColors.muted}>{RESULT_MARKER} Tool calls: {totalToolCalls}</Text>
          {toolCallCounts && Object.entries(toolCallCounts).map(([name, count]) => (
            <Text key={name} color={themeColors.dim}>    {name}: {count}</Text>
          ))}
        </Box>
      )}

      {tokenSummary && (tokenSummary.total_input_tokens > 0 || tokenSummary.total_output_tokens > 0) && (
        <Box flexDirection="column" marginTop={1}>
          <Text bold>Token Usage & Estimated Cost</Text>
          <Text color={themeColors.muted}>
            {'  '}Tokens: {formatTokenCount(tokenSummary.total_input_tokens)} in / {formatTokenCount(tokenSummary.total_output_tokens)} out
            {'  '}({tokenSummary.total_api_calls} API calls)
          </Text>
          <Text color={themeColors.muted}>
            {'  '}Estimated cost: <Text color={themeColors.warn}>{formatCost(tokenSummary.estimated_cost_usd)}</Text>
            <Text color={themeColors.dim}> (approximate)</Text>
          </Text>
          {tokenSummary.breakdown && Object.entries(tokenSummary.breakdown).map(([stage, data]) => (
            <Text key={stage} color={themeColors.dim}>
              {'    '}{stage.padEnd(12)} {formatTokenCount(data.input_tokens)} in / {formatTokenCount(data.output_tokens)} out  ~{formatCost(data.cost_usd)}
            </Text>
          ))}
          {tokenSummary.tts_api_calls !== undefined && tokenSummary.tts_api_calls > 0 && (
            <Text color={themeColors.dim}>
              {'    '}{'tts'.padEnd(12)} {tokenSummary.tts_api_calls} Gemini TTS calls
            </Text>
          )}
        </Box>
      )}
    </Box>
  );
}
