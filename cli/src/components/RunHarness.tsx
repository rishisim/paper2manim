import React from 'react';
import { Box, Text } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import { formatDuration } from '../lib/format.js';
import { getStageConfig, type StageName } from '../lib/theme.js';
import { workerLabel } from '../lib/segmentBoard.js';
import type { BoardActivityDot, BoardRowModel, InspectRow, ProgressMode, RunEventRecord, SegmentState, WorkerRole } from '../lib/types.js';
import { RunTimeline } from './RunTimeline.js';

type RunViewMode = 'board' | 'inspect';

interface RunHarnessProps {
  concept: string;
  quality: 'low' | 'medium' | 'high';
  stage: StageName | null;
  elapsed: number;
  runState: 'active' | 'complete' | 'error';
  segments: Map<number, SegmentState>;
  segmentCodes: Map<number, string>;
  totalSegments: number;
  progressPct: number;
  progressMode: ProgressMode;
  globalEvents: RunEventRecord[];
  viewMode: RunViewMode;
  boardRows: BoardRowModel[];
  boardSelectedSegmentId?: number;
  boardScrollOffset: number;
  boardWindowRows: number;
  boardExpandedSegmentId?: number;
  boardFollowMode: boolean;
  inspectRows: InspectRow[];
  inspectSelectedId?: string;
  inspectScrollOffset: number;
  inspectWindowLines: number;
  inspectExpandedItems: Set<string>;
  inspectFilter: string;
  inspectFollowMode: boolean;
}

const PIPELINE_ORDER: StageName[] = ['plan', 'tts', 'code', 'verify', 'render', 'stitch', 'concat', 'done'];

export function RunHarness({
  concept,
  quality,
  stage,
  elapsed,
  runState,
  segments,
  segmentCodes,
  totalSegments,
  progressPct,
  progressMode,
  globalEvents,
  viewMode,
  boardRows,
  boardSelectedSegmentId,
  boardScrollOffset,
  boardWindowRows,
  boardExpandedSegmentId,
  boardFollowMode,
  inspectRows,
  inspectSelectedId,
  inspectScrollOffset,
  inspectWindowLines,
  inspectExpandedItems,
  inspectFilter,
  inspectFollowMode,
}: RunHarnessProps) {
  const { themeColors } = useAppContext();
  const stageConfig = getStageConfig(themeColors);
  const orderedSegments = [...segments.values()].sort((a, b) => a.id - b.id);
  const workingCount = orderedSegments.filter(seg => !seg.done && !seg.failed).length;
  const warningCount = orderedSegments.filter(seg => !!seg.latestWarning).length;
  const doneCount = orderedSegments.filter(seg => seg.done).length;
  const stageLabel = stage ? (stageConfig[stage] ?? stageConfig.plan).label : 'Starting';
  const globalRail = dedupeGlobalEvents(globalEvents).slice(-4);
  const compactBoard = boardWindowRows < 10;
  const inlineDrawer = boardWindowRows < 12;

  return (
    <Box flexDirection="column" paddingLeft={1} marginTop={1}>
      <Box flexDirection="column">
        <Text bold color={themeColors.primary}>{concept || 'Untitled run'}</Text>
        <Text color={themeColors.muted}>
          {stageLabel}
          <Text color={themeColors.dim}>  ·  </Text>
          {formatDuration(elapsed)}
          <Text color={themeColors.dim}>  ·  </Text>
          quality {quality}
          <Text color={themeColors.dim}>  ·  </Text>
          {totalSegments || orderedSegments.length} segments
          <Text color={themeColors.dim}>  ·  </Text>
          <Text color={themeColors.primary}>{workingCount} active</Text>
          <Text color={themeColors.dim}>  </Text>
          <Text color={themeColors.warn}>{warningCount} warn</Text>
          <Text color={themeColors.dim}>  </Text>
          <Text color={themeColors.success}>{doneCount} done</Text>
          <Text color={themeColors.dim}>  ·  </Text>
          {progressMode === 'determinate' ? `${Math.round(progressPct)}%` : 'estimating'}
          <Text color={themeColors.dim}>  ·  </Text>
          {viewMode}
        </Text>
      </Box>

      <PipelineStageStrip currentStage={stage} runState={runState} />

      {viewMode === 'inspect' ? (
        <RunTimeline
          rows={inspectRows}
          selectedId={inspectSelectedId}
          scrollOffset={inspectScrollOffset}
          windowLines={inspectWindowLines}
          expandedItems={inspectExpandedItems}
          filter={inspectFilter}
          followMode={inspectFollowMode}
          compact={inspectWindowLines < 10}
        />
      ) : (
        <Box flexDirection="column" marginTop={1}>
          <BoardHeader
            rows={boardRows}
            selectedSegmentId={boardSelectedSegmentId}
            followMode={boardFollowMode}
            globalRail={globalRail}
          />
          {boardRows.length === 0 ? (
            <Text color={themeColors.dim}>Waiting for storyboard segments to become ready...</Text>
          ) : (
            <BoardList
              rows={boardRows}
              selectedSegmentId={boardSelectedSegmentId}
              scrollOffset={boardScrollOffset}
              windowRows={boardWindowRows}
              expandedSegmentId={boardExpandedSegmentId}
              compact={compactBoard}
              inlineDrawer={inlineDrawer}
            />
          )}
        </Box>
      )}
    </Box>
  );
}

