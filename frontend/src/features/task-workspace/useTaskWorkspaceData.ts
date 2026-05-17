import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  answerClarification,
  cancelGenerationRun,
  getGenerationRun,
  getSolution,
  getSolutionRendered,
  getTask,
  startGenerationRun,
  updateTask,
} from '../../shared/api/tasks';
import { getActiveKnowledgeVersion } from '../../shared/api/knowledge';
import { queryKeys } from '../../shared/api/queryKeys';
import { getVerificationProtocol, getVerificationRun, startVerificationRun } from '../../shared/api/verification';
import type {
  NormalizedClarificationRequest,
  NormalizedGenerationRun,
  NormalizedTaskSnapshot,
  NormalizedVerificationRun,
} from '../../shared/api/normalized';
import { usePollingQuery } from '../../shared/hooks/usePollingQuery';
import { groupTitleFromRule, readinessLabel } from '../../shared/lib/format';
import type {
  GenerationDispatch,
  VerificationFinding,
} from '../../types/api';
import { diagnosticsOperationId, isTerminal } from './lib';

export function useTaskWorkspaceData(taskId: string) {
  const queryClient = useQueryClient();
  const [answerDrafts, setAnswerDrafts] = useState<Record<string, string>>({});
  const [generationRunId, setGenerationRunId] = useState<string | null>(null);
  const [verificationRunId, setVerificationRunId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState('');
  const [draftText, setDraftText] = useState('');
  const [draftSaveMode, setDraftSaveMode] = useState<'draft' | 'submit' | null>(null);
  const [generationDispatchNotice, setGenerationDispatchNotice] = useState<GenerationDispatch | null>(null);
  const lastServerDraftRef = useRef<{ taskId: string; title: string; text: string } | null>(null);

  const taskQuery = useQuery({
    queryKey: queryKeys.task(taskId),
    queryFn: ({ signal }) => getTask(taskId, { signal }),
    enabled: Boolean(taskId),
  });
  const activeVersionQuery = useQuery({
    queryKey: queryKeys.taskActiveVersion(taskId),
    queryFn: ({ signal }) => getActiveKnowledgeVersion({ signal }),
    staleTime: 30_000,
    retry: false,
  });

  useEffect(() => {
    if (!taskQuery.data) return;
    const nextServerDraft = {
      taskId: taskQuery.data.task_id,
      title: taskQuery.data.title ?? '',
      text: taskQuery.data.raw_text ?? '',
    };
    const previousServerDraft = lastServerDraftRef.current;
    const shouldHydrate = !previousServerDraft
      || previousServerDraft.taskId !== nextServerDraft.taskId
      || (draftTitle === previousServerDraft.title && draftText === previousServerDraft.text);

    lastServerDraftRef.current = nextServerDraft;
    if (shouldHydrate) {
      setDraftTitle(nextServerDraft.title);
      setDraftText(nextServerDraft.text);
    }
  }, [draftText, draftTitle, taskQuery.data]);

  const latestGenerationRef = useMemo(() => taskQuery.data?.generation_runs[0] ?? null, [taskQuery.data]);
  const effectiveGenerationRunId = generationRunId ?? latestGenerationRef?.generation_run_id ?? null;
  const generationRunQuery = usePollingQuery<NormalizedGenerationRun>(
    effectiveGenerationRunId ? queryKeys.generationRun(effectiveGenerationRunId) : ['generation-run', null],
    (signal) => getGenerationRun(effectiveGenerationRunId as string, { signal }),
    Boolean(effectiveGenerationRunId),
    (data) => isTerminal(data.state),
  );

  const solutionId = generationRunQuery.data?.solution_version_id ?? latestGenerationRef?.solution_version_id ?? null;
  const solutionQuery = useQuery({
    queryKey: solutionId ? queryKeys.solution(solutionId) : ['solution', null],
    queryFn: ({ signal }) => getSolution(solutionId as string, { signal }),
    enabled: Boolean(solutionId),
  });
  const renderedQuery = useQuery({
    queryKey: solutionId ? queryKeys.solutionRendered(solutionId) : ['solution-rendered', null],
    queryFn: ({ signal }) => getSolutionRendered(solutionId as string, { signal }),
    enabled: Boolean(solutionId),
  });

  const latestVerificationRef = useMemo(() => solutionQuery.data?.verification_runs[0] ?? null, [solutionQuery.data]);
  const effectiveVerificationRunId = verificationRunId ?? latestVerificationRef?.verification_run_id ?? null;
  const verificationRunQuery = usePollingQuery<NormalizedVerificationRun>(
    effectiveVerificationRunId ? queryKeys.verificationRun(effectiveVerificationRunId) : ['verification-run', null],
    (signal) => getVerificationRun(effectiveVerificationRunId as string, { signal }),
    Boolean(effectiveVerificationRunId),
    (data) => isTerminal(data.state),
  );

  const protocolId = verificationRunQuery.data?.protocol_id ?? latestVerificationRef?.protocol_id ?? null;
  const protocolQuery = useQuery({
    queryKey: protocolId ? queryKeys.protocol(protocolId) : ['protocol', null],
    queryFn: ({ signal }) => getVerificationProtocol(protocolId as string, { signal }),
    enabled: Boolean(protocolId),
  });

  useEffect(() => {
    if (generationRunQuery.data && isTerminal(generationRunQuery.data.state)) {
      queryClient.invalidateQueries({ queryKey: queryKeys.task(taskId) });
      if (generationRunQuery.data.solution_version_id) {
        queryClient.invalidateQueries({ queryKey: queryKeys.solution(generationRunQuery.data.solution_version_id) });
      }
    }
  }, [generationRunQuery.data, queryClient, taskId]);

  useEffect(() => {
    if (verificationRunQuery.data && isTerminal(verificationRunQuery.data.state)) {
      if (solutionId) queryClient.invalidateQueries({ queryKey: queryKeys.solution(solutionId) });
      if (verificationRunQuery.data.protocol_id) {
        queryClient.invalidateQueries({ queryKey: queryKeys.protocol(verificationRunQuery.data.protocol_id) });
      }
    }
  }, [verificationRunQuery.data, queryClient, solutionId]);

  const answerMutation = useMutation({
    mutationFn: ({ clarificationId, answers }: { clarificationId: string; answers: Array<{ question_code: string; answer_text: string }> }) => answerClarification(taskId, clarificationId, answers),
    onSuccess: (_updatedTask, variables) => {
      setAnswerDrafts((current) => {
        const next = { ...current };
        for (const answer of variables.answers) {
          delete next[answer.question_code];
        }
        return next;
      });
      queryClient.invalidateQueries({ queryKey: queryKeys.task(taskId) });
    },
  });

  const saveDraftMutation = useMutation({
    mutationFn: (mode: 'draft' | 'submit') => updateTask(taskId, { title: draftTitle, raw_text: draftText, save_as_draft: mode === 'draft' }),
    onMutate: (mode) => setDraftSaveMode(mode),
    onSuccess: (updatedTask) => {
      lastServerDraftRef.current = {
        taskId: updatedTask.task_id,
        title: updatedTask.title ?? '',
        text: updatedTask.raw_text ?? '',
      };
      queryClient.setQueryData(queryKeys.task(taskId), updatedTask);
      queryClient.invalidateQueries({ queryKey: queryKeys.task(taskId) });
    },
    onSettled: () => setDraftSaveMode(null),
  });

  const generationMutation = useMutation({
    mutationFn: () => startGenerationRun(taskId, { execute_inline: false }),
    onSuccess: (dispatch: GenerationDispatch) => {
      setGenerationDispatchNotice(dispatch);
      if (dispatch.dispatch_type === 'generation_run') {
        setGenerationRunId(dispatch.generation_run.generation_run_id);
      }
      queryClient.invalidateQueries({ queryKey: queryKeys.task(taskId) });
    },
  });

  const cancelGenerationMutation = useMutation({
    mutationFn: () => {
      if (!effectiveGenerationRunId) {
        throw new Error('Нет активного запуска подготовки решения для отмены.');
      }
      return cancelGenerationRun(effectiveGenerationRunId);
    },
    onSuccess: (run) => {
      setGenerationRunId(run.generation_run_id);
      queryClient.setQueryData(queryKeys.generationRun(run.generation_run_id), run);
      queryClient.invalidateQueries({ queryKey: queryKeys.generationRun(run.generation_run_id) });
      queryClient.invalidateQueries({ queryKey: queryKeys.task(taskId) });
    },
  });

  const verificationMutation = useMutation({
    mutationFn: () => startVerificationRun(solutionId as string),
    onSuccess: (run) => {
      setVerificationRunId(run.verification_run_id);
      if (solutionId) queryClient.invalidateQueries({ queryKey: queryKeys.solution(solutionId) });
    },
  });

  const task = taskQuery.data ?? null;
  const openClarifications = task?.clarification_requests.filter((item: NormalizedClarificationRequest) => item.state === 'open') ?? [];
  const clarificationHistory = task?.clarification_requests.filter((item: NormalizedClarificationRequest) => item.state === 'answered' || item.state === 'closed' || item.state === 'canceled') ?? [];
  const groupedFindings: Record<string, VerificationFinding[]> = {};
  (protocolQuery.data?.findings ?? []).forEach((finding: VerificationFinding) => {
    const key = groupTitleFromRule(finding.rule_name ?? finding.rule_id);
    groupedFindings[key] = groupedFindings[key] ?? [];
    groupedFindings[key].push(finding);
  });

  const generationOperationId = diagnosticsOperationId(generationRunQuery.data?.diagnostics ?? null, effectiveGenerationRunId);
  const verificationOperationId = diagnosticsOperationId(verificationRunQuery.data?.diagnostics ?? null, effectiveVerificationRunId);
  const readinessAssessment = (task?.readiness_assessment ?? {}) as Record<string, unknown>;
  const readinessMissingInputs = Array.isArray(readinessAssessment.missing_inputs)
    ? readinessAssessment.missing_inputs.map((item) => readinessLabel(String(item)))
    : [];

  return {
    answerDrafts,
    setAnswerDrafts,
    draftTitle,
    setDraftTitle,
    draftText,
    setDraftText,
    draftSaveMode,
    generationDispatchNotice,
    taskQuery,
    activeVersionQuery,
    generationRunQuery,
    solutionQuery,
    renderedQuery,
    verificationRunQuery,
    protocolQuery,
    answerMutation,
    saveDraftMutation,
    generationMutation,
    cancelGenerationMutation,
    verificationMutation,
    task: task as NormalizedTaskSnapshot | null,
    openClarifications,
    clarificationHistory,
    groupedFindings,
    latestGenerationRef,
    latestVerificationRef,
    solutionId,
    protocolId,
    generationOperationId,
    verificationOperationId,
    readinessMissingInputs,
  };
}
