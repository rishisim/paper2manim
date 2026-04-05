import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';
import { VERSION, MODEL_TAG, BRAND_ICON, TIPS, truncatePath } from '../lib/theme.js';
import { truncateRight } from '../lib/format.js';
import { ConceptInput } from './ConceptInput.js';
import { PromptBar } from './PromptBar.js';
import { useRecentProjects } from '../hooks/useRecentProjects.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';
import { useAppContext } from '../context/AppContext.js';
import type { Project, AppDispatch } from '../lib/types.js';

type FocusMode = 'input' | 'projects';

interface WelcomeScreenProps {
  onSubmit: (concept: string) => void;
  onResumeProject: (project: Project) => void;
  dispatch?: AppDispatch;
  promptPrefill?: string;
  onPromptPrefillConsumed?: () => void;
}

export function WelcomeScreen({ onSubmit, onResumeProject, dispatch, promptPrefill, onPromptPrefillConsumed }: WelcomeScreenProps) {
  const { themeColors } = useAppContext();
  const { projects, loading } = useRecentProjects();
  const [tip] = useState(() => TIPS[Math.floor(Math.random() * TIPS.length)]!);
  const [focusMode, setFocusMode] = useState<FocusMode>('input');
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [clearKey, setClearKey] = useState(0);
  const [slashActive, setSlashActive] = useState(false);

  const termWidth = useTerminalWidth();
  const contentWidth = Math.min(termWidth - 4, 100);
  const maxConcept = Math.max(8, contentWidth - 30);

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

  // Welcome banner — bordered box matching Claude Code style
  const welcomeBox = (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={themeColors.primary}
      paddingX={2}
      paddingY={0}
    >
      <Box>
        <Text bold color={themeColors.primary}>{BRAND_ICON}</Text>
        <Text bold color={themeColors.text}> paper2manim</Text>
        <Text color={themeColors.muted}> v{VERSION}</Text>
      </Box>
      <Box>
        <Text color={themeColors.muted}>{truncateRight(MODEL_TAG, contentWidth - 6)}</Text>
      </Box>
      <Box>
        <Text color={themeColors.dim}>{truncatePath(displayCwd, contentWidth - 6)}</Text>
      </Box>
      {!slashActive && (
        <Box marginTop={1}>
          <Text color={themeColors.dim}>Tip: {truncateRight(tip, contentWidth - 10)}</Text>
        </Box>
      )}
    </Box>
  );

  // Detailed content — hidden when slash overlay is active
  const detailedContent = !slashActive && (
    <>
      {/* Recent projects */}
      {(loading || projects.length > 0) && (
        <Box flexDirection="column" paddingX={1} marginTop={1}>
          <Text bold color={themeColors.muted}>Recent projects</Text>
          {loading ? (
            <Text color={themeColors.dim}>  Loading...</Text>
          ) : (
            projects.slice(0, 5).map((p, idx) => {
              const isSelected = focusMode === 'projects' && idx === selectedIdx;
              const icon = p.status === 'completed' ? '✔' : '◯';
              const iconColor = p.status === 'completed' ? themeColors.success : themeColors.warn;
              const conceptDisplay = truncateRight(p.concept, maxConcept);
              return (
                <Text key={p.dir}>
                  <Text color={isSelected ? themeColors.primary : themeColors.dim}>{isSelected ? '❯ ' : '  '}</Text>
                  <Text color={iconColor}>{icon} </Text>
                  <Text bold={isSelected} color={isSelected ? themeColors.primary : themeColors.text}>{conceptDisplay}</Text>
                </Text>
              );
            })
          )}
        </Box>
      )}
    </>
  );

  const hintText = focusMode === 'projects'
    ? '↑↓ select  Enter resume  Esc back'
    : projects.length > 0
      ? '↑ recent projects  / commands'
      : '/ commands  Enter submit';

  return (
    <Box flexDirection="column" marginBottom={1}>
      {welcomeBox}
      {detailedContent}

      {/* Input — always the same instance regardless of slashActive */}
      <Box flexDirection="column" paddingX={1} marginTop={1}>
        {dispatch ? (
          <PromptBar
            onSubmit={onSubmit}
            dispatch={dispatch}
            isDisabled={!slashActive && focusMode === 'projects'}
            placeholder="Type a concept, or / for commands…"
            onSlashModeChange={setSlashActive}
            prefill={promptPrefill}
            onPrefillConsumed={onPromptPrefillConsumed}
          />
        ) : (
          <ConceptInput onSubmit={onSubmit} isDisabled={!slashActive && focusMode === 'projects'} clearKey={clearKey} />
        )}
        {!slashActive && (
          <Box paddingLeft={2}>
            <Text color={themeColors.dim}>{hintText}</Text>
          </Box>
        )}
      </Box>
    </Box>
  );
}