function BoardHeader({
  rows,
  selectedSegmentId,
  followMode,
  globalRail,
}: {
  rows: BoardRowModel[];
  selectedSegmentId?: number;
  followMode: boolean;
  globalRail: RunEventRecord[];
}) {
  const { themeColors } = useAppContext();
  if (rows.length === 0) return null;
  const activeCount = rows.filter(row => row.state === 'live').length;
  const warnCount = rows.filter(row => row.state === 'warning' || row.state === 'failed').length;
  const latestGlobal = globalRail[globalRail.length - 1]?.message;
  return (
    <Box flexDirection="column" marginTop={1} marginBottom={1}>
      <Text color={themeColors.dim}>
        <Text color={themeColors.primary}>board</Text>
        <Text color={themeColors.dim}>  ·  </Text>
        {followMode ? 'follow' : 'inspect'}
        <Text color={themeColors.dim}>  ·  </Text>
        {activeCount} active
        <Text color={themeColors.dim}>  ·  </Text>
        {warnCount} warn
        {latestGlobal ? (
          <>
            <Text color={themeColors.dim}>  ·  </Text>
            {truncate(latestGlobal, 56)}
          </>
        ) : null}
      </Text>
      <Box>
        {rows.map(row => (
          <Text
            key={`matrix-${row.segmentId}`}
            color={matrixColor(row.statusPipState, row.segmentId === selectedSegmentId, themeColors)}
          >
            {row.segmentId === selectedSegmentId ? '◉ ' : '● '}
          </Text>
        ))}
      </Box>
    </Box>
  );
}

function BoardList({
  rows,
  selectedSegmentId,
  scrollOffset,
  windowRows,
  expandedSegmentId,
  compact,
  inlineDrawer,
}: {
  rows: BoardRowModel[];
  selectedSegmentId?: number;
  scrollOffset: number;
  windowRows: number;
  expandedSegmentId?: number;
  compact: boolean;
  inlineDrawer: boolean;
}) {
  const { themeColors } = useAppContext();
  const start = Math.max(0, Math.min(scrollOffset, Math.max(0, rows.length - windowRows)));
  const end = Math.min(rows.length, start + windowRows);
  const visible = rows.slice(start, end);
  const selectedExpanded = !inlineDrawer && expandedSegmentId !== undefined
    ? rows.find(row => row.segmentId === expandedSegmentId && row.segmentId === selectedSegmentId)
    : undefined;
  return (
    <Box flexDirection="column" marginTop={1}>
      {start > 0 ? <Text color={themeColors.dim}>↑ {start} more</Text> : null}
      {visible.map(row => (
        <BoardRow
          key={`board-row-${row.segmentId}`}
          row={row}
          selected={row.segmentId === selectedSegmentId}
          expanded={inlineDrawer && row.segmentId === expandedSegmentId}
          compact={compact}
        />
      ))}
      {end < rows.length ? <Text color={themeColors.dim}>↓ {rows.length - end} more</Text> : null}
      {selectedExpanded ? <BoardDrawer row={selectedExpanded} compact={compact} /> : null}
    </Box>
  );
}

function BoardRow({
  row,
  selected,
  expanded,
  compact,
}: {
  row: BoardRowModel;
  selected: boolean;
  expanded: boolean;
  compact: boolean;
}) {
  const { themeColors } = useAppContext();
  const badgeColor = matrixColor(row.statusPipState, selected, themeColors);
  return (
    <Box flexDirection="column">
      <Text color={selected ? themeColors.text : themeColors.muted} bold={selected}>
        {selected ? '›' : ' '} <Text color={badgeColor}>{selected ? '◉' : stateGlyph(row.statusPipState)}</Text>{' '}
        {truncate(row.primarySummary, compact ? 68 : 96)}
        {row.updatedAgo ? <Text color={themeColors.dim}> · {row.updatedAgo}</Text> : null}
      </Text>
      <Text color={themeColors.dim}>
        {'  '}
        {renderActivityDots(row.activityDots, selected, themeColors)}
        {row.secondarySummary ? (
          <>
            <Text color={themeColors.dim}> </Text>
            {truncate(row.secondarySummary, compact ? 76 : 112)}
          </>
        ) : null}
      </Text>
      {selected && expanded ? <BoardDrawer row={row} compact={compact} inline /> : null}
    </Box>
  );
}

