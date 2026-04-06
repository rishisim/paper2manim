import type { Project, ProjectPrimaryAction, ProjectStateBadge } from './types.js';

export type WelcomeFocusArea = 'concept' | 'goal' | 'quality' | 'projects';

export interface OnboardingState {
  step: WelcomeFocusArea;
  conceptDraft: string;
  goalDraft: string;
  selectedQuality: 'low' | 'medium' | 'high';
  readyToSubmit: boolean;
}

export interface WelcomeProjectViewModel {
  statusLabel: string;
  statusTone: 'success' | 'warn' | 'error';
  badge: ProjectStateBadge;
  primaryAction: ProjectPrimaryAction;
  primaryActionLabel: string;
  secondaryText: string;
  resumeLabel: string;
}

export const WELCOME_EXAMPLES = [
  'Chain rule intuition with moving tangent lines',
  'Why eigenvectors matter in PCA',
  'Visual walkthrough of Bayes theorem for exam prep',
] as const;

export const GOAL_SUGGESTIONS = [
  'intuition',
  'exam prep',
  'visual walkthrough',
] as const;

export const QUALITY_OPTIONS: Array<'low' | 'medium' | 'high'> = ['low', 'medium', 'high'];

export function moveOnboardingFocus(
  current: WelcomeFocusArea,
  direction: 'up' | 'down',
  hasProjects: boolean,
): WelcomeFocusArea {
  switch (current) {
    case 'concept':
      return direction === 'down' ? 'goal' : 'concept';
    case 'goal':
      return direction === 'down' ? 'quality' : 'concept';
    case 'quality':
      return direction === 'down' ? (hasProjects ? 'projects' : 'concept') : 'goal';
    case 'projects':
      return direction === 'down' ? 'concept' : 'quality';
  }
}

export function nextWelcomeFocusArea(current: WelcomeFocusArea, hasProjects: boolean): WelcomeFocusArea {
  switch (current) {
    case 'concept': return 'goal';
    case 'goal': return 'quality';
    case 'quality': return hasProjects ? 'projects' : 'concept';
    case 'projects': return 'concept';
  }
}

export function previousWelcomeFocusArea(current: WelcomeFocusArea, hasProjects: boolean): WelcomeFocusArea {
  switch (current) {
    case 'concept': return hasProjects ? 'projects' : 'quality';
    case 'goal': return 'concept';
    case 'quality': return 'goal';
    case 'projects': return 'quality';
  }
}

export function createOnboardingState(
  quality: 'low' | 'medium' | 'high',
  overrides: Partial<OnboardingState> = {},
): OnboardingState {
  const conceptDraft = overrides.conceptDraft ?? '';
  return {
    step: overrides.step ?? 'concept',
    conceptDraft,
    goalDraft: overrides.goalDraft ?? '',
    selectedQuality: overrides.selectedQuality ?? quality,
    readyToSubmit: conceptDraft.trim().length > 0,
  };
}

export function validateConceptDraft(value: string): string | null {
  return value.trim().length > 0
    ? null
    : 'Start with a topic or question so we have something concrete to animate.';
}

export interface QualityEnterOutcome {
  shouldSubmit: boolean;
  validationMessage?: string;
}

export function getQualityEnterOutcome(conceptDraft: string): QualityEnterOutcome {
  if (conceptDraft.trim().length > 0) {
    return { shouldSubmit: true };
  }
  return {
    shouldSubmit: false,
    validationMessage: 'Add a topic first, like "Chain rule intuition for beginners", then press Enter to continue.',
  };
}

export function composeConceptSubmission(concept: string, goal?: string): string {
  const trimmedConcept = concept.trim();
  const trimmedGoal = goal?.trim();
  if (!trimmedGoal) return trimmedConcept;
  return `${trimmedConcept}\n\nPresentation goal: ${trimmedGoal}`;
}

export function getProjectViewModel(project: Project): WelcomeProjectViewModel {
  const completed = project.status === 'completed';
  const failed = project.status === 'failed' || project.status === 'error';
  const badge: ProjectStateBadge = completed ? 'completed' : failed ? 'attention' : 'in_progress';
  const progressPct = project.progress_total > 0
    ? Math.round((project.progress_done / project.progress_total) * 100)
    : 0;
  const primaryAction: ProjectPrimaryAction = completed
    ? (project.has_video ? 'open_video' : 'view_summary')
    : failed
      ? 'rerun'
      : 'resume';

  return {
    statusLabel: completed ? 'Completed' : failed ? 'Needs attention' : 'In progress',
    statusTone: completed ? 'success' : failed ? 'error' : 'warn',
    badge,
    primaryAction,
    primaryActionLabel: completed
      ? (project.has_video ? 'Open video' : 'View summary')
      : failed
        ? 'Re-run'
        : 'Resume',
    secondaryText: completed
      ? project.has_video
        ? 'Final video ready'
        : 'Finished pipeline'
      : failed
        ? project.progress_desc || 'Pipeline stopped before completion'
      : progressPct > 0
        ? `${progressPct}% - ${project.progress_desc || 'Pipeline active'}`
        : project.progress_desc || 'Pipeline active',
    resumeLabel: completed
      ? project.has_video
        ? 'Open completed video from workspace'
        : 'Review completed output in workspace'
      : `Resume ${project.progress_desc || 'pipeline'}`,
  };
}
