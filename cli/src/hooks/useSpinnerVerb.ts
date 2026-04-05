import { useState, useEffect, useRef } from 'react';
import type { StageName } from '../lib/theme.js';

/**
 * Whimsical spinner verbs — inspired by Claude Code's playful loading messages.
 * A large pool of fun words that randomly cycle while the pipeline is processing.
 */
const WHIMSICAL_VERBS = [
  'Cogitating', 'Ruminating', 'Pondering', 'Noodling', 'Mulling',
  'Cerebrating', 'Deliberating', 'Contemplating', 'Percolating',
  'Brewing', 'Simmering', 'Marinating', 'Fermenting', 'Crystallizing',
  'Orchestrating', 'Harmonizing', 'Composing', 'Crafting',
  'Flibbertigibbeting', 'Flummoxing', 'Combobulating', 'Recombobulating',
  'Discombobulating', 'Shenaniganing', 'Tomfoolering', 'Boondoggling',
  'Lollygagging', 'Gallivanting', 'Perambulating', 'Meandering',
  'Sketching', 'Computing', 'Processing', 'Synthesizing', 'Forging',
  'Generating', 'Incubating', 'Hatching', 'Sprouting', 'Cultivating',
  'Concocting', 'Manifesting', 'Channeling', 'Choreographing',
  'Calculating', 'Tinkering', 'Wrangling', 'Improvising',
  'Spinning', 'Whirring', 'Churning', 'Crunching',
  'Architecting', 'Envisioning', 'Imagining',
  'Befuddling', 'Doodling', 'Frolicking', 'Grooving',
  'Moonwalking', 'Skedaddling', 'Spelunking', 'Vibing',
  'Perusing', 'Musing', 'Canoodling', 'Finagling',
  'Flourishing', 'Razzmatazzing', 'Prestidigitating',
  'Philosophising', 'Transmuting', 'Metamorphosing',
  'Bloviating', 'Pontificating', 'Gesticulating',
  'Hyperspacing', 'Nebulizing', 'Orbiting', 'Cascading',
  'Perambulating', 'Undulating', 'Unfurling', 'Zigzagging',
  'Pollinating', 'Photosynthesizing', 'Osmosing', 'Germinating',
  'Kneading', 'Whisking', 'Zesting', 'Caramelizing',
  'Garnishing', 'Julienning', 'Seasoning', 'Tempering',
  'Clauding', 'Gitifying', 'Reticulating',
];

/** Stage-specific verbs shown alongside the whimsical ones. */
const STAGE_VERBS: Partial<Record<StageName, string[]>> = {
  plan:        ['Planning storyboard', 'Analyzing concept', 'Structuring narrative', 'Designing flow'],
  tts:         ['Generating voiceover', 'Synthesizing speech', 'Recording narration'],
  code:        ['Writing Manim code', 'Building animations', 'Crafting scenes'],
  code_retry:  ['Retrying segments', 'Self-correcting', 'Fixing errors'],
  verify:      ['Verifying code', 'Checking for visual issues', 'Reviewing transitions'],
  render:      ['Rendering frames', 'Processing video', 'Compositing scenes'],
  timing:      ['Aligning audio/video', 'Syncing tracks', 'Checking timing'],
  concat:      ['Assembling final video', 'Concatenating segments', 'Finalizing'],
  overlay:     ['Overlaying audio', 'Mixing final track', 'Merging media'],
};

const CYCLE_MS = 2500;

/** Deterministic shuffle based on a seed (so each stage gets a consistent order). */
function seededShuffle(arr: string[], seed: number): string[] {
  const result = [...arr];
  let s = seed;
  for (let i = result.length - 1; i > 0; i--) {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    const j = s % (i + 1);
    [result[i], result[j]] = [result[j]!, result[i]!];
  }
  return result;
}

/** Returns a cycling verb string appropriate for the current pipeline stage.
 *  Uses Claude Code-style whimsical verbs mixed with stage-specific ones. */
export function useSpinnerVerb(stage: StageName | null): string {
  const [idx, setIdx] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const verbsRef = useRef<string[]>([]);

  useEffect(() => {
    setIdx(0);
    if (intervalRef.current) clearInterval(intervalRef.current);

    // Build verb list: stage-specific verbs first, then shuffled whimsical pool
    const stageSpecific = stage ? (STAGE_VERBS[stage] ?? []) : [];
    const seed = stage ? stage.charCodeAt(0) * 1000 + (stage.charCodeAt(1) ?? 0) : 0;
    const shuffled = seededShuffle(WHIMSICAL_VERBS, seed);
    verbsRef.current = [...stageSpecific, ...shuffled];

    intervalRef.current = setInterval(() => setIdx(i => i + 1), CYCLE_MS);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [stage]);

  if (!stage) return '';
  const verbs = verbsRef.current;
  if (verbs.length === 0) return '';
  return verbs[idx % verbs.length]! + '...';
}
