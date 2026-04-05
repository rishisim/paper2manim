import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import type { QuestionDef } from '../lib/types.js';

interface QuestionnaireProps {
  concept: string;
  questions: QuestionDef[];
  onComplete: (answers: Record<string, string>) => void;
}

/** Minimal arrow-key select list — no external dependency. */
function SelectList({ options, onSubmit }: { options: string[]; onSubmit: (value: string) => void }) {
  const { themeColors } = useAppContext();
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
            <Text color={themeColors.primary} bold>{'❯ '}{opt}</Text>
          ) : (
            <Text color={themeColors.dim}>{'  '}{opt}</Text>
          )}
        </Text>
      ))}
    </Box>
  );
}

export function Questionnaire({ concept, questions, onComplete }: QuestionnaireProps) {
  const { themeColors } = useAppContext();
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
      <Text color={themeColors.primary}>
        ? <Text bold>Customizing video for:</Text> {concept}
      </Text>
      <Box marginTop={1} flexDirection="column">
        <Text bold color={themeColors.text}>
          {current.question}
        </Text>
        <Box marginTop={0}>
          <SelectList key={current.id} options={current.options} onSubmit={handleSelect} />
        </Box>
      </Box>
      <Box marginTop={1}>
        <Text color={themeColors.dim}>
          Question {currentIdx + 1} of {questions.length}  <Text color={themeColors.muted}>↑↓ navigate  ↵ select</Text>
        </Text>
      </Box>
    </Box>
  );
}
