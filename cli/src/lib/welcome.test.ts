import { describe, expect, it } from 'vitest';
import {
  composeConceptSubmission,
  createOnboardingState,
  getQualityEnterOutcome,
  getProjectViewModel,
  moveOnboardingFocus,
  nextWelcomeFocusArea,
  previousWelcomeFocusArea,
  validateConceptDraft,
} from './welcome.js';

describe('welcome helpers', () => {
  it('tracks submit readiness from the concept draft', () => {
    expect(createOnboardingState('high').readyToSubmit).toBe(false);
    expect(createOnboardingState('high', { conceptDraft: 'Bayes theorem' }).readyToSubmit).toBe(true);
  });

  it('validates empty concept drafts', () => {
    expect(validateConceptDraft('   ')).toContain('topic');
    expect(validateConceptDraft('Eigenvectors')).toBeNull();
  });

  it('composes the optional presentation goal into the submitted concept', () => {
    expect(composeConceptSubmission('Chain rule', 'intuition')).toBe('Chain rule\n\nPresentation goal: intuition');
    expect(composeConceptSubmission('Chain rule', '')).toBe('Chain rule');
  });

  it('requires a topic before the Step 3 Enter can submit', () => {
    expect(getQualityEnterOutcome('Chain rule').shouldSubmit).toBe(true);
    const emptyOutcome = getQualityEnterOutcome('   ');
    expect(emptyOutcome.shouldSubmit).toBe(false);
    expect(emptyOutcome.validationMessage).toContain('Add a topic first');
  });

  it('builds compact project summaries for in-progress work', () => {
    const vm = getProjectViewModel({
      dir: '/tmp/demo',
      folder: 'demo',
      concept: 'SVD',
      status: 'running',
      updated_at: '2026-04-05T12:00:00Z',
      progress_done: 2,
      progress_total: 4,
      progress_desc: 'render stage',
    });

    expect(vm.statusLabel).toBe('In progress');
    expect(vm.secondaryText).toContain('50%');
    expect(vm.resumeLabel).toContain('render stage');
  });

  it('cycles focus through the staged onboarding flow', () => {
    expect(nextWelcomeFocusArea('concept', true)).toBe('goal');
    expect(nextWelcomeFocusArea('goal', true)).toBe('quality');
    expect(nextWelcomeFocusArea('quality', true)).toBe('projects');
    expect(nextWelcomeFocusArea('quality', false)).toBe('concept');
    expect(previousWelcomeFocusArea('concept', true)).toBe('projects');
    expect(previousWelcomeFocusArea('concept', false)).toBe('quality');
  });

  it('keeps arrow transitions reliable and non-skipping', () => {
    expect(moveOnboardingFocus('concept', 'down', true)).toBe('goal');
    expect(moveOnboardingFocus('goal', 'down', true)).toBe('quality');
    expect(moveOnboardingFocus('quality', 'down', true)).toBe('projects');
    expect(moveOnboardingFocus('projects', 'down', true)).toBe('concept');

    // Critical safety invariant: Up on concept should never jump directly to projects.
    expect(moveOnboardingFocus('concept', 'up', true)).toBe('concept');
    expect(moveOnboardingFocus('concept', 'up', false)).toBe('concept');
  });

  it('describes completed projects as a workspace/open-video path', () => {
    const vm = getProjectViewModel({
      dir: '/tmp/completed',
      folder: 'completed',
      concept: 'Bayes theorem',
      status: 'completed',
      updated_at: '2026-04-05T12:00:00Z',
      progress_done: 5,
      progress_total: 5,
      progress_desc: 'done',
      has_video: true,
    });

    expect(vm.statusLabel).toBe('Completed');
    expect(vm.secondaryText).toContain('Final video ready');
    expect(vm.resumeLabel).toContain('Open completed video');
  });
});
