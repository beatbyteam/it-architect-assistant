import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  getSolution,
  getSolutionModel,
  getSolutionRendered,
  getSolutionSectionAssessments,
} from '../../shared/api/tasks';
import { queryKeys } from '../../shared/api/queryKeys';
import { getVerificationRun, startVerificationRun } from '../../shared/api/verification';
import { usePollingQuery } from '../../shared/hooks/usePollingQuery';
import {
  normalizeSolution,
  normalizeSolutionArchitectureModel,
} from '../../shared/api/normalized';
import type {
  NormalizedSolution,
  NormalizedVerificationRun,
} from '../../shared/api/normalized';
import type {
  PublicationRevision,
  SolutionArchitectureEntity,
  SolutionSectionAssessment,
} from '../../types/api';
import { diagnosticsOperationId, isTerminal, normalizeArray } from './lib';

export function useSolutionPageData(solutionId: string) {
  const [copied, setCopied] = useState(false);
  const [verificationRunId, setVerificationRunId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const solutionQuery = useQuery({
    queryKey: queryKeys.solution(solutionId),
    queryFn: ({ signal }) => getSolution(solutionId, { signal }),
    enabled: Boolean(solutionId),
  });

  const solution = solutionQuery.data ? normalizeSolution(solutionQuery.data as NormalizedSolution) : null;
  const hasEmbeddedModel = solution
    ? (
      solution.architecture_model.entities.length > 0
      || solution.architecture_model.relations.length > 0
      || solution.architecture_model.section_summaries.length > 0
      || Object.keys(solution.architecture_model.diagnostics).length > 0
    )
    : false;
  const hasEmbeddedAssessments = solution ? solution.section_assessments.length > 0 : false;

  const renderedQuery = useQuery({
    queryKey: queryKeys.solutionRendered(solutionId),
    queryFn: ({ signal }) => getSolutionRendered(solutionId, { signal }),
    enabled: Boolean(solutionId),
  });
  const modelQuery = useQuery({
    queryKey: queryKeys.solutionModel(solutionId),
    queryFn: ({ signal }) => getSolutionModel(solutionId, { signal }),
    enabled: Boolean(solutionId) && Boolean(solution) && !hasEmbeddedModel,
  });
  const sectionAssessmentsQuery = useQuery({
    queryKey: queryKeys.solutionSectionAssessments(solutionId),
    queryFn: ({ signal }) => getSolutionSectionAssessments(solutionId, { signal }),
    enabled: Boolean(solutionId) && Boolean(solution) && !hasEmbeddedAssessments,
  });

  const latestVerificationRunId = useMemo(
    () => verificationRunId ?? solution?.verification_runs[0]?.verification_run_id ?? null,
    [solution, verificationRunId],
  );
  const verificationRunQuery = usePollingQuery<NormalizedVerificationRun>(
    latestVerificationRunId ? queryKeys.verificationRun(latestVerificationRunId) : ['verification-run', null],
    (signal) => getVerificationRun(latestVerificationRunId as string, { signal }),
    Boolean(latestVerificationRunId),
    (data) => isTerminal(data.state),
  );

  const verificationOperationId = diagnosticsOperationId(verificationRunQuery.data?.diagnostics ?? null);
  const solutionExplainability = (solution?.explainability ?? renderedQuery.data?.explainability ?? {}) as Record<string, unknown>;
  const retrievalSummary = (solutionExplainability.retrieval_summary as Record<string, unknown> | undefined) ?? {};
  const basisDocuments = normalizeArray(solutionExplainability.basis_documents as Array<Record<string, unknown>> | undefined);
  const sectionCoverage = normalizeArray(solutionExplainability.section_coverage as Array<Record<string, unknown>> | undefined);
  const evidenceCoverage = (solutionExplainability.evidence_coverage as Record<string, unknown> | undefined) ?? {};
  const guidanceSummary = (retrievalSummary.guidance_summary_by_section as Record<string, Record<string, unknown>> | undefined) ?? {};
  const publicationHistory = ((solution?.publication_history ?? renderedQuery.data?.publication_history ?? []) as PublicationRevision[]);
  const snapshotSummary = (solution?.snapshot_summary ?? renderedQuery.data?.snapshot_summary ?? {}) as Record<string, unknown>;
  const knowledgeScope = solution?.knowledge_scope ?? verificationRunQuery.data?.knowledge_scope ?? null;

  const sectionAssessments = ((sectionAssessmentsQuery.data?.section_assessments ?? solution?.section_assessments ?? []) as SolutionSectionAssessment[]);
  const architectureModel = normalizeSolutionArchitectureModel(modelQuery.data?.architecture_model ?? solution?.architecture_model);

  const sectionAssessmentMap = new Map<string, SolutionSectionAssessment>(sectionAssessments.map((item: SolutionSectionAssessment) => [item.section_code, item]));
  const readyCount = sectionAssessments.filter((item: SolutionSectionAssessment) => item.status === 'ready').length;
  const partialCount = sectionAssessments.filter((item: SolutionSectionAssessment) => item.status === 'partial').length;
  const insufficientCount = sectionAssessments.filter((item: SolutionSectionAssessment) => item.status === 'insufficient').length;
  const normalizedEntityCount = architectureModel.entities.filter((item: SolutionArchitectureEntity) => item.normalized_flag).length;
  const relationCount = architectureModel.relations.length;

  const entitiesByLayer = useMemo(() => {
    const groups: Record<string, SolutionArchitectureEntity[]> = {};
    architectureModel.entities.forEach((item: SolutionArchitectureEntity) => {
      const key = item.archimate_layer ?? item.section_code ?? 'other';
      groups[key] = groups[key] ?? [];
      groups[key].push(item);
    });
    return groups;
  }, [architectureModel.entities]);

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  const verificationMutation = useMutation({
    mutationFn: (payload?: { knowledge_document_ids?: string[] }) => startVerificationRun(solutionId, payload),
    onSuccess: async (run) => {
      setVerificationRunId(run.verification_run_id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.solution(solutionId) }),
        queryClient.invalidateQueries({ queryKey: ['registry-solutions'] }),
        queryClient.invalidateQueries({ queryKey: ['registry-protocols'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard-solutions'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard-protocols'] }),
      ]);
    },
  });

  return {
    copied,
    solutionQuery,
    renderedQuery,
    modelQuery,
    sectionAssessmentsQuery,
    verificationMutation,
    verificationRunQuery,
    solution: solution as NormalizedSolution | null,
    verificationOperationId,
    retrievalSummary,
    basisDocuments,
    sectionCoverage,
    evidenceCoverage,
    guidanceSummary,
    publicationHistory,
    snapshotSummary,
    knowledgeScope,
    sectionAssessments,
    architectureModel,
    sectionAssessmentMap,
    readyCount,
    partialCount,
    insufficientCount,
    normalizedEntityCount,
    relationCount,
    entitiesByLayer,
    copyLink,
  };
}
