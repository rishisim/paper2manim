export const AUTO_VERBOSE_WIDTH = 110;

/**
 * Resolve effective verbose mode with optional manual override.
 * - null override => width-driven auto mode
 * - boolean override => explicit user preference
 */
export function resolveEffectiveVerbose(
  termWidth: number,
  manualOverride: boolean | null,
  autoWidth = AUTO_VERBOSE_WIDTH,
): boolean {
  if (manualOverride !== null) return manualOverride;
  return termWidth >= autoWidth;
}

