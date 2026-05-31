import React, { useEffect, useMemo, useState } from 'react';
import { Box, Text, useInput } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import {
  buildReviewItems,
  getQuestionAnswerLabel,
  getQuestionCursor,
  getQuestionOptions,
  getQuestionStage,
  getVisibleQuestions,
  pruneHiddenAnswers,
  withResolvedDefaults,
} from '../lib/questionnaire.js';
import type { PreferencesSummaryItem, QuestionDef, QuestionnaireStage } from '../lib/types.js';

interface QuestionnaireProps {
  concept: string;
  questions: QuestionDef[];
  onComplete: (answers: Record<string, string>) => void;
  onCancel?: () => void;
}

const STAGES: Array<{ id: QuestionnaireStage | 'review'; label: string; description: string }> = [
  {
    id: 'goal',
    label: 'Goal shaping',
    description: 'Set audience, teaching angle, and the overall depth of the video.',
  },
  {
    id: 'refine',
    label: 'Preference refinement',
    description: 'Tune production tradeoffs only where they materially improve the result.',
  },
  {
    id: 'review',
    label: 'Review',
    description: 'Check the generated profile, edit anything you want, then start rendering.',
  },
];

function shallowEqualAnswers(a: Record<string, string>, b: Record<string, string>): boolean {
  const aKeys = Object.keys(a);
  const bKeys = Object.keys(b);
  if (aKeys.length !== bKeys.length) return false;
  return aKeys.every(key => a[key] === b[key]);
}

function getStageIndex(stage: QuestionnaireStage | 'review'): number {
  return STAGES.findIndex(entry => entry.id === stage);
}

function getNextQuestion(currentId: string, questions: QuestionDef[]): QuestionDef | null {
  const idx = questions.findIndex(question => question.id === currentId);
  if (idx < 0) return questions[0] ?? null;
  return questions[idx + 1] ?? null;
}

function getPrevQuestion(currentId: string, questions: QuestionDef[]): QuestionDef | null {
  const idx = questions.findIndex(question => question.id === currentId);
  if (idx <= 0) return null;
  return questions[idx - 1] ?? null;
}

function getReviewCursorForQuestion(reviewItems: PreferencesSummaryItem[], questionId: string): number {
  const idx = reviewItems.findIndex(item => item.id === questionId);
  return idx >= 0 ? idx : 0;
}

