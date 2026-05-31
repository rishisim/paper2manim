import React from 'react';
import { EventEmitter } from 'node:events';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render } from 'ink-testing-library';
import { AppContextProvider } from '../context/AppContext.js';
import { DEFAULT_SETTINGS, type QuestionDef, type Session } from '../lib/types.js';
import {
  buildReviewItems,
  getQuestionCursor,
  getVisibleQuestions,
  withResolvedDefaults,
} from '../lib/questionnaire.js';
import { Questionnaire } from './Questionnaire.js';

type InputHandler = (input: string, key: Record<string, boolean>) => void;

const inputState = vi.hoisted(() => ({
  latest: null as InputHandler | null,
}));

vi.mock('ink', async () => {
  const actual = await vi.importActual<typeof import('ink')>('ink');
  return {
    ...actual,
    useInput: (handler: InputHandler) => {
      inputState.latest = handler;
    },
  };
});

const QUESTIONS: QuestionDef[] = [
  {
    id: 'audience_profile',
    question: 'Who is this video for?',
    stage: 'goal',
    summaryLabel: 'Audience',
    default: 'undergraduate',
    options: [
      { value: 'high_school', label: 'High school learner' },
      { value: 'undergraduate', label: 'Undergraduate', recommended: true },
    ],
  },
  {
    id: 'lesson_goal',
    question: 'What should the video emphasize?',
    stage: 'goal',
    summaryLabel: 'Teaching focus',
    default: 'intuition',
    options: [
      { value: 'intuition', label: 'Build intuition first', recommended: true },
      { value: 'derivation', label: 'Walk through the derivation' },
    ],
  },
  {
    id: 'narration_feel',
    question: 'What narration style should we use?',
    stage: 'refine',
    summaryLabel: 'Narration',
    default: 'guided',
    showWhen: {
      anyOf: [{ questionId: 'lesson_goal', values: ['intuition'] }],
    },
    options: [
      { value: 'guided', label: 'Guided and intuitive', recommended: true },
      { value: 'compact', label: 'Compact and technical' },
    ],
  },
];

function baseSession(): Session {
  return {
    id: 'test-session',
    name: null,
    startedAt: '2026-04-05T00:00:00Z',
    concept: '',
    stage: null,
    checkpoints: [],
    tokenUsage: { input: 0, output: 0, cacheRead: 0 },
    permissionMode: 'default',
  };
}

async function flush(ms = 20): Promise<void> {
  await new Promise(resolve => setTimeout(resolve, ms));
}

function press(input: string, key: Record<string, boolean> = {}): void {
  if (!inputState.latest) {
    throw new Error('No input handler registered');
  }
  inputState.latest(input, key);
}

(EventEmitter.prototype as EventEmitter & { ref?: () => void; unref?: () => void }).ref ??= () => {};
(EventEmitter.prototype as EventEmitter & { ref?: () => void; unref?: () => void }).unref ??= () => {};

describe('Questionnaire helpers', () => {
  it('uses stored cursor when available', () => {
    const idx = getQuestionCursor(QUESTIONS[0]!, {}, { audience_profile: 1 });
    expect(idx).toBe(1);
  });

  it('resolves defaults and conditional follow-ups', () => {
    const answers = withResolvedDefaults(QUESTIONS);
    expect(getVisibleQuestions(QUESTIONS, answers).map(q => q.id)).toEqual([
      'audience_profile',
      'lesson_goal',
      'narration_feel',
    ]);

    const derivationAnswers = withResolvedDefaults(QUESTIONS, { lesson_goal: 'derivation' });
    expect(getVisibleQuestions(QUESTIONS, derivationAnswers).map(q => q.id)).toEqual([
      'audience_profile',
      'lesson_goal',
    ]);
  });

  it('builds review items from friendly labels', () => {
    const answers = withResolvedDefaults(QUESTIONS);
    const items = buildReviewItems(QUESTIONS, answers);
    expect(items).toEqual([
      { id: 'audience_profile', label: 'Audience', value: 'Undergraduate', stage: 'goal' },
      { id: 'lesson_goal', label: 'Teaching focus', value: 'Build intuition first', stage: 'goal' },
      { id: 'narration_feel', label: 'Narration', value: 'Guided and intuitive', stage: 'refine' },
    ]);
  });
});

describe('Questionnaire UX flow', () => {
  afterEach(() => {
    cleanup();
    inputState.latest = null;
  });

  it('shows staged guidance and reaches review before submit', async () => {
    const onComplete = vi.fn();
    const instance = render(
      <AppContextProvider settings={DEFAULT_SETTINGS} session={baseSession()} gitBranch={null}>
        <Questionnaire concept="Fourier transform" questions={QUESTIONS} onComplete={onComplete} />
      </AppContextProvider>,
    );

    await flush();
    expect(instance.lastFrame() ?? '').toContain('Stage 1 of 3: Goal shaping');
    expect(instance.lastFrame() ?? '').toContain('Undergraduate (Recommended)');

    press('', { rightArrow: true });
    await flush();
    press('', { rightArrow: true });
    await flush();
    press('', { rightArrow: true });
    await flush();

    const frame = instance.lastFrame() ?? '';
    expect(frame).toContain('Review your video profile');
    expect(frame).toContain('Start generation');
    expect(onComplete).not.toHaveBeenCalled();
  });

  it('supports editing from the review screen before confirming', async () => {
    const onComplete = vi.fn();
    const instance = render(
      <AppContextProvider settings={DEFAULT_SETTINGS} session={baseSession()} gitBranch={null}>
        <Questionnaire concept="Fourier transform" questions={QUESTIONS} onComplete={onComplete} />
      </AppContextProvider>,
    );

    await flush();
    press('', { rightArrow: true });
    await flush();
    press('', { rightArrow: true });
    await flush();
    press('', { rightArrow: true });
    await flush();

    press('', { return: true });
    await flush();
    expect(instance.lastFrame() ?? '').toContain('Who is this video for?');

    press('1');
    await flush();
    expect(instance.lastFrame() ?? '').toContain('Review your video profile');
    expect(instance.lastFrame() ?? '').toContain('Audience: High school learner');

    press('', { downArrow: true });
    press('', { downArrow: true });
    press('', { downArrow: true });
    await flush();
    press('', { return: true });
    await flush();

    expect(onComplete).toHaveBeenCalledWith({
      audience_profile: 'high_school',
      lesson_goal: 'intuition',
      narration_feel: 'guided',
    });
  });
});
