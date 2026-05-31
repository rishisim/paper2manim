import type {
  PreferencesSummaryItem,
  QuestionDef,
  QuestionOptionDef,
  QuestionVisibility,
  QuestionVisibilityRule,
  QuestionnaireStage,
} from './types.js';

export function normalizeQuestionOption(option: string | QuestionOptionDef): QuestionOptionDef {
  if (typeof option === 'string') {
    return { value: option, label: option };
  }
  return option;
}

export function getQuestionOptions(question: QuestionDef): QuestionOptionDef[] {
  return question.options.map(normalizeQuestionOption);
}

function matchesVisibilityRule(rule: QuestionVisibilityRule, answers: Record<string, string>): boolean {
  return rule.values.includes(answers[rule.questionId] ?? '');
}

export function isQuestionVisible(question: QuestionDef, answers: Record<string, string>): boolean {
  const visibility: QuestionVisibility | undefined = question.showWhen;
  if (!visibility) return true;

  if (visibility.allOf && visibility.allOf.some(rule => !matchesVisibilityRule(rule, answers))) {
    return false;
  }
  if (visibility.anyOf && !visibility.anyOf.some(rule => matchesVisibilityRule(rule, answers))) {
    return false;
  }
  return true;
}

export function getVisibleQuestions(questions: QuestionDef[], answers: Record<string, string>): QuestionDef[] {
  return questions.filter(question => isQuestionVisible(question, answers));
}

export function pruneHiddenAnswers(
  questions: QuestionDef[],
  answers: Record<string, string>,
): Record<string, string> {
  const visibleIds = new Set(getVisibleQuestions(questions, answers).map(question => question.id));
  return Object.fromEntries(
    Object.entries(answers).filter(([id]) => visibleIds.has(id)),
  );
}

export function withResolvedDefaults(
  questions: QuestionDef[],
  initialAnswers: Record<string, string> = {},
): Record<string, string> {
  const answers = { ...initialAnswers };

  for (let i = 0; i < questions.length + 2; i++) {
    const pruned = pruneHiddenAnswers(questions, answers);
    for (const key of Object.keys(answers)) {
      if (!(key in pruned)) delete answers[key];
    }
    let changed = false;
    for (const question of getVisibleQuestions(questions, answers)) {
      if (answers[question.id]) continue;
      const options = getQuestionOptions(question);
      const fallback = question.default ?? options[0]?.value;
      if (fallback) {
        answers[question.id] = fallback;
        changed = true;
      }
    }
    if (!changed) break;
  }

  return answers;
}

export function getQuestionCursor(
  question: QuestionDef,
  answers: Record<string, string>,
  cursorByQuestion: Record<string, number>,
): number {
  const options = getQuestionOptions(question);
  const answerIdx = options.findIndex(opt => opt.value === answers[question.id]);
  const storedCursor = cursorByQuestion[question.id];
  if (storedCursor !== undefined) return Math.max(0, Math.min(options.length - 1, storedCursor));
  if (answerIdx >= 0) return answerIdx;
  if (question.default) {
    const defaultIdx = options.findIndex(opt => opt.value === question.default);
    if (defaultIdx >= 0) return defaultIdx;
  }
  return 0;
}

export function getQuestionAnswerLabel(question: QuestionDef, answer: string | undefined): string {
  if (!answer) return 'Not set';
  const option = getQuestionOptions(question).find(opt => opt.value === answer);
  if (!option) return answer;
  return option.summaryLabel ?? option.label;
}

export function buildReviewItems(
  questions: QuestionDef[],
  answers: Record<string, string>,
): PreferencesSummaryItem[] {
  return getVisibleQuestions(questions, answers).map((question) => ({
    id: question.id,
    label: question.summaryLabel ?? question.question.replace(/:\s*$/, ''),
    value: getQuestionAnswerLabel(question, answers[question.id]),
    stage: question.stage,
  }));
}

export function getQuestionStage(question: QuestionDef): QuestionnaireStage {
  return question.stage ?? 'goal';
}
