import { collapseActivityLines, getActivityKindLabel, getStageProgressBarWidth, getStatusBarMaxLines, normalizeActivityKind, truncatePreserveTail, type ActivityLine } from '../components/StatusBar.js';
import { getFooterVisibility } from '../components/FooterStatusLine.js';
import { formatSegmentViewModelForWidth, getSegmentLineViewModel } from '../components/SegmentStatus.js';
import { renderIndeterminateProgressBar, renderProgressBar } from './format.js';
import type { ProgressMode, SegmentState } from './types.js';

export interface SimulatedActivityRow {
  kind: string;
  kindLabel: string;
  text: string;
  count: number;
}

export interface SimulatedRunUi {
  width: number;
  activityMaxLines: number;
  rows: SimulatedActivityRow[];
  progressBar: string;
  progressPct: number;
  progressMode: ProgressMode;
  footer: ReturnType<typeof getFooterVisibility>;
  segments: ReturnType<typeof formatSegmentViewModelForWidth>[];
}

export function simulateRunUi(params: {
  width: number;
  activity: ActivityLine[];
  segments: SegmentState[];
  running?: boolean;
  hasTokens?: boolean;
  hasBranch?: boolean;
  verbose?: boolean;
  maxActivityLines?: number;
  progressPct?: number;
  progressMode?: ProgressMode;
}): SimulatedRunUi {
  const {
    width,
    activity,
    segments,
    running = true,
    hasTokens = true,
    hasBranch = true,
    verbose = false,
    maxActivityLines = 6,
    progressPct = 0,
    progressMode = 'determinate',
  } = params;
  const compact = width < 100;
  const activityMaxLines = getStatusBarMaxLines(width, maxActivityLines, verbose);
  const clampedPct = Math.max(0, Math.min(100, progressPct));
  const progressBar = progressMode === 'determinate'
    ? renderProgressBar(clampedPct, getStageProgressBarWidth(width))
    : renderIndeterminateProgressBar(4, getStageProgressBarWidth(width));
  const rows = collapseActivityLines(activity)
    .slice(-activityMaxLines)
    .map((line) => {
      const kind = normalizeActivityKind(line);
      const kindLabel = getActivityKindLabel(kind, compact);
      const indent = kind === 'tool_call' ? 10 : kind === 'tool_result' ? 9 : 8;
      return {
        kind,
        kindLabel,
        text: truncatePreserveTail(line.text, width, indent),
        count: line.count ?? 1,
      };
    });

  return {
    width,
    activityMaxLines,
    rows,
    progressBar,
    progressPct: clampedPct,
    progressMode,
    footer: getFooterVisibility(width, running, hasTokens, hasBranch, verbose),
    segments: segments.map(seg => formatSegmentViewModelForWidth(getSegmentLineViewModel(seg), width)),
  };
}
