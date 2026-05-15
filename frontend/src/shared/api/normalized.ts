import type {
  ClarificationRequest,
  DocumentMemory,
  DocumentSnapshot,
  GenerationRun,
  KnowledgeScope,
  KnowledgeScopeVersionSnapshot,
  OperationDetail,
  OperationStep,
  PublicationRevision,
  Solution,
  SolutionArchitectureEntity,
  SolutionArchitectureModel,
  SolutionArchitectureRelation,
  SolutionComponent,
  SolutionIntegration,
  SolutionRisk,
  SolutionSection,
  SolutionSectionAssessment,
  SolutionVerificationRunRef,
  TaskSnapshot,
  VerificationBasisDocument,
  VerificationFinding,
  VerificationProtocol,
  VerificationRun,
} from '../../types/api';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function normalizeArray<T>(value: T[] | null | undefined): T[] {
  return Array.isArray(value) ? value : [];
}

function normalizeRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function normalizeNumberMap(value: unknown): Record<string, number> {
  if (!isRecord(value)) return {};
  return Object.fromEntries(
    Object.entries(value)
      .filter(([, entry]) => typeof entry === 'number' && Number.isFinite(entry))
      .map(([key, entry]) => [key, entry]),
  ) as Record<string, number>;
}

function normalizePublicationHistory(value: unknown): PublicationRevision[] {
  return normalizeArray(value as PublicationRevision[] | undefined);
}

function normalizeKnowledgeScopeVersionSnapshot(value: unknown): KnowledgeScopeVersionSnapshot | null {
  if (!isRecord(value)) return null;
  return {
    ...(value as unknown as KnowledgeScopeVersionSnapshot),
    missing_required_packages: normalizeArray(value.missing_required_packages as string[] | undefined),
    basis_documents: normalizeArray(value.basis_documents as Array<Record<string, unknown>> | undefined),
  };
}

export function normalizeKnowledgeScope(value: unknown): KnowledgeScope | null {
  if (!isRecord(value)) return null;
  return {
    ...(value as unknown as Partial<KnowledgeScope>),
    mandatory_version: normalizeKnowledgeScopeVersionSnapshot(value.mandatory_version),
    selected_user_version: normalizeKnowledgeScopeVersionSnapshot(value.selected_user_version),
    effective_version_ids: normalizeArray(value.effective_version_ids as string[] | undefined),
    basis_documents: normalizeArray(value.basis_documents as Array<Record<string, unknown>> | undefined),
    document_scope: isRecord(value.document_scope)
      ? {
        ...(value.document_scope as Record<string, unknown>),
        selected_document_ids: normalizeArray(value.document_scope.selected_document_ids as string[] | undefined),
        effective_document_ids: normalizeArray(value.document_scope.effective_document_ids as string[] | undefined),
        selected_documents: normalizeArray(value.document_scope.selected_documents as Array<Record<string, unknown>> | undefined),
      }
      : null,
  } as KnowledgeScope;
}

export type NormalizedGenerationRun = Omit<GenerationRun, 'knowledge_scope' | 'diagnostics'> & {
  knowledge_scope: KnowledgeScope | null;
  diagnostics: Record<string, unknown> | null;
};

export function normalizeGenerationRun(value: GenerationRun): NormalizedGenerationRun {
  return {
    ...value,
    knowledge_scope: normalizeKnowledgeScope(value.knowledge_scope),
    diagnostics: isRecord(value.diagnostics) ? value.diagnostics : null,
  };
}

export type NormalizedVerificationRun = Omit<VerificationRun, 'knowledge_scope' | 'diagnostics'> & {
  knowledge_scope: KnowledgeScope | null;
  diagnostics: Record<string, unknown> | null;
};

export function normalizeVerificationRun(value: VerificationRun): NormalizedVerificationRun {
  return {
    ...value,
    knowledge_scope: normalizeKnowledgeScope(value.knowledge_scope),
    diagnostics: isRecord(value.diagnostics) ? value.diagnostics : null,
  };
}

