import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';
import { colors, VERSION, MODEL_TAG, BRAND_ICON, TIPS, truncatePath } from '../lib/theme.js';
import { ConceptInput } from './ConceptInput.js';
import { PromptBar } from './PromptBar.js';
import { useRecentProjects } from '../hooks/useRecentProjects.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';
import { useAppContext } from '../context/AppContext.js';
import type { Project, AppDispatch } from '../lib/types.js';

// M9: Tip is selected inside the component (per-mount) not at module load

/** Number of project rows always reserved — keeps the welcome box height stable. */
const PROJECT_ROWS = 5;

/** Truncate from the right, keeping the beginning. */
function truncateRight(s: string, maxLen: number): string {
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen - 1) + '…';
}

type FocusMode = 'input' | 'projects';

interface WelcomeScreenProps {
  onSubmit: (concept: string) => void;
  onResumeProject: (project: Project) => void;
  dispatch?: AppDispatch;
}

export function WelcomeScreen({ onSubmit, onResumeProject, dispatch }: WelcomeScreenProps) {
  const { themeColors } = useAppContext();
  const { projects, loading } = useRecentProjects();
  // M9: Pick a tip per-mount so it varies across sessions
  const [tip] = useState(() => TIPS[Math.floor(Math.random() * TIPS.length)]!);
  const [focusMode, setFocusMode] = useState<FocusMode>('input');
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [clearKey, setClearKey] = useState(0);
  // Track slash mode from PromptBar so we can suspend our own key handling
  const [slashActive, setSlashActive] = useState(false);

  // Reactive terminal width — re-renders on resize
  const termWidth = useTerminalWidth();
  const BOX_WIDTH = Math.max(60, termWidth - 2);
  const BOX_INNER   = BOX_WIDTH - 2;
  const LEFT_WIDTH  = Math.floor(BOX_INNER * 0.42);
  const LEFT_CONTENT = LEFT_WIDTH - 4;
  const RIGHT_WIDTH  = BOX_INNER - LEFT_WIDTH - 1;
  const RIGHT_CONTENT = RIGHT_WIDTH - 4;
  const MAX_CONCEPT  = Math.max(8, RIGHT_CONTENT - 4);

  const cwd = process.cwd();
  const home = process.env['HOME'] ?? '';
  const displayCwd = home ? cwd.replace(home, '~') : cwd;

  useInput((_input, key) => {
    if (focusMode === 'input') {
      if (key.upArrow && projects.length > 0) {
        setFocusMode('projects');
        setSelectedIdx(projects.length - 1);
      } else if (key.escape) {
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
  }, { isActive: !slashActive });

  const hintText = focusMode === 'projects'
    ? '↑↓ select  Enter resume  Esc back to input'
    : projects.length > 0
      ? '↑ navigate recent  Enter submit  Esc clear'
      : 'Enter to submit  Esc clear';

  // Project rows: always render exactly PROJECT_ROWS lines so the welcome box
  // height never changes between the loading state and the loaded state.
  const projectRows = Array.from({ length: PROJECT_ROWS }, (_, idx) => {
    if (loading) {
      return (
        <Box key={`load-${idx}`}>
          <Text color={colors.dim}>{idx === 0 ? '  Loading…' : ' '}</Text>
        </Box>
      );
    }
    const p = projects[idx];
    if (!p) {
      // No project at this slot — show placeholder if list is empty on first slot
      return (
        <Box key={`empty-${idx}`}>
          <Text color={colors.dim}>
            {idx === 0 && projects.length === 0 ? '  No recent projects yet.' : ' '}
          </Text>
        </Box>
      );
    }
    const isSelected = focusMode === 'projects' && idx === selectedIdx;
    const icon = p.status === 'completed' ? '✓' : '○';
    const iconColor = p.status === 'completed' ? colors.success : colors.warn;
    const conceptDisplay = truncateRight(p.concept, MAX_CONCEPT);
    return (
      // Single <Text> guarantees exactly one terminal line per project
      <Text key={p.dir}>
        <Text color={isSelected ? colors.primary : colors.dim}>{isSelected ? '▸ ' : '  '}</Text>
        <Text color={iconColor}>{icon} </Text>
        <Text bold={isSelected} color={isSelected ? colors.primary : colors.text}>{conceptDisplay}</Text>
      </Text>
    );
  });

  return (
    <Box flexDirection="column" marginBottom={1}>
      {/* ── Welcome box — hidden when slash overlay is open to prevent terminal overflow.
           Hiding (not unmounting) keeps the PromptBar instance alive so its slashMode
           state survives the transition and the overlay opens on the first /. ── */}
      {!slashActive && (
        <Box flexDirection="row" borderStyle="round" borderColor={colors.primary} width={BOX_WIDTH}>
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
            {projectRows}
          </Box>
        </Box>
      )}

      {/* ── Input — always the same instance regardless of slashActive ── */}
      <Box flexDirection="column" paddingX={1}>
        {dispatch ? (
          <PromptBar
            onSubmit={onSubmit}
            dispatch={dispatch}
            isDisabled={!slashActive && focusMode === 'projects'}
            placeholder="Type a concept, /help for commands…"
            onSlashModeChange={setSlashActive}
          />
        ) : (
          <ConceptInput onSubmit={onSubmit} isDisabled={!slashActive && focusMode === 'projects'} clearKey={clearKey} />
        )}
        {!slashActive && focusMode === 'projects' && (
          <Box marginTop={1}>
            <Text color={themeColors.dim}>{hintText}</Text>
          </Box>
        )}
      </Box>
    </Box>
  );
}
