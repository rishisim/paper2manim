import React from 'react';
import { Box, Text } from 'ink';
import { TextInput } from '@inkjs/ui';
import { colors } from '../lib/theme.js';

interface ConceptInputProps {
  onSubmit: (concept: string) => void;
  isDisabled?: boolean;
  /** Increment to force-clear the input field (remounts the uncontrolled TextInput). */
  clearKey?: number;
}

export function ConceptInput({ onSubmit, isDisabled = false, clearKey = 0 }: ConceptInputProps) {
  return (
    <Box flexDirection="column">
      <Text bold>What concept would you like to visualize?</Text>
      <Box marginTop={1}>
        <Text color={colors.primary} bold>{'> '}</Text>
        <TextInput
          key={clearKey}
          isDisabled={isDisabled}
          placeholder="e.g. The Dot Product, Fourier Transform..."
          onSubmit={(value) => {
            const trimmed = value.trim();
            if (trimmed) onSubmit(trimmed);
          }}
        />
      </Box>
    </Box>
  );
}
