import type { TaskListItem } from '../../types/api';

const TERMINAL_GENERATION_STATES = new Set(['completed', 'failed', 'canceled']);

type TaskWithGenerationState = TaskListItem & {
  latest_generation_state?: string | null;
};

export const GENERATION_SELECTION_LOCK_REASON = 'Подготовка решения уже идет, поэтому базу знаний сейчас менять нельзя.';

export function isGenerationRunning(state?: string | null) {
  return Boolean(state && !TERMINAL_GENERATION_STATES.has(state));
}

export function hasRunningGeneration(tasks?: TaskListItem[] | null) {
  return (tasks ?? []).some((task) => isGenerationRunning((task as TaskWithGenerationState).latest_generation_state));
}
