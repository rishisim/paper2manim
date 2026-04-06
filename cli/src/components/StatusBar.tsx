import React from 'react';
import { Box, Text } from 'ink';
import { getStageConfig, RESULT_MARKER, type StageName } from '../lib/theme.js';
import { formatDuration, renderProgressBar, renderProgressBarAscii, renderIndeterminateProgressBar } from '../lib/format.js';
import { useAppContext } from '../context/AppContext.js';
import { useClaudeSpinner } from '../hooks/useClaudeSpinner.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';
import type { ActivityGroup, ActivitySeverity, ProgressMode } from '../lib/types.js';

export type ActivityKind = 'tool_call' | 'thinking' | 'status' | 'tool_result' | 'diff';

export interface ActivityLine {
  id: string;
  kind?: ActivityKind;
  type?: ActivityKind;
  text: string;
  detail?: string;
  groupKey?: string;
  count?: number;
  segmentId?: number;
  group?: ActivityGroup;
  severity?: ActivitySeverity;
}

interface StatusBarProps {
  stage: StageName;
  elapsed: number;
  activity: ActivityLine[];
  segmentsCompleted?: number;
  totalSegments?: number;
  progressPct?: number;
  progressMode?: ProgressMode;
  stageProgressPct?: number;
  hintText?: string;
  maxLines?: number;
  verbose?: boolean;
}

const STAGE_OBJECTIVES: Record<StageName, string> = {
  plan: 'Current objective: shape a teachable storyboard.',
  pipeline: 'Current objective: launch and monitor segment workers in parallel.',
  tts: 'Current objective: produce narration audio for each segment.',
  code: 'Current objective: create Manim scenes that match narration.',
  code_retry: 'Current objective: recover failed segments and keep momentum.',
  verify: 'Current objective: check correctness and style consistency.',
  render: 'Current objective: render final quality segment videos.',
  stitch: 'Current objective: align segment media for final assembly.',
  timing: 'Current objective: validate and adjust A/V synchronization.',
  concat: 'Current objective: join segment outputs into one video.',
  subtitles: 'Current objective: generate and embed subtitles cleanly.',
  overlay: 'Current objective: merge final audio track cleanly.',
  done: 'Current objective: complete.',
};

function safeText(value: unknown, fallback = ''): string {
  if (typeof value === 'string') return value;
  if (value === null || value === undefined) return fallback;
  return String(value);
}

export function normalizeActivityKind(line: ActivityLine): ActivityKind {
  return line.kind ?? line.type ?? 'status';
}

function normalizeActivityTextPrefix(text: unknown): string {
  const normalized = safeText(text);
  return normalized.trim().replace(/\s+/g, ' ').toLowerCase().slice(0, 40);
}

function mergeableKey(line: ActivityLine): string {
  const kind = normalizeActivityKind(line);
  return `${kind}:${line.group ?? 'doing'}:${line.groupKey ?? normalizeActivityTextPrefix(line.text)}`;
}

export function collapseActivityLines(lines: ActivityLine[]): ActivityLine[] {
  const collapsed: ActivityLine[] = [];
  for (const line of lines) {
    const text = safeText(line.text, '(no status)');
    const detail = line.detail !== undefined ? safeText(line.detail) : undefined;
    const normalized: ActivityLine = {
      ...line,
      text,
      detail,
      kind: normalizeActivityKind(line),
      count: line.count ?? 1,
      group: line.group ?? inferGroup(text, normalizeActivityKind(line)),
      severity: line.severity ?? inferSeverity(text),
    };
    const last = collapsed[collapsed.length - 1];
    if (last && mergeableKey(last) === mergeableKey(normalized)) {
      last.count = (last.count ?? 1) + (normalized.count ?? 1);
      last.text = normalized.text;
      last.group = normalized.group;
      last.severity = normalized.severity;
      if (normalized.detail) last.detail = normalized.detail;
      continue;
    }
    collapsed.push(normalized);
  }
  return collapsed;
}

export function truncatePreserveTail(text: string | null | undefined, maxWidth: number, indent: number): string {
  const safe = safeText(text);
  const available = maxWidth - indent - 1;
  if (available <= 0 || safe.length <= available) return safe;
  if (available <= 12) return safe.slice(0, available - 1) + '…';
  const head = Math.max(6, Math.floor(available * 0.6));
  const tail = Math.max(4, available - head - 1);
  return `${safe.slice(0, head)}…${safe.slice(-tail)}`;
}

export function getEffectiveActivityMaxLines(termWidth: number, maxLines: number): number {
  return Math.max(3, Math.min(maxLines, termWidth < 90 ? 4 : termWidth < 120 ? 5 : maxLines));
}

export function getStatusBarMaxLines(termWidth: number, maxLines: number, verbose: boolean): number {
  const base = getEffectiveActivityMaxLines(termWidth, maxLines);
  if (!verbose) return base;
  const bonus = termWidth < 100 ? 1 : termWidth < 140 ? 2 : 3;
  return Math.min(maxLines + bonus, base + bonus);
}