export type NormalizedClarificationRequest = Omit<ClarificationRequest, 'answers'> & {
  answers: NonNullable<ClarificationRequest['answers']>;
};

function normalizeClarificationRequest(value: ClarificationRequest): NormalizedClarificationRequest {
  return {
    ...value,
    answers: normalizeArray(value.answers),
  };
}

export type NormalizedTaskSnapshot = Omit<TaskSnapshot, 'clarification_requests' | 'generation_runs'> & {
  clarification_requests: NormalizedClarificationRequest[];
  generation_runs: NonNullable<TaskSnapshot['generation_runs']>;
};

export function normalizeTaskSnapshot(value: TaskSnapshot): NormalizedTaskSnapshot {
  return {
    ...value,
    clarification_requests: normalizeArray(value.clarification_requests).map(normalizeClarificationRequest),
    generation_runs: normalizeArray(value.generation_runs),
  };
}

function normalizeSolutionSection(value: SolutionSection): SolutionSection {
  return {
    ...value,
    source_refs: normalizeArray(value.source_refs),
  };
}

function normalizeSectionAssessment(value: SolutionSectionAssessment): SolutionSectionAssessment {
  return {
    ...value,
    observed_signal_groups: normalizeArray(value.observed_signal_groups),
    missing_signal_groups: normalizeArray(value.missing_signal_groups),
    reasons: normalizeArray(value.reasons),
    allowed_archimate_elements: normalizeArray(value.allowed_archimate_elements),
  };
}

export type NormalizedSolutionArchitectureModel = Omit<SolutionArchitectureModel, 'entities' | 'relations' | 'section_summaries' | 'diagnostics'> & {
  entities: SolutionArchitectureEntity[];
  relations: SolutionArchitectureRelation[];
  section_summaries: Array<Record<string, unknown>>;
  diagnostics: Record<string, unknown>;
};

export function normalizeSolutionArchitectureModel(value?: SolutionArchitectureModel | null): NormalizedSolutionArchitectureModel {
  const record = isRecord(value) ? value : {};
  return {
    version: typeof record.version === 'string' ? record.version : 'sectioned-architecture-model.v1',
    entities: normalizeArray((record.entities as SolutionArchitectureEntity[] | undefined)),
    relations: normalizeArray((record.relations as SolutionArchitectureRelation[] | undefined)),
    section_summaries: normalizeArray((record.section_summaries as Array<Record<string, unknown>> | undefined)),
    diagnostics: normalizeRecord(record.diagnostics),
  };
}

export type NormalizedSolution = Omit<Solution, 'sections' | 'components' | 'integrations' | 'risks' | 'verification_runs' | 'section_assessments' | 'architecture_model' | 'explainability' | 'snapshot_summary' | 'publication_history' | 'knowledge_scope'> & {
  sections: SolutionSection[];
  components: SolutionComponent[];
  integrations: SolutionIntegration[];
  risks: SolutionRisk[];
  verification_runs: SolutionVerificationRunRef[];
  section_assessments: SolutionSectionAssessment[];
  architecture_model: NormalizedSolutionArchitectureModel;
  explainability: Record<string, unknown>;
  snapshot_summary: Record<string, unknown>;
  publication_history: PublicationRevision[];
  knowledge_scope: KnowledgeScope | null;
};

export function normalizeSolution(value: unknown): NormalizedSolution {
  const record = isRecord(value) ? value : {};
  return {
    ...(record as Solution),
    sections: normalizeArray(record.sections as SolutionSection[] | undefined).map(normalizeSolutionSection),
    components: normalizeArray(record.components as SolutionComponent[] | undefined).map((item) => ({
      ...item,
      interfaces: normalizeArray(item.interfaces),
    })),
    integrations: normalizeArray(record.integrations as SolutionIntegration[] | undefined),
    risks: normalizeArray(record.risks as SolutionRisk[] | undefined),
    verification_runs: normalizeArray(record.verification_runs as SolutionVerificationRunRef[] | undefined),
    section_assessments: normalizeArray(record.section_assessments as SolutionSectionAssessment[] | undefined).map(normalizeSectionAssessment),
    architecture_model: normalizeSolutionArchitectureModel(record.architecture_model as SolutionArchitectureModel | undefined),
    explainability: normalizeRecord(record.explainability),
    snapshot_summary: normalizeRecord(record.snapshot_summary),
    publication_history: normalizePublicationHistory(record.publication_history),
    knowledge_scope: normalizeKnowledgeScope(record.knowledge_scope),
  };
}

