import { request, type RequestOptions } from './client';
import type { paths, SuccessJson } from '../../generated/openapi';
import {
  normalizeGenerationRun,
  normalizeSolution,
  normalizeSolutionArchitectureModel,
  normalizeTaskSnapshot,
} from './normalized';

type TasksListResponse = SuccessJson<paths['/tasks']['get']>;
type TaskResponse = SuccessJson<paths['/tasks/{task_id}']['get']>;
type TaskMutationResponse = SuccessJson<paths['/tasks/{task_id}']['patch']>;
type ClarificationAnswerResponse = SuccessJson<paths['/tasks/{task_id}/clarifications/{clarification_id}/answers']['post']>;
type GenerationDispatchResponse = SuccessJson<paths['/tasks/{task_id}/generation-runs']['post']>;
type GenerationRunResponse = SuccessJson<paths['/generation-runs/{generation_run_id}']['get']>;
type SolutionResponse = SuccessJson<paths['/solutions/{solution_version_id}']['get']>;
type SolutionsRegistryResponse = SuccessJson<paths['/solutions']['get']>;
type RenderedSolutionResponse = SuccessJson<paths['/solutions/{solution_version_id}/rendered']['get']>;
type SolutionModelResponse = SuccessJson<paths['/solutions/{solution_version_id}/model']['get']>;
type SolutionSectionAssessmentsResponse = SuccessJson<paths['/solutions/{solution_version_id}/section-assessments']['get']>;

export function getTasks(filters?: { state?: string; search?: string; limit?: number }, options?: RequestOptions) {
  return request<TasksListResponse>('/tasks', options, filters);
}

export async function getTask(taskId: string, options?: RequestOptions) {
  return normalizeTaskSnapshot(await request<TaskResponse>(`/tasks/${taskId}`, options));
}

export async function createTask(payload: { title?: string | null; raw_text: string; metadata?: Record<string, unknown> | null; save_as_draft?: boolean; idempotency_key?: string }) {
  return normalizeTaskSnapshot(await request<TaskResponse>('/tasks', { method: 'POST', body: JSON.stringify(payload) }));
}

export async function updateTask(taskId: string, payload: { title?: string | null; raw_text?: string | null; metadata?: Record<string, unknown> | null; save_as_draft?: boolean }) {
  return normalizeTaskSnapshot(await request<TaskMutationResponse>(`/tasks/${taskId}`, { method: 'PATCH', body: JSON.stringify(payload) }));
}

export function answerClarification(taskId: string, clarificationId: string, answers: Array<{ question_code: string; answer_text: string }>) {
  return request<ClarificationAnswerResponse>(`/tasks/${taskId}/clarifications/${clarificationId}/answers`, {
    method: 'POST',
    body: JSON.stringify({ answers }),
  });
}

export async function startGenerationRun(taskId: string, payload?: { idempotency_key?: string; correlation_id?: string; execute_inline?: boolean }) {
  const response = await request<GenerationDispatchResponse>(`/tasks/${taskId}/generation-runs`, { method: 'POST', body: JSON.stringify(payload ?? {}) });
  if (response.dispatch_type === 'generation_run') {
    return {
      ...response,
      generation_run: normalizeGenerationRun(response.generation_run),
    } as GenerationDispatchResponse;
  }
  return response;
}

export async function getGenerationRun(generationRunId: string, options?: RequestOptions) {
  return normalizeGenerationRun(await request<GenerationRunResponse>(`/generation-runs/${generationRunId}`, options));
}

export async function cancelGenerationRun(generationRunId: string) {
  return normalizeGenerationRun(await request<GenerationRunResponse>(`/generation-runs/${generationRunId}/cancel`, {
    method: 'POST',
    body: '{}',
  }));
}

export async function getSolution(solutionVersionId: string, options?: RequestOptions) {
  return normalizeSolution(await request<SolutionResponse>(`/solutions/${solutionVersionId}`, options));
}

export function getSolutionsRegistry(filters?: { task_id?: string; state?: string; knowledge_version_id?: string; limit?: number }, options?: RequestOptions) {
  return request<SolutionsRegistryResponse>('/solutions', options, filters);
}

export function getSolutionRendered(solutionVersionId: string, options?: RequestOptions) {
  return request<RenderedSolutionResponse>(`/solutions/${solutionVersionId}/rendered`, options);
}

export async function getSolutionModel(solutionVersionId: string, options?: RequestOptions) {
  const response = await request<SolutionModelResponse>(`/solutions/${solutionVersionId}/model`, options);
  return {
    ...response,
    architecture_model: normalizeSolutionArchitectureModel(response.architecture_model),
  } as SolutionModelResponse;
}

export async function getSolutionSectionAssessments(solutionVersionId: string, options?: RequestOptions) {
  const response = await request<SolutionSectionAssessmentsResponse>(`/solutions/${solutionVersionId}/section-assessments`, options);
  return {
    ...response,
    section_assessments: Array.isArray(response.section_assessments) ? response.section_assessments : [],
  } as SolutionSectionAssessmentsResponse;
}
