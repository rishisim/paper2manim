import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';
import { colors, VERSION, MODEL_TAG, BRAND_ICON, TIPS, truncatePath } from '../lib/theme.js';
import { ConceptInput } from './ConceptInput.js';
import { useRecentProjects } from '../hooks/useRecentProjects.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';
import type { Project } from '../lib/types.js';

// Pick tip once at module load (not on every render)
const tip = TIPS[Math.floor(Math.random() * TIPS.length)]!;

/** Truncate from the right, keeping the beginning. */
function truncateRight(s: string, maxLen: number): string {
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen - 1) + '…';
}

type FocusMode = 'input' | 'projects';

interface WelcomeScreenProps {
  onSubmit: (concept: string) => void;
  onResumeProject: (project: Project) => void;
}

export function WelcomeScreen({ onSubmit, onResumeProject }: WelcomeScreenProps) {
  const { projects, loading } = useRecentProjects();
  const [focusMode, setFocusMode] = useState<FocusMode>('input');
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [clearKey, setClearKey] = useState(0);

  // Reactive terminal width — re-renders on resize
  const termWidth = useTerminalWidth();
  const BOX_WIDTH = Math.max(60, termWidth - 2);

  // Box inner area (subtract left+right borders)
  const BOX_INNER = BOX_WIDTH - 2;

  // Left panel ~42% of inner area
  const LEFT_WIDTH = Math.floor(BOX_INNER * 0.42);
  // Content available inside left panel (subtract paddingX=2 on each side)
  const LEFT_CONTENT = LEFT_WIDTH - 4;

  // Divider column = 1 char; right panel gets the rest
  const RIGHT_WIDTH = BOX_INNER - LEFT_WIDTH - 1;
  // Content available inside right panel (subtract paddingX=2 on each side)
  const RIGHT_CONTENT = RIGHT_WIDTH - 4;

  // Max concept length per project row: RIGHT_CONTENT minus pointer (2) + icon (2)
  const MAX_CONCEPT = Math.max(8, RIGHT_CONTENT - 4);

  const cwd = process.cwd();
  const home = process.env['HOME'] ?? '';
  const displayCwd = home ? cwd.replace(home, '~') : cwd;

  useInput((_input, key) => {
    if (focusMode === 'input') {
      if (key.upArrow && projects.length > 0) {
        setFocusMode('projects');
        setSelectedIdx(projects.length - 1);
      } else if (key.escape) {
        // Esc clears the input field (Claude Code style)
        setClearKey(k => k + 1);
      }
    } else if (focusMode === 'projects') {
      if (key.upArrow) {
        setSelectedIdx(i => Math.max(0, i - 1));
      } else if (key.downArrow) {
        if (selectedIdx >= projects.length - 1) {
          setFocusMode('input');
        } else {
          setSelectedIdx(i => i + 1);
        }
      } else if (key.escape) {
        setFocusMode('input');
      } else if (key.return) {
        const project = projects[selectedIdx];
        if (project) onResumeProject(project);
      }
    }
  });

  const hintText = focusMode === 'projects'
    ? '↑↓ select  Enter resume  Esc back to input'
    : projects.length > 0
      ? '↑ navigate recent  Enter submit  Esc clear'
      : 'Enter to submit  Esc clear';

  return (
    <Box flexDirection="column" marginBottom={1}>
      {/* ── Welcome box ── */}
      <Box
        flexDirection="row"
        borderStyle="round"
        borderColor={colors.primary}
        width={BOX_WIDTH}
      >
        {/* LEFT PANEL */}
        <Box flexDirection="column" width={LEFT_WIDTH} paddingX={2} paddingY={1}>
          <Text>
            <Text bold color={colors.primary}>{BRAND_ICON}</Text>
            <Text bold color={colors.text}> paper2manim</Text>
            <Text color={colors.dim}>  v{VERSION}</Text>
          </Text>
          <Box marginTop={1} justifyContent="center">
            <Text bold color={colors.primary}>{BRAND_ICON}</Text>
          </Box>
          <Box marginTop={1}>
            <Text color={colors.dim}>{truncateRight(MODEL_TAG, LEFT_CONTENT)}</Text>
          </Box>
          <Text color={colors.dim}>{truncatePath(displayCwd, LEFT_CONTENT)}</Text>
        </Box>

        {/* VERTICAL DIVIDER */}
        <Box
          borderStyle="single"
          borderLeft={true}
          borderRight={false}
          borderTop={false}
          borderBottom={false}
          borderColor={colors.dim}
        />

        {/* RIGHT PANEL */}
        <Box flexDirection="column" width={RIGHT_WIDTH} paddingX={2} paddingY={1}>
          <Text bold color={colors.dim}>Tips for getting started</Text>
          <Text color={colors.dim}>{truncateRight(tip, RIGHT_CONTENT)}</Text>
          <Box marginTop={1}>
            <Text color={colors.dim}>{'─'.repeat(RIGHT_CONTENT)}</Text>
          </Box>
          <Box marginTop={1}>
            <Text bold color={colors.dim}>Recent projects</Text>
          </Box>
          {loading && (
            <Text color={colors.dim}>  Loading…</Text>
          )}
          {!loading && projects.length === 0 && (
            <Text color={colors.dim}>  No recent projects yet.</Text>
          )}
          {/* Each project rendered as a single <Text> to guarantee one line */}
          {!loading && projects.map((p, idx) => {
            const isSelected = focusMode === 'projects' && idx === selectedIdx;
            const icon = p.status === 'completed' ? '✓' : '○';
            const iconColor = p.status === 'completed' ? colors.success : colors.warn;
            const conceptDisplay = truncateRight(p.concept, MAX_CONCEPT);
            return (
              <Text key={p.dir}>
                <Text color={isSelected ? colors.primary : colors.dim}>{isSelected ? '▸ ' : '  '}</Text>
                <Text color={iconColor}>{icon} </Text>
                <Text bold={isSelected} color={isSelected ? colors.primary : colors.text}>{conceptDisplay}</Text>
              </Text>
            );
          })}
        </Box>
      </Box>

      {/* ── Input below the box ── */}
      <Box flexDirection="column" paddingX={1}>
        <ConceptInput onSubmit={onSubmit} isDisabled={focusMode === 'projects'} clearKey={clearKey} />
        <Box marginTop={1}>
          <Text color={colors.dim}>{hintText}</Text>
        </Box>
      </Box>
    </Box>
  );
}
