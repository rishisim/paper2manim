import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';
import { colors } from '../lib/theme.js';
import type { QuestionDef } from '../lib/types.js';

interface QuestionnaireProps {
  concept: string;
  questions: QuestionDef[];
  onComplete: (answers: Record<string, string>) => void;
}

/** Minimal arrow-key select list — no external dependency. */
function SelectList({ options, onSubmit }: { options: string[]; onSubmit: (value: string) => void }) {
  const [cursor, setCursor] = useState(0);

  useInput((input, key) => {
    if (key.upArrow) {
      setCursor(prev => (prev > 0 ? prev - 1 : options.length - 1));
    } else if (key.downArrow) {
      setCursor(prev => (prev < options.length - 1 ? prev + 1 : 0));
    } else if (key.return) {
      onSubmit(options[cursor]!);
    }
  });

  return (
    <Box flexDirection="column">
      {options.map((opt, i) => (
        <Text key={opt}>
          {i === cursor ? (
            <Text color={colors.primary} bold>{'❯ '}{opt}</Text>
          ) : (
            <Text color={colors.dim}>{'  '}{opt}</Text>
          )}
        </Text>
      ))}
    </Box>
  );
}

export function Questionnaire({ concept, questions, onComplete }: QuestionnaireProps) {
  const [currentIdx, setCurrentIdx] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});

  if (questions.length === 0) return null;

  const current = questions[currentIdx]!;

  const handleSelect = (value: string) => {
    const newAnswers = { ...answers, [current.id]: value };
    setAnswers(newAnswers);

    if (currentIdx + 1 < questions.length) {
      setCurrentIdx(currentIdx + 1);
    } else {
      onComplete(newAnswers);
    }
  };

  return (
    <Box flexDirection="column">
      <Text color={colors.primary}>
        ? <Text bold>Customizing video for:</Text> {concept}
      </Text>
      <Box marginTop={1} flexDirection="column">
        <Text bold color={colors.text}>
          {current.question}
        </Text>
        <Box marginTop={0}>
          <SelectList key={current.id} options={current.options} onSubmit={handleSelect} />
        </Box>
      </Box>
      <Box marginTop={1}>
        <Text color={colors.dim}>
          Question {currentIdx + 1} of {questions.length}  <Text color={colors.muted}>↑↓ navigate  ↵ select</Text>
        </Text>
      </Box>
    </Box>
  );
}
