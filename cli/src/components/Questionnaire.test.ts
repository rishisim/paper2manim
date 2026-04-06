import { describe, expect, it } from 'vitest';
import { getQuestionCursor } from './Questionnaire.js';
import type { QuestionDef } from '../lib/types.js';

const QUESTION: QuestionDef = {
  id: 'audience',
  question: 'Target audience:',
  options: ['High school', 'Undergraduate', 'Graduate'],
  default: 'Undergraduate',
};

describe('Questionnaire state helpers', () => {
  it('uses stored cursor when available (back navigation preserves position)', () => {
    const idx = getQuestionCursor(QUESTION, {}, { audience: 2 });
    expect(idx).toBe(2);
  });

  it('falls back to existing answer when no stored cursor exists', () => {
    const idx = getQuestionCursor(QUESTION, { audience: 'Graduate' }, {});
    expect(idx).toBe(2);
  });

  it('falls back to question default when no answer exists', () => {
    const idx = getQuestionCursor(QUESTION, {}, {});
    expect(idx).toBe(1);
  });

  it('falls back to first option when nothing else is set', () => {
    const q: QuestionDef = { ...QUESTION, default: undefined };
    const idx = getQuestionCursor(q, {}, {});
    expect(idx).toBe(0);
  });
});

