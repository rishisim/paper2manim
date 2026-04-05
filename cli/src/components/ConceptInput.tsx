import React from 'react';
import { Box, Text } from 'ink';
import { TextInput } from '@inkjs/ui';
import { useAppContext } from '../context/AppContext.js';

interface ConceptInputProps {
  onSubmit: (concept: string) => void;
  isDisabled?: boolean;
  /** Increment to force-clear the input field (remounts the uncontrolled TextInput). */
  clearKey?: number;
}

export function ConceptInput({ onSubmit, isDisabled = false, clearKey = 0 }: ConceptInputProps) {
  const { themeColors, promptColor } = useAppContext();
  return (
    <Box flexDirection="column">
      <Box borderStyle="round" borderColor={promptColor} paddingX={1}>
        <Text color={themeColors.success} bold>{'> '}</Text>
        <TextInput
          key={clearKey}
          isDisabled={isDisabled}
          placeholder="Type a concept to visualize…"
          onSubmit={(value) => {
            const trimmed = value.trim();
            if (trimmed) onSubmit(trimmed);
          }}
        />
      </Box>
    </Box>
  );
}