function BoardDrawer({
  row,
  compact,
  inline = false,
}: {
  row: BoardRowModel;
  compact: boolean;
  inline?: boolean;
}) {
  const { themeColors } = useAppContext();
  const codePreview = (row.selectedCodePreview ?? row.codePreview ?? []).slice(0, compact ? 3 : 5);
  return (
    <Box flexDirection="column" paddingLeft={inline ? 2 : 1} marginTop={inline ? 0 : 1}>
      {row.selectedReasoningPreview || row.reasoningPreview ? (
        <Text color={themeColors.text}>
          <Text color={themeColors.primary}>{row.reasoningLabel ?? 'Status'}</Text>
          <Text color={themeColors.dim}>  </Text>
          {truncate(row.selectedReasoningPreview ?? row.reasoningPreview ?? '', compact ? 110 : 180)}
        </Text>
      ) : (
        <Text color={themeColors.dim}>No live reasoning yet.</Text>
      )}
      {codePreview.length > 0 ? (
        codePreview.map((line, idx) => (
          <Text key={`drawer-code-${row.segmentId}-${idx}`} color={themeColors.dim}>
            <Text color={themeColors.primary}>│</Text> {truncate(line, compact ? 80 : 112)}
          </Text>
        ))
      ) : (
        <Text color={themeColors.dim}>No live code yet.</Text>
      )}
      {row.selectedToolPreview || row.toolPreview ? (
        <Text color={themeColors.muted}>
          <Text color={themeColors.primary}>tool</Text>
          <Text color={themeColors.dim}>  </Text>
          {truncate(row.selectedToolPreview ?? row.toolPreview ?? '', compact ? 92 : 140)}
        </Text>
      ) : null}
    </Box>
  );
}

function PipelineStageStrip({
  currentStage,
  runState,
}: {
  currentStage: StageName | null;
  runState: 'active' | 'complete' | 'error';
}) {
  const { themeColors } = useAppContext();
  const activeIndex = normalizedStageIndex(currentStage);

  return (
    <Box marginTop={1}>
      {PIPELINE_ORDER.map((stage, index) => {
        const isComplete = runState === 'complete' ? true : activeIndex > index;
        const isActive = runState === 'active' && activeIndex === index;
        const color = isComplete ? themeColors.success : isActive ? themeColors.primary : themeColors.dim;
        const marker = isComplete ? '●' : isActive ? '◉' : '○';
        return (
          <Text key={stage} color={color}>
            {index > 0 ? ' -> ' : ''}
            {marker} {stageLabel(stage)}
          </Text>
        );
      })}
    </Box>
  );
}

