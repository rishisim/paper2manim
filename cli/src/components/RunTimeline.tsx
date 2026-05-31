import React from 'react';
import { Box, Text } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import { summarizeToolOutput } from './StatusBar.js';
import type { InspectRow, RunEventRecord } from '../lib/types.js';

const FILTERS = [
  { key: 'all', label: '1A' },
  { key: 'tools', label: '2T' },
  { key: 'reasoning', label: '3R' },
  { key: 'code', label: '4C' },
  { key: 'status', label: '5S' },
] as const;

function eventKindLabel(event: RunEventRecord): string {
  if (event.reasoning?.kind === 'raw_reasoning') return 'reason';
  if (event.reasoning?.kind === 'inferred_reasoning') return 'infer';
  if (event.tool && event.detail) return 'tool-out';
  if (event.tool) return 'tool';
  if (event.channel === 'code') return 'code';
  if (event.kind === 'stage_transition') return 'stage';
  if (event.kind === 'stage_complete') return 'done';
  if (event.kind === 'segment_phase') return 'phase';
  if (event.kind === 'segment_terminal') return 'segment';
  if (event.kind === 'run_marker') return 'run';
  return event.kind;
}

function eventSummary(event: RunEventRecord): string {
  if (event.tool?.output_preview) return `${event.tool.name}: ${event.tool.output_preview}`;
  return event.message;
}

function eventPreview(event: RunEventRecord): string | undefined {
  if (event.detail) return summarizeToolOutput(event.detail, 220);
  if (event.reasoning?.text) return summarizeToolOutput(event.reasoning.text, 220);
  return undefined;
}

function eventBadges(event: RunEventRecord): string[] {
  const badges: string[] = [];
  if (event.segment_id !== undefined) badges.push(`S${event.segment_id}`);
  if (event.worker_role) badges.push(event.worker_role);
  badges.push(eventKindLabel(event));
  if (event.source === 'provider_stream') badges.push('model');
  else if (event.source === 'tool_runtime') badges.push('tool');
  else if (event.source === 'ui_derived') badges.push('derived');
  return badges;
}

function matchesFilter(event: RunEventRecord, filter: string): boolean {
  if (filter === 'all') return true;
  if (filter === 'tools') return !!event.tool;
  if (filter === 'reasoning') return !!event.reasoning;
  if (filter === 'code') return event.channel === 'code';
  if (filter === 'status') return !event.tool && !event.reasoning && event.channel !== 'code';
  return true;
}

export function buildTimelineRows(events: RunEventRecord[], filter = 'all'): InspectRow[] {
  return events
    .filter(event => matchesFilter(event, filter))
    .map(event => ({
      id: `e-${event.run_id}-${event.seq}`,
      event,
      summary: eventSummary(event),
      badges: eventBadges(event),
      preview: eventPreview(event),
      groupKey: event.segment_id !== undefined ? `segment:${event.segment_id}` : event.stage ?? 'global',
      isExpandable: Boolean(event.detail || event.reasoning?.text || event.tool?.params || event.data),
    }));
}

interface RunTimelineProps {
  rows: InspectRow[];
  selectedId?: string;
  scrollOffset: number;
  windowLines: number;
  expandedItems: Set<string>;
  filter: string;
  followMode: boolean;
  compact?: boolean;
}

function detailLinesForRow(row: InspectRow | undefined): string[] {
  if (!row) return ['No event selected.'];
  const lines: string[] = [];
  lines.push(row.summary);
  lines.push(`time: ${row.event.ts}`);
  if (row.event.stage) lines.push(`stage: ${row.event.stage}`);
  if (row.event.segment_id !== undefined) lines.push(`segment: ${row.event.segment_id}`);
  if (row.event.worker_role) lines.push(`worker: ${row.event.worker_role}`);
  if (row.event.source) lines.push(`source: ${row.event.source}`);
  if (row.event.reasoning) lines.push(`reasoning: ${row.event.reasoning.kind}`);
  if (row.event.tool?.params && Object.keys(row.event.tool.params).length > 0) {
    lines.push(`tool params: ${JSON.stringify(row.event.tool.params)}`);
  }
  if (row.event.detail) {
    lines.push('');
    lines.push(...row.event.detail.split('\n').map(part => part.trimEnd()).filter(Boolean));
  } else if (row.event.data && Object.keys(row.event.data).length > 0) {
    lines.push('');
    lines.push(...JSON.stringify(row.event.data, null, 2).split('\n'));
  }
  return lines;
}

export function RunTimeline({
  rows,
  selectedId,
  scrollOffset,
  windowLines,
  expandedItems,
  filter,
  followMode,
  compact = false,
}: RunTimelineProps) {
  const { themeColors } = useAppContext();
  const safeWindowLines = Math.max(5, windowLines);
  const start = Math.max(0, Math.min(scrollOffset, Math.max(0, rows.length - safeWindowLines)));
  const end = Math.min(rows.length, start + safeWindowLines);
  const visible = rows.slice(start, end);
  const selectedRow = rows.find(row => row.id === selectedId) ?? rows[rows.length - 1];
  const inlineDetails = compact || safeWindowLines < 10;

  return (
    <Box flexDirection="column" paddingLeft={1} marginTop={1}>
      <Box>
        <Text bold color={themeColors.primary}>Inspect</Text>
        <Text color={themeColors.dim}>  {followMode ? 'follow' : 'inspect'}</Text>
        <Text color={themeColors.dim}>  ·  </Text>
        {FILTERS.map(item => (
          <Text key={item.key} color={filter === item.key ? themeColors.text : themeColors.dim} bold={filter === item.key}>
            {item.label}{' '}
          </Text>
        ))}
      </Box>
      <Text color={themeColors.dim}>Chronological stream · j/k or arrows · Enter expand · g follow</Text>
      {rows.length === 0 ? <Text color={themeColors.dim}>No events yet.</Text> : null}
      {visible.map((row, idx) => {
        const previous = idx > 0 ? visible[idx - 1] : undefined;
        const selected = row.id === selectedRow?.id;
        const expanded = expandedItems.has(row.id);
        const showDivider = previous && previous.groupKey !== row.groupKey && row.event.segment_id !== undefined;
        return (
          <Box key={row.id} flexDirection="column">
            {showDivider ? <Text color={themeColors.dim}>  seg {row.event.segment_id}</Text> : null}
            <Text color={selected ? themeColors.text : themeColors.dim} bold={selected}>
              {selected ? '›' : ' '} {row.badges.map(badge => `[${badge}]`).join(' ')} {row.summary}
            </Text>
            {expanded && row.preview ? (
              <Text color={themeColors.dim}>
                {selected ? '  ' : '    '}{row.preview}
              </Text>
            ) : null}
            {inlineDetails && selected && !expanded ? (
              <Text color={themeColors.dim}>
                {row.preview ?? row.event.source ?? 'selected'}
              </Text>
            ) : null}
          </Box>
        );
      })}
      {!inlineDetails && selectedRow ? (
        <Box flexDirection="column" marginTop={1}>
          <Text bold color={themeColors.primary}>Detail</Text>
          {detailLinesForRow(selectedRow).slice(0, Math.max(4, safeWindowLines - visible.length - 3)).map((line, idx) => (
            <Text key={`${selectedRow.id}-detail-${idx}`} color={themeColors.text}>{line}</Text>
          ))}
        </Box>
      ) : null}
    </Box>
  );
}