export type NormalizedVerificationProtocol = Omit<VerificationProtocol, 'findings' | 'basis_documents' | 'totals_by_status' | 'totals_by_severity' | 'diagnostics' | 'compliance_summary' | 'snapshot_summary' | 'publication_history' | 'knowledge_scope'> & {
  findings: VerificationFinding[];
  basis_documents: VerificationBasisDocument[];
  totals_by_status: Record<string, number>;
  totals_by_severity: Record<string, number>;
  diagnostics: Record<string, unknown> | null;
  compliance_summary: Record<string, unknown>;
  snapshot_summary: Record<string, unknown>;
  publication_history: PublicationRevision[];
  knowledge_scope: KnowledgeScope | null;
};

export function normalizeVerificationProtocol(value: unknown): NormalizedVerificationProtocol {
  const record = isRecord(value) ? value : {};
  return {
    ...(record as VerificationProtocol),
    findings: normalizeArray(record.findings as VerificationFinding[] | undefined),
    basis_documents: normalizeArray(record.basis_documents as VerificationBasisDocument[] | undefined),
    totals_by_status: normalizeNumberMap(record.totals_by_status),
    totals_by_severity: normalizeNumberMap(record.totals_by_severity),
    diagnostics: isRecord(record.diagnostics) ? record.diagnostics : null,
    compliance_summary: normalizeRecord(record.compliance_summary),
    snapshot_summary: normalizeRecord(record.snapshot_summary),
    publication_history: normalizePublicationHistory(record.publication_history),
    knowledge_scope: normalizeKnowledgeScope(record.knowledge_scope),
  };
}

export type NormalizedDocumentSnapshot = Omit<DocumentSnapshot, 'chunks'> & {
  chunks: NonNullable<DocumentSnapshot['chunks']>;
};

export function normalizeDocumentSnapshot(value: DocumentSnapshot): NormalizedDocumentSnapshot {
  return {
    ...value,
    chunks: normalizeArray(value.chunks),
  };
}

export type NormalizedDocumentMemory = Omit<DocumentMemory, 'counters' | 'items'> & {
  counters: Record<string, number>;
  items: NonNullable<DocumentMemory['items']>;
};

export function normalizeDocumentMemory(value: DocumentMemory): NormalizedDocumentMemory {
  return {
    ...value,
    counters: normalizeNumberMap(value.counters),
    items: normalizeArray(value.items),
  };
}

export type NormalizedOperationStep = Omit<OperationStep, 'payload'> & {
  payload: Record<string, unknown> | null;
};

function normalizeOperationStep(value: OperationStep): NormalizedOperationStep {
  return {
    ...value,
    payload: isRecord(value.payload) ? value.payload : null,
  };
}

export type NormalizedOperationDetail = Omit<OperationDetail, 'steps' | 'audit_events' | 'diagnostics'> & {
  steps: NormalizedOperationStep[];
  audit_events: NonNullable<OperationDetail['audit_events']>;
  diagnostics: Record<string, unknown> | null;
};

export function normalizeOperationDetail(value: OperationDetail): NormalizedOperationDetail {
  return {
    ...value,
    steps: normalizeArray(value.steps).map(normalizeOperationStep),
    audit_events: normalizeArray(value.audit_events),
    diagnostics: isRecord(value.diagnostics) ? value.diagnostics : null,
  };
}
