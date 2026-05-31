/**
 * Lightweight Python syntax highlighter for terminal display.
 * Returns an array of {text, colorKey} spans for a single line.
 */

export type ColorKey = 'keyword' | 'string' | 'comment' | 'number' | 'manim' | 'decorator' | 'default';

export interface TokenSpan {
  text: string;
  colorKey: ColorKey;
}

const KEYWORDS = new Set([
  'class', 'def', 'return', 'import', 'from', 'if', 'elif', 'else',
  'for', 'while', 'try', 'except', 'finally', 'with', 'as', 'yield',
  'lambda', 'pass', 'break', 'continue', 'raise', 'in', 'not', 'and',
  'or', 'is', 'None', 'True', 'False', 'self', 'super', 'del',
  'global', 'nonlocal', 'assert', 'async', 'await',
]);

const MANIM_CLASSES = new Set([
  'Scene', 'VGroup', 'HGroup', 'Group', 'Axes', 'NumberPlane', 'ComplexPlane',
  'MathTex', 'Tex', 'Text', 'Title', 'Paragraph', 'MarkupText',
  'Arrow', 'Dot', 'Line', 'DashedLine', 'Circle', 'Square', 'Rectangle',
  'Polygon', 'Arc', 'Annulus', 'Sector', 'Ellipse', 'Triangle',
  'Create', 'Write', 'FadeIn', 'FadeOut', 'Transform', 'ReplacementTransform',
  'MoveToTarget', 'Indicate', 'Wiggle', 'GrowFromCenter', 'GrowArrow',
  'DrawBorderThenFill', 'ShowCreation', 'Uncreate', 'ApplyMethod',
  'AnimationGroup', 'Succession', 'LaggedStart', 'LaggedStartMap',
  'SurroundingRectangle', 'BackgroundRectangle', 'Brace', 'BraceBetweenPoints',
  'NumberLine', 'BarChart', 'Table', 'Matrix', 'DecimalNumber', 'Integer',
  'TracedPath', 'ParametricFunction', 'FunctionGraph',
  'ThreeDScene', 'Surface', 'Sphere', 'Cube', 'Cylinder', 'Cone',
  'UP', 'DOWN', 'LEFT', 'RIGHT', 'ORIGIN', 'UL', 'UR', 'DL', 'DR',
  'PI', 'TAU', 'DEGREES',
  'RED', 'BLUE', 'GREEN', 'YELLOW', 'WHITE', 'BLACK', 'GREY', 'GRAY',
  'ORANGE', 'PURPLE', 'PINK', 'TEAL', 'GOLD', 'MAROON',
  'RED_A', 'RED_B', 'RED_C', 'RED_D', 'RED_E',
  'BLUE_A', 'BLUE_B', 'BLUE_C', 'BLUE_D', 'BLUE_E',
  'GREEN_A', 'GREEN_B', 'GREEN_C', 'GREEN_D', 'GREEN_E',
]);

// Regex pattern that matches tokens in order of priority
// 1. Comments (#...)
// 2. Strings (triple-quoted partial, double/single quoted)
// 3. Decorators (@...)
// 4. Numbers (int, float)
// 5. Identifiers (words)
// 6. Everything else
const TOKEN_RE = /(?:#.*$)|(?:f?"""(?:[^"\\]|\\.)*?(?:"""|$))|(?:f?'''(?:[^'\\]|\\.)*?(?:'''|$))|(?:f?"(?:[^"\\]|\\.)*?")|(?:f?'(?:[^'\\]|\\.)*?')|(?:@\w+)|(?:\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b)|(?:\b[a-zA-Z_]\w*\b)|(?:\S)/g;

export function highlightLine(line: string): TokenSpan[] {
  const spans: TokenSpan[] = [];
  let lastIndex = 0;

  for (const match of line.matchAll(TOKEN_RE)) {
    const token = match[0];
    const index = match.index!;

    // Add any whitespace/gap before this token
    if (index > lastIndex) {
      spans.push({ text: line.slice(lastIndex, index), colorKey: 'default' });
    }

    let colorKey: ColorKey = 'default';

    if (token.startsWith('#')) {
      colorKey = 'comment';
    } else if (token.startsWith('"') || token.startsWith("'") || token.startsWith('f"') || token.startsWith("f'") || token.startsWith('f"""') || token.startsWith("f'''")) {
      colorKey = 'string';
    } else if (token.startsWith('@')) {
      colorKey = 'decorator';
    } else if (/^\d/.test(token)) {
      colorKey = 'number';
    } else if (KEYWORDS.has(token)) {
      colorKey = 'keyword';
    } else if (MANIM_CLASSES.has(token)) {
      colorKey = 'manim';
    }

    spans.push({ text: token, colorKey });
    lastIndex = index + token.length;
  }

  // Add trailing content
  if (lastIndex < line.length) {
    spans.push({ text: line.slice(lastIndex), colorKey: 'default' });
  }

  // If nothing matched, return the whole line
  if (spans.length === 0) {
    spans.push({ text: line, colorKey: 'default' });
  }

  return spans;
}