export function summarizeToolOutput(output: string, maxLength = 96): string {
  const normalized = safeText(output).replace(/\s+/g, ' ').trim();
  if (!normalized) return '(no output)';
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, Math.max(0, maxLength - 1))}…`;
}

export function getStageProgressBarWidth(termWidth: number): number {
  if (termWidth < 84) return 10;
  if (termWidth < 110) return 14;
  return 20;
}

function inferGroup(text: unknown, kind: ActivityKind): ActivityGroup {
  const raw = safeText(text).toLowerCase();
  if (kind === 'tool_result' || /complete|finished|done|ready|success/.test(raw)) return 'done';
  if (kind === 'diff') return 'doing';
  if (/fix|retry|recover|repair/.test(raw)) return 'fixing';
  if (/verify|check|validate|inspect|test|lint|docs/.test(raw)) return 'checking';
  return 'doing';
}

function inferSeverity(text: unknown): ActivitySeverity {
  const raw = safeText(text).toLowerCase();
  if (/retry|warning|warn|slow/.test(raw)) return 'warning';
  if (/failed|error|crash|fatal/.test(raw)) return 'critical';
  return 'normal';
}

function groupLabel(group: ActivityGroup, compact: boolean): string {
  if (compact) return group[0]?.toUpperCase() ?? 'D';
  return group === 'checking' ? 'Checking' : group === 'fixing' ? 'Fixing' : group === 'done' ? 'Done' : 'Doing';
}

export function getActivityKindLabel(kind: ActivityKind, compact: boolean): string {
  if (compact) {
    return kind === 'tool_call' ? 'T' : kind === 'tool_result' ? 'O' : kind === 'thinking' ? 'R' : kind === 'diff' ? 'Δ' : 'S';
  }
  return kind === 'tool_call' ? 'tool' : kind === 'tool_result' ? 'out' : kind === 'thinking' ? 'think' : kind === 'diff' ? 'diff' : 'status';
}

function buildFailureTransition(lines: ActivityLine[]): string | null {
  const latest = [...lines].reverse().find(line => (line.severity ?? inferSeverity(line.text)) === 'critical');
  if (!latest) return null;
  const group = latest.group ?? inferGroup(latest.text, normalizeActivityKind(latest));
  return group === 'fixing'
    ? 'Failure handling: attempted a repair pass and is preparing another attempt.'
    : 'Failure handling: captured the failure context and queued the next recovery step.';
}

export function StatusBar({
  stage,
  elapsed,
  activity,
  segmentsCompleted,
  totalSegments,
  progressPct = 0,
  progressMode = 'indeterminate',
  stageProgressPct,
  hintText,
  maxLines = 6,
  verbose = false,
}: StatusBarProps) {
  const { themeColors } = useAppContext();
  const stageConfig = getStageConfig(themeColors);
  const config = stageConfig[stage] ?? stageConfig.done;
  const spinnerChar = useClaudeSpinner();
  const termWidth = useTerminalWidth();
  const compact = termWidth < 100;

  const effectiveMaxLines = getStatusBarMaxLines(termWidth, maxLines, verbose);
  const collapsed = collapseActivityLines(activity);
  const visible = collapsed.slice(-effectiveMaxLines);
  const showThroughput = totalSegments !== undefined && totalSegments > 0;
  const safeSegmentsCompleted = Math.max(0, segmentsCompleted ?? 0);
  const runPct = Math.max(0, Math.min(100, progressPct));
  const stagePct = Math.max(0, Math.min(100, stageProgressPct ?? 0));
  const deterministic = progressMode === 'determinate';
  const progressBarWidth = getStageProgressBarWidth(termWidth);
  const frame = Math.floor(elapsed * 8);
  const progressBar = deterministic
    ? (termWidth >= 84 ? renderProgressBar(runPct, progressBarWidth) : renderProgressBarAscii(runPct, progressBarWidth))
    : renderIndeterminateProgressBar(frame, progressBarWidth);
  const failureTransition = buildFailureTransition(visible);

  return (
    <Box flexDirection="column" paddingLeft={1} marginTop={1}>
      <Box>
        <Text color={config.color}>{spinnerChar} </Text>
        <Text bold color={config.color}>{config.label}</Text>
        <Text color={themeColors.muted}>  {formatDuration(elapsed)}</Text>
        {showThroughput && (
          <Text color={themeColors.muted}>
            {'  '}
            {safeSegmentsCompleted}/{totalSegments}
          </Text>
        )}
        <Text color={deterministic ? themeColors.dim : themeColors.warn}>
          {deterministic ? `  progress ${Math.round(runPct)}%` : '  progress estimating...'}
        </Text>
      </Box>

      <Box paddingLeft={2}>
        <Text color={themeColors.dim}>{truncatePreserveTail(STAGE_OBJECTIVES[stage] ?? 'Current objective: processing pipeline updates.', termWidth, 4)}</Text>
      </Box>
      <Box paddingLeft={2}>
        <Text color={deterministic ? themeColors.progressFill : themeColors.warn}>{progressBar}</Text>
        <Text color={themeColors.muted}>
          {' '}
          {deterministic
            ? `${Math.round(runPct)}%${showThroughput ? ` · segments ${safeSegmentsCompleted}/${totalSegments}` : ''}${showThroughput ? ` · stage ${Math.round(stagePct)}%` : ''}`
            : 'estimating...'}
        </Text>
      </Box>
      {hintText && termWidth >= 84 && (
        <Box paddingLeft={2}>
          <Text color={themeColors.dim}>{truncatePreserveTail(hintText, termWidth, 4)}</Text>
        </Box>
      )}

      {visible.map((line) => (
        <ActivityLineRow key={line.id} line={line} termWidth={termWidth} verbose={verbose} />
      ))}

      {failureTransition && (
        <Box paddingLeft={2}>
          <Text color={themeColors.warn}>{truncatePreserveTail(failureTransition, termWidth, 4)}</Text>
        </Box>
      )}
    </Box>
  );
}

function ActivityLineRow({ line, termWidth, verbose }: { line: ActivityLine; termWidth: number; verbose: boolean }) {
  const { themeColors } = useAppContext();
  const kind = normalizeActivityKind(line);
  const compact = termWidth < 100;
  const repeat = (line.count ?? 1) > 1 ? ` x${line.count}` : '';
  const group = line.group ?? inferGroup(line.text, kind);
  const severity = line.severity ?? inferSeverity(line.text);
  const label = groupLabel(group, compact);
  const labelColor = severity === 'critical'
    ? themeColors.error
    : severity === 'warning'
      ? themeColors.warn
      : themeColors.accent;
  const textColor = severity === 'critical' ? themeColors.error : themeColors.dim;

  if (kind === 'thinking') {
    return (
      <Box paddingLeft={2}>
        <Text color={labelColor}>[{label}] </Text>
        <Text color={textColor} italic>
          {truncatePreserveTail(line.text, termWidth, compact ? 8 : 12)}
          {repeat ? <Text color={themeColors.warn}>{repeat}</Text> : null}
        </Text>
      </Box>
    );
  }

  if (kind === 'tool_call') {
    return (
      <Box flexDirection="column">
        <Box paddingLeft={2}>
          <Text color={labelColor}>[{label}] </Text>
          <Text color={themeColors.accent} bold>{RESULT_MARKER} </Text>
          <Text bold color={severity === 'critical' ? themeColors.error : themeColors.text}>
            {truncatePreserveTail(line.text, termWidth, compact ? 10 : 16)}
          </Text>
          {repeat ? <Text color={themeColors.warn}>{repeat}</Text> : null}
        </Box>
        {line.detail && (
          <Box paddingLeft={4}>
            <Text color={textColor}>{truncatePreserveTail(line.detail, termWidth, compact ? 6 : 8)}</Text>
          </Box>
        )}
      </Box>
    );
  }

  if (kind === 'diff') {
    const detailLines = (line.detail ?? '')
      .split('\n')
      .map(s => s.trimEnd())
      .filter(Boolean)
      .slice(0, compact ? 8 : 12);

    return (
      <Box flexDirection="column" paddingLeft={2}>
        <Box>
          <Text color={labelColor}>[{label}] </Text>
          <Text color={themeColors.accent} bold>{RESULT_MARKER} </Text>
          <Text bold color={themeColors.text}>{truncatePreserveTail(line.text, termWidth, compact ? 10 : 16)}</Text>
          {repeat ? <Text color={themeColors.warn}>{repeat}</Text> : null}
        </Box>
        {detailLines.map((dl, idx) => {
          const first = dl[0] ?? '';
          const color = first === '+'
            ? themeColors.success
            : first === '-'
              ? themeColors.error
              : first === '@'
                ? themeColors.accent
                : themeColors.dim;
          return (
            <Box key={`${line.id}-diff-${idx}`} paddingLeft={2}>
              <Text color={color}>{truncatePreserveTail(dl, termWidth, compact ? 8 : 12)}</Text>
            </Box>
          );
        })}
      </Box>
    );
  }

  if (kind === 'tool_result') {
    const detailLines = verbose
      ? (line.detail ?? line.text)
          .split('\n')
          .map(s => s.trimEnd())
          .filter(Boolean)
          .slice(0, compact ? 3 : 5)
      : [];

    return (
      <Box flexDirection="column">
        <Box paddingLeft={4}>
          <Text color={labelColor}>[{label}] </Text>
          <Text color={textColor}>{truncatePreserveTail(line.text, termWidth, compact ? 9 : 14)}</Text>
          {repeat ? <Text color={themeColors.warn}>{repeat}</Text> : null}
        </Box>
        {detailLines.map((detail, idx) => (
          <Box key={`${line.id}-out-${idx}`} paddingLeft={6}>
            <Text color={themeColors.dim}>{truncatePreserveTail(detail, termWidth, compact ? 10 : 16)}</Text>
          </Box>
        ))}
      </Box>
    );
  }

  return (
    <Box paddingLeft={2}>
      <Text color={labelColor}>[{label}] </Text>
      <Text color={textColor}>{truncatePreserveTail(line.text, termWidth, compact ? 9 : 14)}</Text>
      {repeat ? <Text color={themeColors.warn}>{repeat}</Text> : null}
    </Box>
  );
}
