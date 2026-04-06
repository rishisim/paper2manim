import React, { useEffect, useState } from 'react';
import { Box, Text, useInput } from 'ink';
import { VERSION, MODEL_TAG, BRAND_ICON, truncatePath } from '../lib/theme.js';
import { formatRelativeDate, truncateRight } from '../lib/format.js';
import { PromptBar } from './PromptBar.js';
import { useRecentProjects } from '../hooks/useRecentProjects.js';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';
import { useTerminalHeight } from '../hooks/useTerminalHeight.js';
import { useAppContext } from '../context/AppContext.js';
import type { Project, AppDispatch } from '../lib/types.js';
import {
  GOAL_SUGGESTIONS,
  QUALITY_OPTIONS,
  WELCOME_EXAMPLES,
  composeConceptSubmission,
  moveOnboardingFocus,
  getQualityEnterOutcome,
  getProjectViewModel,
  nextWelcomeFocusArea,
  previousWelcomeFocusArea,
  type WelcomeFocusArea,
} from '../lib/welcome.js';

interface WelcomeScreenProps {
  onSubmit: (concept: string) => void;
  onResumeProject: (project: Project) => void;
  dispatch?: AppDispatch;
  promptPrefill?: string;
  onPromptPrefillConsumed?: () => void;
}

function qualityLabel(quality: 'low' | 'medium' | 'high'): string {
  return quality.charAt(0).toUpperCase() + quality.slice(1);
}

const GOAL_OPTIONS = [...GOAL_SUGGESTIONS, 'other'] as const;
const OTHER_GOAL_OPTION_INDEX = GOAL_OPTIONS.length - 1;