export function Questionnaire({ concept, questions, onComplete, onCancel }: QuestionnaireProps) {
  const { themeColors } = useAppContext();
  const [answers, setAnswers] = useState<Record<string, string>>(() => withResolvedDefaults(questions));
  const [cursorByQuestion, setCursorByQuestion] = useState<Record<string, number>>({});
  const [activeQuestionId, setActiveQuestionId] = useState<string | null>(questions[0]?.id ?? null);
  const [reviewMode, setReviewMode] = useState(false);
  const [returnToReview, setReturnToReview] = useState(false);
  const [reviewCursor, setReviewCursor] = useState(0);

  useEffect(() => {
    const resolved = withResolvedDefaults(questions, answers);
    if (!shallowEqualAnswers(resolved, answers)) {
      setAnswers(resolved);
    }
  }, [answers, questions]);

  const visibleQuestions = useMemo(
    () => getVisibleQuestions(questions, answers),
    [questions, answers],
  );
  const reviewItems = useMemo(
    () => buildReviewItems(questions, answers),
    [questions, answers],
  );

  useEffect(() => {
    if (reviewMode) return;
    if (visibleQuestions.length === 0) {
      setActiveQuestionId(null);
      return;
    }
    if (!activeQuestionId || !visibleQuestions.some(question => question.id === activeQuestionId)) {
      setActiveQuestionId(visibleQuestions[0]?.id ?? null);
    }
  }, [activeQuestionId, reviewMode, visibleQuestions]);

  useEffect(() => {
    if (!reviewMode) return;
    const maxCursor = reviewItems.length + 1;
    if (reviewCursor > maxCursor) {
      setReviewCursor(maxCursor);
    }
  }, [reviewCursor, reviewItems.length, reviewMode]);

  if (questions.length === 0) return null;

  const current = visibleQuestions.find(question => question.id === activeQuestionId) ?? visibleQuestions[0] ?? null;
  const currentOptions = current ? getQuestionOptions(current) : [];
  const cursor = current ? getQuestionCursor(current, answers, cursorByQuestion) : 0;
  const currentStage = reviewMode ? 'review' : (current ? getQuestionStage(current) : 'goal');
  const currentStageMeta = STAGES[getStageIndex(currentStage)] ?? STAGES[0]!;
  const currentStageIdx = getStageIndex(currentStage) + 1;
  const reviewEntryCount = reviewItems.length + 2;

  const setCursorForCurrent = (next: number) => {
    if (!current) return;
    const bounded = Math.max(0, Math.min(currentOptions.length - 1, next));
    setCursorByQuestion(prev => ({ ...prev, [current.id]: bounded }));
  };

  const applyAnswer = (questionId: string, value: string) => {
    const nextAnswers = pruneHiddenAnswers(
      questions,
      withResolvedDefaults(questions, { ...answers, [questionId]: value }),
    );
    setAnswers(nextAnswers);
    return nextAnswers;
  };

  const moveToReview = (questionId?: string) => {
    if (questionId) {
      setReviewCursor(getReviewCursorForQuestion(reviewItems, questionId));
    }
    setReviewMode(true);
    setReturnToReview(false);
  };

  const handleSelect = (value: string) => {
    if (!current) return;
    const selectedIdx = currentOptions.findIndex(opt => opt.value === value);
    if (selectedIdx >= 0) {
      setCursorByQuestion(prev => ({ ...prev, [current.id]: selectedIdx }));
    }

    applyAnswer(current.id, value);

    if (returnToReview) {
      moveToReview(current.id);
      return;
    }

    const nextQuestion = getNextQuestion(current.id, visibleQuestions);
    if (nextQuestion) {
      setActiveQuestionId(nextQuestion.id);
    } else {
      moveToReview();
    }
  };

  const enterReviewEdit = (questionId: string) => {
    setActiveQuestionId(questionId);
    setReturnToReview(true);
    setReviewMode(false);
  };

  useInput((input, key) => {
    if (reviewMode) {
      if (key.upArrow) {
        setReviewCursor(prev => (prev > 0 ? prev - 1 : reviewEntryCount - 1));
        return;
      }
      if (key.downArrow || key.tab) {
        setReviewCursor(prev => (prev + 1) % reviewEntryCount);
        return;
      }
      if (key.return) {
        if (reviewCursor < reviewItems.length) {
          enterReviewEdit(reviewItems[reviewCursor]!.id);
          return;
        }
        if (reviewCursor === reviewItems.length) {
          onComplete(pruneHiddenAnswers(questions, answers));
          return;
        }
        const lastQuestion = visibleQuestions[visibleQuestions.length - 1];
        if (lastQuestion) {
          setActiveQuestionId(lastQuestion.id);
          setReturnToReview(false);
          setReviewMode(false);
        }
        return;
      }
      if (key.escape && onCancel) {
        onCancel();
      }
      return;
    }

    if (!current || currentOptions.length === 0) return;
    const isLeft = key.leftArrow || input === '\u001B[D' || input.toLowerCase() === 'h' || (key.shift && key.tab);
    const isRight = key.rightArrow || input === '\u001B[C' || input.toLowerCase() === 'l' || key.tab;

    if (key.upArrow) {
      setCursorForCurrent(cursor > 0 ? cursor - 1 : currentOptions.length - 1);
      return;
    }
    if (key.downArrow) {
      setCursorForCurrent(cursor < currentOptions.length - 1 ? cursor + 1 : 0);
      return;
    }
    if (isLeft) {
      if (returnToReview) {
        moveToReview(current.id);
        return;
      }
      const prevQuestion = getPrevQuestion(current.id, visibleQuestions);
      if (prevQuestion) {
        setActiveQuestionId(prevQuestion.id);
      }
      return;
    }
    if (isRight) {
      const nextQuestion = getNextQuestion(current.id, visibleQuestions);
      if (nextQuestion) {
        setActiveQuestionId(nextQuestion.id);
      } else {
        moveToReview();
      }
      return;
    }
    if (key.return) {
      handleSelect(currentOptions[cursor]!.value);
      return;
    }
    if (/^[1-9]$/.test(input)) {
      const idx = Number(input) - 1;
      if (idx >= 0 && idx < currentOptions.length) {
        setCursorForCurrent(idx);
        handleSelect(currentOptions[idx]!.value);
      }
      return;
    }
    if (key.escape && onCancel) {
      onCancel();
    }
  });

  return (
    <Box flexDirection="column">
      <Text color={themeColors.separator}>
        {'──────────────────────────────────────────────────────────────────────────────'}
      </Text>
      <Box marginTop={1} flexDirection="column">
        <Text color={themeColors.text} bold>Customize the video before we generate anything</Text>
        <Text color={themeColors.dim}>For: {concept}</Text>
        <Text color={themeColors.muted}>Stage {currentStageIdx} of {STAGES.length}: {currentStageMeta.label}</Text>
        <Text color={themeColors.dim}>{currentStageMeta.description}</Text>
      </Box>

      <Box marginTop={1} flexDirection="column">
        {STAGES.map((stage, index) => {
          const isActive = stage.id === currentStage;
          const isDone = index < getStageIndex(currentStage);
          return (
            <Text key={stage.id} color={isActive ? themeColors.primary : (isDone ? themeColors.accent : themeColors.dim)} bold={isActive}>
              {isDone ? '✓' : isActive ? '→' : '·'} {stage.label}
            </Text>
          );
        })}
      </Box>

      {!reviewMode && current && (
        <Box marginTop={2} flexDirection="column">
          <Text bold color={themeColors.text}>{current.question}</Text>
          {current.helperText && (
            <Text color={themeColors.dim}>{current.helperText}</Text>
          )}
          <Box marginTop={1} flexDirection="column">
            {currentOptions.map((opt, i) => {
              const isSelected = answers[current.id] === opt.value;
              const isCursor = i === cursor;
              return (
                <Box key={opt.value} flexDirection="column" marginBottom={1}>
                  <Text color={isCursor ? themeColors.primary : (isSelected ? themeColors.accent : themeColors.text)} bold={isCursor}>
                    {i + 1}. [{isSelected ? '✓' : ' '}] {opt.label}{opt.recommended ? ' (Recommended)' : ''}
                  </Text>
                  {opt.description && (
                    <Text color={isCursor ? themeColors.muted : themeColors.dim}>
                      {'   '}{opt.description}
                    </Text>
                  )}
                </Box>
              );
            })}
          </Box>
          <Text color={themeColors.muted}>
            Current choice: {getQuestionAnswerLabel(current, answers[current.id])}
          </Text>
          <Text color={themeColors.dim}>
            Enter selects and continues. Left/Right moves between questions. You can review everything before starting.
          </Text>
        </Box>
      )}

      {reviewMode && (
        <Box marginTop={2} flexDirection="column">
          <Text bold color={themeColors.text}>Review your video profile</Text>
          <Text color={themeColors.dim}>Press Enter on any line to edit it, then come right back here.</Text>
          <Box marginTop={1} flexDirection="column">
            {reviewItems.map((item, index) => {
              const isCursor = reviewCursor === index;
              return (
                <Text key={item.id} color={isCursor ? themeColors.primary : themeColors.text} bold={isCursor}>
                  {isCursor ? '→' : ' '} {item.label}: <Text color={isCursor ? themeColors.accent : themeColors.muted}>{item.value}</Text>
                </Text>
              );
            })}
            <Text color={reviewCursor === reviewItems.length ? themeColors.primary : themeColors.accent} bold={reviewCursor === reviewItems.length}>
              {reviewCursor === reviewItems.length ? '→' : ' '} Start generation
            </Text>
            <Text color={reviewCursor === reviewItems.length + 1 ? themeColors.primary : themeColors.dim} bold={reviewCursor === reviewItems.length + 1}>
              {reviewCursor === reviewItems.length + 1 ? '→' : ' '} Back to questions
            </Text>
          </Box>
          <Text color={themeColors.dim}>
            Up/Down moves through the review. Enter edits a field or confirms the run. Esc cancels.
          </Text>
        </Box>
      )}

      <Box marginTop={1}>
        <Text color={themeColors.separator}>
          {'──────────────────────────────────────────────────────────────────────────────'}
        </Text>
      </Box>
    </Box>
  );
}