function SegmentCard({
  segment,
  code,
  expanded,
}: {
  segment: SegmentState;
  code?: string;
  expanded: boolean;
}) {
  const { themeColors } = useAppContext();
  const statusColor = segment.failed
    ? themeColors.error
    : segment.done
      ? themeColors.success
      : segment.latestWarning
        ? themeColors.warn
        : themeColors.primary;
  const title = segment.title ? `: ${segment.title}` : '';
  const workerRoles = segment.workerRoles ?? (segment.currentWorker ? [segment.currentWorker] : []);
  const trace = segment.trace ?? [];
  const visibleTrace = expanded ? trace.slice(-10) : trace.slice(-5);
  const codePreview = code ? buildRawCodePreview(code, expanded ? 18 : 8, !segment.done && !segment.failed) : [];
  const latestRole = segment.currentWorker ? workerLabel(segment.currentWorker) : 'Worker';
  const workerSummary = summarizeWorkers(workerRoles, segment.workerStates ?? {});
  const cardBorder = segment.failed
    ? themeColors.error
    : segment.latestWarning
      ? themeColors.warn
      : statusColor;

  return (
    <Box
      flexDirection="column"
      marginTop={1}
      borderStyle="round"
      borderColor={cardBorder}
      paddingX={1}
      paddingY={0}
    >
      <Box justifyContent="space-between">
        <Text bold color={statusColor}>Segment {segment.id}<Text color={themeColors.text}>{title}</Text></Text>
        <Text color={themeColors.dim}>{segment.done ? 'done' : segment.failed ? 'failed' : 'live'}</Text>
      </Box>
      <Text color={themeColors.text}>
        {latestRole}: {segment.currentTask ?? segment.prettyPhase}
        {segment.updatedAt ? `  ·  ${Math.max(0, Math.round((Date.now() - segment.updatedAt) / 1000))}s ago` : ''}
      </Text>
      <Text color={themeColors.muted}>{workerSummary}</Text>
      {segment.completedBadges && segment.completedBadges.length > 0 ? (
        <Text color={themeColors.dim}>badges: {segment.completedBadges.slice(-4).join('  ·  ')}</Text>
      ) : null}
      {segment.latestWarning ? (
        <Text color={themeColors.warn}>warning: {segment.latestWarning}</Text>
      ) : null}

      <ConsoleSection title="Current Action" color={themeColors.accent}>
        <Text color={themeColors.text}>{segment.currentTask ?? segment.prettyPhase}</Text>
        {segment.lastStatus ? <Text color={themeColors.dim}>{segment.lastStatus}</Text> : null}
      </ConsoleSection>

      {(segment.lastToolCall || segment.lastToolResult) ? (
        <ConsoleSection title="Latest Tool" color={themeColors.primary}>
          {segment.lastToolCall ? (
            <Text color={themeColors.text}>
              call: {segment.lastToolCall.name}
            </Text>
          ) : null}
          {segment.lastToolResult ? (
            <Text color={themeColors.dim}>
              result: {renderSingleLineBlock(segment.lastToolResult.output, expanded ? 220 : 140)}
            </Text>
          ) : null}
        </ConsoleSection>
      ) : null}

      {segment.liveThinking ? (
        <ConsoleSection title="Latest Reasoning" color={themeColors.accent}>
          <Text color={themeColors.accent}>
            {segment.latestReasoningKind === 'raw_reasoning' ? 'Reasoning (model)' : 'Inference (UI summary)'}
          </Text>
          <Text color={themeColors.text}>
            {renderSingleLineBlock(segment.liveThinking, expanded ? 220 : 140)}
          </Text>
        </ConsoleSection>
      ) : null}

      <ConsoleSection title="Recent Events" color={statusColor}>
        {visibleTrace.length > 0 ? (
          visibleTrace.map(entry => (
            <Text key={entry.id} color={traceColor(entry.category, themeColors)}>
              {tracePrefix(entry.category)} {entry.workerRole ? `${workerLabel(entry.workerRole)} ` : ''}{entry.text}
            </Text>
          ))
        ) : (
          <Text color={themeColors.dim}>· waiting for segment activity</Text>
        )}
        {!expanded && trace.length > visibleTrace.length ? (
          <Text color={themeColors.dim}>· +{trace.length - visibleTrace.length} more recent events retained</Text>
        ) : null}
      </ConsoleSection>

      {codePreview.length > 0 ? (
        <ConsoleSection title="Live Code" color={themeColors.primary}>
          {segment.latestCodeSummary ? <SectionLine label="summary" text={segment.latestCodeSummary} color={themeColors.primary} /> : null}
          {codePreview.map((line, index) => (
            <Text key={`${segment.id}-code-${index}`} color={themeColors.text}>
              <Text color={line.number >= 0 ? themeColors.dim : themeColors.primary}>
                {line.number >= 0 ? String(line.number).padStart(3, ' ') : '  >'}
              </Text>
              <Text color={themeColors.dim}> │ </Text>
              {line.text}
            </Text>
          ))}
        </ConsoleSection>
      ) : null}
    </Box>
  );
}

function SectionLine({ label, text, color }: { label: string; text: string; color: string }) {
  return (
    <Text color={color}>
      {label}: {text}
    </Text>
  );
}

function badgeColor(state: string | undefined, themeColors: ReturnType<typeof useAppContext>['themeColors']): string {
  if (state === 'failed') return themeColors.error;
  if (state === 'done') return themeColors.success;
  if (state === 'warning') return themeColors.warn;
  return themeColors.primary;
}

function traceColor(category: string, themeColors: ReturnType<typeof useAppContext>['themeColors']): string {
  if (category === 'warning') return themeColors.warn;
  if (category === 'code') return themeColors.primary;
  if (category === 'completion') return themeColors.success;
  return themeColors.dim;
}