export function WelcomeScreen({ onSubmit, onResumeProject, dispatch, promptPrefill, onPromptPrefillConsumed }: WelcomeScreenProps) {
  const { themeColors, quality } = useAppContext();
  const { projects, loading } = useRecentProjects();
  const [focusArea, setFocusArea] = useState<WelcomeFocusArea>('concept');
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [slashActive, setSlashActive] = useState(false);
  const [goalDraft, setGoalDraft] = useState('');
  const [goalOptionIndex, setGoalOptionIndex] = useState(-1);
  const [selectedQuality, setSelectedQuality] = useState<'low' | 'medium' | 'high'>(quality);
  const [conceptDraft, setConceptDraft] = useState('');
  const [validationMessage, setValidationMessage] = useState<string | null>(null);

  const termWidth = useTerminalWidth();
  const termHeight = useTerminalHeight();
  const contentWidth = Math.max(30, Math.min(termWidth - 2, 110));
  const splitColumns = contentWidth >= 96;
  const singlePaneMode = termHeight <= 34;
  const collapsedSteps = termHeight <= 36;
  const mainWidth = splitColumns ? Math.floor(contentWidth * 0.64) : contentWidth;
  const sideWidth = splitColumns ? contentWidth - mainWidth - 2 : contentWidth;
  const isTightHeight = termHeight < 32;
  const isVeryTightHeight = termHeight < 27;
  const maxRecent = singlePaneMode ? (termHeight < 24 ? 1 : 2) : isVeryTightHeight ? 2 : isTightHeight ? 3 : 5;
  const visibleProjects = projects.slice(0, maxRecent);

  const cwd = process.cwd();
  const home = process.env['HOME'] ?? '';
  const displayCwd = home ? cwd.replace(home, '~') : cwd;

  useEffect(() => {
    setSelectedQuality(quality);
  }, [quality]);

  useEffect(() => {
    setSelectedIdx(prev => Math.min(prev, Math.max(visibleProjects.length - 1, 0)));
  }, [visibleProjects.length]);

  useEffect(() => {
    if (focusArea === 'projects' && visibleProjects.length === 0) {
      setFocusArea('concept');
    }
  }, [focusArea, visibleProjects.length]);

  const submitConcept = (rawConcept: string) => {
    const composed = composeConceptSubmission(rawConcept, goalDraft);
    dispatch?.setQuality(selectedQuality);
    setValidationMessage(null);
    onSubmit(composed);
  };

  const advanceFromConcept = (rawConcept: string) => {
    setConceptDraft(rawConcept);
    setValidationMessage(null);
    setFocusArea('goal');
  };

  const selectGoalOption = (index: number) => {
    if (index < 0 || index >= GOAL_OPTIONS.length) return;
    setGoalOptionIndex(index);
    const option = GOAL_OPTIONS[index];
    if (option === 'other') {
      setGoalDraft('');
      return;
    }
    setGoalDraft(option);
  };

  useInput((_input, key) => {
    if (slashActive) return;

    if (focusArea === 'projects') {
      if (key.upArrow) {
        if (selectedIdx === 0) {
          setFocusArea('quality');
        } else {
          setSelectedIdx(prev => Math.max(0, prev - 1));
        }
        return;
      }
      if (key.downArrow) {
        if (selectedIdx >= visibleProjects.length - 1) {
          setFocusArea('concept');
        } else {
          setSelectedIdx(prev => Math.max(0, Math.min(visibleProjects.length - 1, prev + 1)));
        }
        return;
      }
      if (key.return) {
        const project = visibleProjects[selectedIdx];
        if (project) onResumeProject(project);
        return;
      }
      if (key.escape) {
        setFocusArea('concept');
        return;
      }
    }

    if (key.tab && !key.shift) {
      setFocusArea(current => nextWelcomeFocusArea(current, visibleProjects.length > 0));
      setValidationMessage(null);
      return;
    }

    if (key.tab && key.shift) {
      setFocusArea(current => previousWelcomeFocusArea(current, visibleProjects.length > 0));
      setValidationMessage(null);
      return;
    }

    if (focusArea === 'quality' && key.downArrow) {
      setFocusArea(current => moveOnboardingFocus(current, 'down', visibleProjects.length > 0));
      setValidationMessage(null);
      return;
    }

    if (focusArea === 'quality' && key.upArrow) {
      setFocusArea(current => moveOnboardingFocus(current, 'up', visibleProjects.length > 0));
      setValidationMessage(null);
      return;
    }

    if (focusArea === 'quality') {
      if (key.return || _input === '\n') {
        const outcome = getQualityEnterOutcome(conceptDraft);
        if (!outcome.shouldSubmit) {
          setValidationMessage(outcome.validationMessage ?? 'Add a topic first and try again.');
          setFocusArea('concept');
          return;
        }
        submitConcept(conceptDraft);
        return;
      }
      if (key.leftArrow) {
        setSelectedQuality(prev => QUALITY_OPTIONS[Math.max(0, QUALITY_OPTIONS.indexOf(prev) - 1)] ?? prev);
        return;
      }
      if (key.rightArrow) {
        setSelectedQuality(prev => QUALITY_OPTIONS[Math.min(QUALITY_OPTIONS.length - 1, QUALITY_OPTIONS.indexOf(prev) + 1)] ?? prev);
        return;
      }
      if (_input === '1') { setSelectedQuality('low'); return; }
      if (_input === '2') { setSelectedQuality('medium'); return; }
      if (_input === '3') { setSelectedQuality('high'); return; }
    }

    if (focusArea === 'goal') {
      if (key.upArrow) {
        setFocusArea(current => moveOnboardingFocus(current, 'up', visibleProjects.length > 0));
        setValidationMessage(null);
        return;
      }
      if (key.downArrow) {
        setFocusArea(current => moveOnboardingFocus(current, 'down', visibleProjects.length > 0));
        setValidationMessage(null);
        return;
      }
      if (key.return || _input === '\n') {
        setValidationMessage(null);
        setFocusArea('quality');
        return;
      }
      if (key.leftArrow) {
        const next = goalOptionIndex <= 0 ? GOAL_OPTIONS.length - 1 : goalOptionIndex - 1;
        selectGoalOption(next);
        return;
      }
      if (key.rightArrow) {
        const next = goalOptionIndex >= GOAL_OPTIONS.length - 1 ? 0 : goalOptionIndex + 1;
        selectGoalOption(next);
        return;
      }

      const numericChoice = Number.parseInt(_input, 10);
      if (!Number.isNaN(numericChoice) && numericChoice >= 1 && numericChoice <= GOAL_OPTIONS.length) {
        selectGoalOption(numericChoice - 1);
        return;
      }

      if (key.backspace || key.delete) {
        setGoalOptionIndex(OTHER_GOAL_OPTION_INDEX);
        setGoalDraft(prev => prev.slice(0, -1));
        return;
      }

      if (_input && !key.ctrl && !key.meta) {
        setGoalOptionIndex(OTHER_GOAL_OPTION_INDEX);
        setGoalDraft(prev => prev + _input);
        return;
      }
    }
  }, { isActive: !slashActive });

  const projectPreview = visibleProjects[selectedIdx];
  const projectPreviewVm = projectPreview ? getProjectViewModel(projectPreview) : null;

  const onboardingCopy = [
    'Step 1: add a clear topic.',
    'Step 2: optionally add a teaching goal.',
    'Step 3: pick quality, then press Enter to generate.',
  ].slice(0, isVeryTightHeight ? 1 : isTightHeight ? 2 : 3);

  const conceptPrompt = dispatch ? (
    <PromptBar
      onSubmit={advanceFromConcept}
      onEmptySubmit={() => setValidationMessage('Add a topic first, like "Chain rule intuition for beginners", then press Enter to continue.')}
      onValueChange={(value) => {
        if (value.startsWith('/')) return;
        if (value === '' && slashActive) return;
        setConceptDraft(value);
        if (validationMessage && value.trim()) setValidationMessage(null);
      }}
      externalValue={conceptDraft}
      dispatch={dispatch}
      isDisabled={!slashActive && focusArea !== 'concept'}
      placeholder={'Try: "Chain rule intuition with visual examples for beginners"'}
      onSlashModeChange={setSlashActive}
      prefill={promptPrefill}
      onPrefillConsumed={onPromptPrefillConsumed}
      preserveInputOnSubmit
      disableHistoryNavigation
      onNavigateUp={() => {
        setFocusArea(current => moveOnboardingFocus(current, 'up', visibleProjects.length > 0));
        setValidationMessage(null);
      }}
      onNavigateDown={() => {
        setFocusArea(current => moveOnboardingFocus(current, 'down', visibleProjects.length > 0));
        setValidationMessage(null);
      }}
    />
  ) : null;

  return (
    <Box flexDirection="column" marginBottom={1}>
      {singlePaneMode || slashActive ? (
        <Box marginBottom={1} paddingX={1}>
          <Text>
            <Text bold color={themeColors.primary}>{BRAND_ICON}</Text>
            <Text bold color={themeColors.text}> paper2manim</Text>
            <Text color={themeColors.muted}> v{VERSION}</Text>
            <Text color={themeColors.dim}>
              {slashActive
                ? '  Command mode'
                : `  ${truncatePath(displayCwd, Math.max(12, contentWidth - 24))}`}
            </Text>
          </Text>
        </Box>
      ) : (
        <Box
          borderStyle="round"
          borderColor={themeColors.primary}
          paddingX={2}
          paddingY={0}
          marginBottom={1}
        >
          <Box flexDirection="column" width={contentWidth}>
            <Box>
              <Text bold color={themeColors.primary}>{BRAND_ICON}</Text>
              <Text bold color={themeColors.text}> paper2manim</Text>
              <Text color={themeColors.muted}> v{VERSION}</Text>
            </Box>
            <Text color={themeColors.muted}>{truncateRight(MODEL_TAG, contentWidth - 4)}</Text>
            <Text color={themeColors.dim}>{truncatePath(displayCwd, contentWidth - 4)}</Text>
          </Box>
        </Box>
      )}

      <Box flexDirection={splitColumns && !singlePaneMode ? 'row' : 'column'}>
        {(!singlePaneMode || focusArea !== 'projects') && (
        <Box
          flexDirection="column"
          width={splitColumns && !singlePaneMode ? mainWidth : contentWidth}
          borderStyle="round"
          borderColor={focusArea === 'concept' || focusArea === 'goal' || focusArea === 'quality' ? themeColors.primary : themeColors.separator}
          paddingX={2}
          paddingY={1}
          marginRight={splitColumns && !singlePaneMode ? 1 : 0}
          marginBottom={splitColumns && !singlePaneMode ? 0 : 1}
        >
          <Text bold color={themeColors.text}>{slashActive ? 'Slash Commands' : 'Start New Video'}</Text>
          {slashActive ? (
            <Text color={themeColors.dim}>Type to filter. Press Esc to close command mode.</Text>
          ) : onboardingCopy.map((line) => (
            <Text key={line} color={themeColors.dim}>{truncateRight(line, mainWidth - 4)}</Text>
          ))}

          <Box flexDirection="column" marginTop={1}>
            <Text bold color={focusArea === 'concept' || slashActive ? themeColors.primary : themeColors.muted}>
              {slashActive ? 'Now: Command Input' : 'Now: Topic'}
            </Text>
            {slashActive ? (
              <Text color={themeColors.dim}>Type `/` to browse, keep typing to filter, then press Enter or Tab to accept.</Text>
            ) : (!collapsedSteps || focusArea === 'concept') ? (
              <>
                <Text color={themeColors.dim}>Press Enter to continue to Step 2.</Text>
              </>
            ) : (
              <Text color={themeColors.dim}>Press Down to edit topic.</Text>
            )}
            <Box marginTop={1}>
              {conceptPrompt}
            </Box>
          </Box>

          {!slashActive && (
          <Box flexDirection="column" marginTop={1}>
            <Text bold color={focusArea === 'goal' ? themeColors.primary : themeColors.muted}>Step 2 (Optional): Teaching Goal</Text>
            {(!collapsedSteps || focusArea === 'goal') ? (
              <>
                <Text color={themeColors.dim}>Choose a goal, or select other to type your own.</Text>
                <Box marginTop={1} flexWrap="wrap">
                  {GOAL_OPTIONS.map((goal, idx) => {
                    const selected = goalOptionIndex === idx;
                    const isOther = goal === 'other';
                    const goalLabel = isOther && selected
                      ? focusArea === 'goal'
                        ? `[${goalDraft}| ]`
                        : goalDraft.trim()
                          ? `[${goalDraft}]`
                          : '[other]'
                      : `[${goal}]`;

                    return (
                      <Box key={goal} marginRight={1}>
                        <Text color={selected ? themeColors.primary : themeColors.dim} bold={selected}>
                          {goalLabel}
                        </Text>
                      </Box>
                    );
                  })}
                </Box>
              </>
            ) : (
              <Text color={themeColors.dim}>{goalDraft.trim() ? `Current goal: ${truncateRight(goalDraft, mainWidth - 20)}` : 'Press Down to choose optional goal.'}</Text>
            )}
          </Box>
          )}

          {!slashActive && (
          <Box flexDirection="column" marginTop={1}>
            <Text bold color={focusArea === 'quality' ? themeColors.primary : themeColors.muted}>Step 3: Quality</Text>
            {(!collapsedSteps || focusArea === 'quality') ? (
              <>
                <Text color={themeColors.dim}>Current quality: <Text color={themeColors.primary}>{qualityLabel(selectedQuality)}</Text>. Use Left/Right or 1/2/3.</Text>
                <Box marginTop={1} flexWrap="wrap">
                  {QUALITY_OPTIONS.map((option, index) => {
                    const selected = option === selectedQuality;
                    return (
                      <Box key={option} marginRight={1}>
                        <Text color={selected ? themeColors.primary : themeColors.dim} bold={selected}>
                          [{index + 1}] {qualityLabel(option)}{selected ? ' (selected)' : ''}
                        </Text>
                      </Box>
                    );
                  })}
                </Box>
              </>
            ) : (
              <Text color={themeColors.dim}>Current quality: {qualityLabel(selectedQuality)}</Text>
            )}
          </Box>
          )}

          {validationMessage && (
            <Box marginTop={1}>
              <Text color={themeColors.warn}>{truncateRight(validationMessage, mainWidth - 4)}</Text>
            </Box>
          )}

          {!slashActive && !isVeryTightHeight && !collapsedSteps && (
            <Box flexDirection="column" marginTop={1}>
              <Text bold color={themeColors.muted}>Example prompts</Text>
              {WELCOME_EXAMPLES.slice(0, isTightHeight ? 2 : 3).map((example) => (
                <Text key={example} color={themeColors.dim}>- {truncateRight(example, mainWidth - 6)}</Text>
              ))}
            </Box>
          )}

          <Box marginTop={1}>
            <Text color={themeColors.dim}>
              {focusArea === 'concept'
                ? 'Press Enter to move to Step 2. Down/Tab also moves focus.'
                : focusArea === 'goal'
                  ? 'Press Enter to move to Step 3. Down/Tab also moves focus.'
                  : focusArea === 'quality'
                    ? 'Use 1/2/3 or arrows, then press Enter to generate.'
                    : 'Enter resumes selected project. Esc returns to new run.'}
              {'  '}Shortcuts: <Text color={themeColors.muted}>/ for commands  ? for help</Text>
            </Text>
          </Box>
        </Box>
        )}

        {(!slashActive && (!singlePaneMode || focusArea === 'projects')) && (
        <Box
          flexDirection="column"
          width={splitColumns && !singlePaneMode ? sideWidth : contentWidth}
          borderStyle="round"
          borderColor={focusArea === 'projects' ? themeColors.primary : themeColors.separator}
          paddingX={2}
          paddingY={1}
        >
          <Text bold color={themeColors.text}>Recent Projects</Text>
          <Text color={themeColors.dim}>Quick resume is one Enter away when you switch focus here.</Text>

          <Box marginTop={1} flexDirection="column">
            {loading ? (
              <Text color={themeColors.dim}>Loading recent work...</Text>
            ) : visibleProjects.length === 0 ? (
              <Text color={themeColors.dim}>Your next project will show up here for quick resume.</Text>
            ) : (
              visibleProjects.map((project, idx) => {
                const vm = getProjectViewModel(project);
                const selected = focusArea === 'projects' && idx === selectedIdx;
                const statusColor = vm.statusTone === 'success'
                  ? themeColors.success
                  : vm.statusTone === 'error'
                    ? themeColors.error
                    : themeColors.warn;
                return (
                  <Box key={project.dir} flexDirection="column" marginBottom={1}>
                    <Text>
                      <Text color={selected ? themeColors.primary : themeColors.dim}>{selected ? '❯ ' : '  '}</Text>
                      <Text bold={selected}>{truncateRight(project.concept, sideWidth - 8)}</Text>
                    </Text>
                    <Text color={statusColor}>  {vm.statusLabel}</Text>
                    {!singlePaneMode && (
                      <Text color={themeColors.dim}>  {truncateRight(formatRelativeDate(project.updated_at), sideWidth - 4)}</Text>
                    )}
                    <Text color={themeColors.dim}>  {truncateRight(vm.secondaryText, sideWidth - 4)}</Text>
                  </Box>
                );
              })
            )}
          </Box>

          {projects.length > visibleProjects.length && (
            <Box marginTop={1}>
              <Text color={themeColors.dim}>
                Showing {visibleProjects.length} recent projects for this terminal height.
              </Text>
            </Box>
          )}

          {projectPreview && projectPreviewVm && (
            <Box flexDirection="column" marginTop={1}>
              <Text bold color={themeColors.muted}>Selected action</Text>
              <Text color={themeColors.dim}>{truncateRight(projectPreviewVm.resumeLabel, sideWidth - 4)}</Text>
              <Text color={themeColors.dim}>Press Enter to resume <Text bold>{truncateRight(projectPreview.concept, sideWidth - 24)}</Text></Text>
            </Box>
          )}

          <Box marginTop={1}>
            <Text color={themeColors.dim}>Up/Down browse  Enter run suggested action  Esc return</Text>
            {singlePaneMode && (
              <Text color={themeColors.dim}>Up at top returns to onboarding.</Text>
            )}
          </Box>
        </Box>
        )}
      </Box>
    </Box>
  );
}
