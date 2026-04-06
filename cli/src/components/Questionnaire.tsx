import React, { useMemo, useState } from 'react';
import { Box, Text, useInput } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import type { QuestionDef } from '../lib/types.js';

interface QuestionnaireProps {
  concept: string;
  questions: QuestionDef[];
  onComplete: (answers: Record<string, string>) => void;
  onCancel?: () => void;
}

export function getQuestionCursor(
  question: QuestionDef,
  answers: Record<string, string>,
  cursorByQuestion: Record<string, number>,
): number {
  const options = question.options ?? [];
  const answerIdx = options.findIndex(opt => opt === answers[question.id]);
  const storedCursor = cursorByQuestion[question.id];
  if (storedCursor !== undefined) return Math.max(0, Math.min(options.length - 1, storedCursor));
  if (answerIdx >= 0) return answerIdx;
  if (question.default) {
    const defaultIdx = options.findIndex(opt => opt === question.default);
    if (defaultIdx >= 0) return defaultIdx;
  }
  return 0;
}

export function Questionnaire({ concept, questions, onComplete, onCancel }: QuestionnaireProps) {
  const { themeColors } = useAppContext();
  const [currentIdx, setCurrentIdx] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [cursorByQuestion, setCursorByQuestion] = useState<Record<string, number>>({});

  if (questions.length === 0) return null;

  const current = questions[currentIdx]!;
  const currentOptions = current.options ?? [];
  const cursor = getQuestionCursor(current, answers, cursorByQuestion);
  const hasPrev = currentIdx > 0;
  const hasNext = currentIdx < questions.length - 1;
  const canAdvance = !!answers[current.id];

  const setCursorForCurrent = (next: number) => {
    const bounded = Math.max(0, Math.min(currentOptions.length - 1, next));
    setCursorByQuestion(prev => ({ ...prev, [current.id]: bounded }));
  };

  const handleSelect = (value: string) => {
    const newAnswers = { ...answers, [current.id]: value };
    setAnswers(newAnswers);
    const selectedIdx = currentOptions.findIndex(opt => opt === value);
    if (selectedIdx >= 0) {
      setCursorByQuestion(prev => ({ ...prev, [current.id]: selectedIdx }));
    }

    if (currentIdx + 1 < questions.length) {
      setCurrentIdx(currentIdx + 1);
    } else {
      onComplete(newAnswers);
    }
  };

  useInput((input, key) => {
    if (currentOptions.length === 0) return;
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
      if (hasPrev) setCurrentIdx(currentIdx - 1);
      return;
    }
    if (isRight) {
      if (hasNext && canAdvance) setCurrentIdx(currentIdx + 1);
      return;
    }
    if (key.return) {
      handleSelect(currentOptions[cursor]!);
      return;
    }
    if (/^[1-9]$/.test(input)) {
      const idx = Number(input) - 1;
      if (idx >= 0 && idx < currentOptions.length) {
        setCursorForCurrent(idx);
        handleSelect(currentOptions[idx]!);
      }
      return;
    }
    if (key.escape && onCancel) {
      onCancel();
    }
  });

  const completion = useMemo(() => {
    const answered = Object.keys(answers).length;
    return `${answered}/${questions.length} answered`;
  }, [answers, questions.length]);

  return (
    <Box flexDirection="column">
      <Text color={themeColors.separator}>
        {'──────────────────────────────────────────────────────────────────────────────'}
      </Text>
      <Box marginTop={1}>
        <Text color={themeColors.dim}>← </Text>
        <Text backgroundColor={themeColors.accent} color={themeColors.bg} bold>
          {' '}
          {current.question.replace(/:\s*$/, '')}
          {' '}
        </Text>
        <Text color={themeColors.dim}>  ↵ select · ← back · → next</Text>
      </Box>
      <Box marginTop={1}>
        <Text color={themeColors.text} bold>
          Customizing video for:
        </Text>
        <Text color={themeColors.dim}> {concept}</Text>
      </Box>
      <Box marginTop={1}>
        <Text bold color={themeColors.text}>
          {current.question}
        </Text>
      </Box>
      <Box marginTop={1} flexDirection="column">
        {currentOptions.map((opt, i) => {
          const isSelected = answers[current.id] === opt;
          const isCursor = i === cursor;
          return (
            <Text key={opt}>
              {isCursor ? (
                <Text color={themeColors.primary} bold>
                  {i + 1}. [{isSelected ? '✓' : '·'}] {opt}
                </Text>
              ) : (
                <Text color={isSelected ? themeColors.accent : themeColors.dim}>
                  {i + 1}. [{isSelected ? '✓' : ' '}] {opt}
                </Text>
              )}
            </Text>
          );
        })}
      </Box>
      <Box marginTop={1}>
        <Text color={themeColors.accent}>↵ </Text>
        <Text color={themeColors.accent} bold>Submit</Text>
      </Box>
      <Box>
        <Text color={themeColors.separator}>
          {'──────────────────────────────────────────────────────────────────────────────'}
        </Text>
      </Box>
      <Box marginTop={1} flexDirection="column">
        <Text color={themeColors.text}>Question {currentIdx + 1} of {questions.length}</Text>
        <Text color={themeColors.dim}>{completion}</Text>
        <Text color={themeColors.dim}>
          Enter select · 1-9 quick choose · ↑/↓ navigate · ←/→ or Tab/Shift+Tab move · Esc cancel
        </Text>
      </Box>
    </Box>
  );
}
