import { createHash } from 'node:crypto';

export interface CompactDiff {
  hasChanges: boolean;
  added: number;
  removed: number;
  summary: string;
  lines: string[];
  truncated: boolean;
  dedupeKey: string;
}

type OpType = ' ' | '+' | '-';
interface Op {
  type: OpType;
  line: string;
}

function normalizeForWhitespaceCompare(code: string): string {
  return code
    .split('\n')
    .map(l => l.replace(/\s+$/g, ''))
    .join('\n')
    .trim();
}

function toLines(code: string): string[] {
  if (!code) return [];
  const lines = code.split('\n');
  if (lines.length > 0 && lines[lines.length - 1] === '') lines.pop();
  return lines;
}

function makeDedupeKey(prevCode: string, nextCode: string): string {
  return createHash('sha1').update(prevCode).update('\n::\n').update(nextCode).digest('hex').slice(0, 12);
}

function buildOps(prevLines: string[], nextLines: string[]): Op[] {
  const n = prevLines.length;
  const m = nextLines.length;
  const lcs: number[][] = Array.from({ length: n + 1 }, () => Array<number>(m + 1).fill(0));

  for (let i = 1; i <= n; i += 1) {
    for (let j = 1; j <= m; j += 1) {
      if (prevLines[i - 1] === nextLines[j - 1]) {
        lcs[i]![j] = (lcs[i - 1]![j - 1] ?? 0) + 1;
      } else {
        lcs[i]![j] = Math.max(lcs[i - 1]![j] ?? 0, lcs[i]![j - 1] ?? 0);
      }
    }
  }

  const out: Op[] = [];
  let i = n;
  let j = m;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && prevLines[i - 1] === nextLines[j - 1]) {
      out.push({ type: ' ', line: prevLines[i - 1]! });
      i -= 1;
      j -= 1;
      continue;
    }
    if (j > 0 && (i === 0 || (lcs[i]![j - 1] ?? 0) >= (lcs[i - 1]?.[j] ?? 0))) {
      out.push({ type: '+', line: nextLines[j - 1]! });
      j -= 1;
    } else if (i > 0) {
      out.push({ type: '-', line: prevLines[i - 1]! });
      i -= 1;
    }
  }

  out.reverse();
  return out;
}

function buildHunkRanges(ops: Op[], context: number): Array<{ start: number; end: number }> {
  const changeIdxs: number[] = [];
  for (let i = 0; i < ops.length; i += 1) {
    if (ops[i]?.type !== ' ') changeIdxs.push(i);
  }
  if (changeIdxs.length === 0) return [];

  const ranges: Array<{ start: number; end: number }> = [];
  let start = Math.max(0, changeIdxs[0]! - context);
  let end = Math.min(ops.length - 1, changeIdxs[0]! + context);

  for (let i = 1; i < changeIdxs.length; i += 1) {
    const idx = changeIdxs[i]!;
    const nextStart = Math.max(0, idx - context);
    const nextEnd = Math.min(ops.length - 1, idx + context);
    if (nextStart <= end + 1) {
      end = Math.max(end, nextEnd);
    } else {
      ranges.push({ start, end });
      start = nextStart;
      end = nextEnd;
    }
  }
  ranges.push({ start, end });
  return ranges;
}

function countOldUntil(ops: Op[], idxExclusive: number): number {
  let n = 0;
  for (let i = 0; i < idxExclusive; i += 1) {
    const t = ops[i]?.type;
    if (t === ' ' || t === '-') n += 1;
  }
  return n;
}

function countNewUntil(ops: Op[], idxExclusive: number): number {
  let n = 0;
  for (let i = 0; i < idxExclusive; i += 1) {
    const t = ops[i]?.type;
    if (t === ' ' || t === '+') n += 1;
  }
  return n;
}

export function buildCompactUnifiedDiff(
  prevCode: string,
  nextCode: string,
  opts?: {
    maxVisibleLines?: number;
    contextLines?: number;
  },
): CompactDiff {
  const maxVisible = Math.max(6, opts?.maxVisibleLines ?? 16);
  const context = Math.max(0, opts?.contextLines ?? 1);
  const dedupeKey = makeDedupeKey(prevCode, nextCode);

  if (normalizeForWhitespaceCompare(prevCode) === normalizeForWhitespaceCompare(nextCode)) {
    return {
      hasChanges: false,
      added: 0,
      removed: 0,
      summary: 'No code changes',
      lines: [],
      truncated: false,
      dedupeKey,
    };
  }

  const prevLines = toLines(prevCode);
  const nextLines = toLines(nextCode);
  const ops = buildOps(prevLines, nextLines);

  const added = ops.filter(op => op.type === '+').length;
  const removed = ops.filter(op => op.type === '-').length;

  const hunkRanges = buildHunkRanges(ops, context);
  const rendered: string[] = [];
  for (const range of hunkRanges) {
    const oldStart = countOldUntil(ops, range.start) + 1;
    const newStart = countNewUntil(ops, range.start) + 1;
    const oldCount = ops.slice(range.start, range.end + 1).filter(op => op.type !== '+').length;
    const newCount = ops.slice(range.start, range.end + 1).filter(op => op.type !== '-').length;
    rendered.push(`@@ -${oldStart},${oldCount} +${newStart},${newCount} @@`);
    for (let i = range.start; i <= range.end; i += 1) {
      const op = ops[i]!;
      rendered.push(`${op.type}${op.line}`);
    }
  }

  const truncated = rendered.length > maxVisible;
  const lines = truncated ? rendered.slice(0, maxVisible) : rendered;
  if (truncated) {
    lines.push(`… ${rendered.length - maxVisible} more diff lines`);
  }

  return {
    hasChanges: added > 0 || removed > 0,
    added,
    removed,
    summary: `+${added} -${removed}`,
    lines,
    truncated,
    dedupeKey,
  };
}