function buildRawCodePreview(
  code: string,
  maxLines: number,
  showCursor: boolean,
): Array<{ number: number; text: string }> {
  const lines = code.split('\n').map(line => line.replace(/\t/g, '    '));
  const start = Math.max(0, lines.length - maxLines);
  const visible = lines.slice(start).map((text, index) => ({ number: start + index + 1, text }));
  if (showCursor) {
    const last = visible[visible.length - 1];
    if (last) {
      visible[visible.length - 1] = { ...last, text: `${last.text}${last.text.endsWith(' ') ? '█' : ' █'}` };
    } else {
      visible.push({ number: -1, text: '█' });
    }
  }
  return visible;
}

function stageLabel(stage: StageName): string {
  if (stage === 'tts') return 'TTS';
  if (stage === 'done') return 'Finalize';
  return stage.charAt(0).toUpperCase() + stage.slice(1);
}

function normalizedStageIndex(stage: StageName | null): number {
  if (!stage) return -1;
  if (stage === 'pipeline') return 2;
  if (stage === 'code_retry' || stage === 'verify') return 3;
  if (stage === 'timing' || stage === 'subtitles' || stage === 'overlay') return 5;
  return PIPELINE_ORDER.indexOf(stage);
}

function dedupeGlobalEvents(events: RunEventRecord[]): RunEventRecord[] {
  const deduped: RunEventRecord[] = [];
  for (const event of events) {
    const last = deduped[deduped.length - 1];
    if (last && last.message === event.message) continue;
    deduped.push(event);
  }
  return deduped;
}

function summarizeWorkers(
  roles: WorkerRole[],
  states: Partial<Record<WorkerRole, string>>,
): string {
  if (roles.length === 0) return 'no active workers';
  return roles.map(role => `${workerLabel(role)} ${states[role] ?? 'working'}`).join('  ·  ');
}

function tracePrefix(category: string): string {
  if (category === 'inference') return '[think]';
  if (category === 'code') return '[code] ';
  if (category === 'warning') return '[warn] ';
  if (category === 'completion') return '[done] ';
  if (category === 'check') return '[check]';
  return '[log]  ';
}

function ConsoleSection({
  title,
  color,
  children,
}: {
  title: string;
  color: string;
  children: React.ReactNode;
}) {
  return (
    <Box flexDirection="column" marginTop={1} borderStyle="single" borderColor={color} paddingX={1}>
      <Text bold color={color}>{title}</Text>
      {children}
    </Box>
  );
}

function renderSingleLineBlock(text: string, maxLength: number): string {
  const compact = text.replace(/\s+/g, ' ').trim();
  if (compact.length <= maxLength) return compact;
  return `${compact.slice(0, maxLength - 1)}…`;
}

function stateGlyph(state: BoardRowModel['state']): string {
  if (state === 'done') return '●';
  if (state === 'failed') return '◌';
  if (state === 'warning') return '◐';
  if (state === 'queued') return '○';
  return '●';
}

function matrixColor(
  state: BoardRowModel['state'],
  selected: boolean,
  themeColors: ReturnType<typeof useAppContext>['themeColors'],
): string {
  if (selected) return themeColors.text;
  if (state === 'failed') return themeColors.error;
  if (state === 'done') return themeColors.success;
  if (state === 'warning') return themeColors.warn;
  if (state === 'queued') return themeColors.dim;
  return themeColors.primary;
}

function dotString(dots: BoardActivityDot[]): string {
  if (dots.length === 0) return '···';
  return dots.slice(0, 5).map(() => '●').join('');
}

function renderActivityDots(
  dots: BoardActivityDot[],
  selected: boolean,
  themeColors: ReturnType<typeof useAppContext>['themeColors'],
): React.ReactNode {
  return (
    <>
      {dots.length === 0 ? (
        <Text color={themeColors.dim}>{dotString(dots)}</Text>
      ) : (
        dots.slice(0, 5).map((dot, idx) => (
          <Text key={`${dot}-${idx}`} color={activityDotColor(dot, selected, themeColors)}>
            ●
          </Text>
        ))
      )}
    </>
  );
}

function activityDotColor(
  dot: BoardActivityDot,
  selected: boolean,
  themeColors: ReturnType<typeof useAppContext>['themeColors'],
): string {
  if (dot === 'warning') return themeColors.warn;
  if (dot === 'done') return themeColors.success;
  if (dot === 'reasoning') return selected ? themeColors.primary : themeColors.muted;
  if (dot === 'code') return selected ? themeColors.primary : themeColors.dim;
  if (dot === 'tool') return selected ? themeColors.text : themeColors.muted;
  return themeColors.dim;
}

function truncate(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return `${text.slice(0, Math.max(0, maxLength - 1))}…`;
}
