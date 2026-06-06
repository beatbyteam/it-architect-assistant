from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.enums import Severity


class ClarificationQuestionItem(BaseModel):
    question_code: str
    question_text: str
    required: bool = True


class ClarificationAnswerItemRequest(BaseModel):
    question_code: str
    answer_text: str = Field(min_length=1)


class ClarificationAnswerRequest(BaseModel):
    answers: list[ClarificationAnswerItemRequest] = Field(min_length=1)


class ClarificationAnswerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    clarification_answer_id: str
    question_code: str
    question_text: str | None = None
    answer_text: str
    sort_order: int
    created_at: datetime


class ClarificationRequestResponse(BaseModel):
    clarification_id: str
    task_id: str
    state: str
    question_items: list[ClarificationQuestionItem]
    created_at: datetime
    answered_at: datetime | None = None
    closed_at: datetime | None = None
    answers: list[ClarificationAnswerResponse] = Field(default_factory=list)


class TaskCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    raw_text: str = Field(min_length=1)
    metadata: dict[str, Any] | None = None
    save_as_draft: bool = False
    idempotency_key: str | None = Field(default=None, max_length=100)


class TaskUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    raw_text: str | None = Field(default=None, min_length=1)
    metadata: dict[str, Any] | None = None
    save_as_draft: bool | None = None


class TaskInputFileImportResponse(BaseModel):
    title: str
    text: str
    source_filename: str
    content_format: str
    parser_name: str
    section_count: int = 0


class TaskListItemResponse(BaseModel):
    task_id: str
    title: str | None = None
    state: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] | None = None
    latest_knowledge_version_id: str | None = None
    latest_generation_state: str | None = None
    latest_verification_state: str | None = None
    latest_protocol_id: str | None = None
    open_clarification_count: int = 0
    overdue_clarification_flag: bool = False


class SolutionRegistryItemResponse(BaseModel):
    solution_version_id: str
    task_id: str
    generation_run_id: str
    knowledge_version_id: str | None = None
    state: str
    solution_title: str
    published_at: datetime | None = None
    created_at: datetime | None = None
    verification_run_count: int = 0
    latest_verification_state: str | None = None
    latest_protocol_id: str | None = None


class VerificationProtocolRegistryItemResponse(BaseModel):
    protocol_id: str
    verification_run_id: str
    solution_version_id: str
    knowledge_version_id: str
    created_at: datetime
    state: str
    summary_status: str
    summary_text: str
    basis_document_count: int = 0
    finding_count: int = 0
    has_blockers: bool = False


class GenerationRunRefResponse(BaseModel):
    generation_run_id: str
    state: str
    knowledge_version_id: str
    started_at: datetime
    finished_at: datetime | None = None
    solution_version_id: str | None = None
    knowledge_scope: dict[str, Any] | None = None


class TaskSnapshotResponse(BaseModel):
    task_id: str
    title: str | None = None
    raw_text: str
    state: str
    created_at: datetime
    updated_at: datetime
    created_by: str
    metadata: dict[str, Any] | None = None
    clarification_requests: list[ClarificationRequestResponse] = Field(default_factory=list)
    generation_runs: list[GenerationRunRefResponse] = Field(default_factory=list)
    latest_knowledge_version_id: str | None = None
    latest_generation_state: str | None = None
    latest_verification_state: str | None = None
    latest_protocol_id: str | None = None
    open_clarification_count: int = 0
    overdue_clarification_flag: bool = False
    readiness_assessment: dict[str, Any] | None = None
    next_action_hint: str | None = None


class TaskGenerationRunCreateRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=100)
    correlation_id: str | None = Field(default=None, max_length=100)
    execute_inline: bool | None = None


class GenerationRunResponse(BaseModel):
    generation_run_id: str
    task_id: str
    knowledge_version_id: str
    state: str
    run_state: str | None = None
    current_stage: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    solution_version_id: str | None = None
    clarification_request: ClarificationRequestResponse | None = None
    knowledge_scope: dict[str, Any] | None = None
    diagnostics: dict[str, Any] | None = None


class GenerationRunAcceptedResponse(BaseModel):
    dispatch_type: Literal["generation_run"] = "generation_run"
    task_id: str
    task_state: str
    generation_run: GenerationRunResponse


class GenerationClarificationRequiredResponse(BaseModel):
    dispatch_type: Literal["needs_clarification"] = "needs_clarification"
    task_id: str
    task_state: str
    missing_inputs: list[str] = Field(default_factory=list)
    clarification_request: ClarificationRequestResponse | None = None


TaskGenerationDispatchResponse = (
    GenerationRunAcceptedResponse | GenerationClarificationRequiredResponse
)


class SolutionSectionSourceRefResponse(BaseModel):
    fragment_id: str | None = None
    document_id: str | None = None
    quote_text: str | None = None
    document_title: str | None = None
    version_ref: str | None = None
    role_code: str | None = None
    required_flag: bool = False
    source_location: str | None = None
    source_name: str | None = None
    document_type: str | None = None
    fragment_type: str | None = None
    sort_order: int


class SolutionSectionResponse(BaseModel):
    section_id: str
    section_code: str
    title: str
    body_markdown: str
    sort_order: int
    source_refs: list[SolutionSectionSourceRefResponse] = Field(default_factory=list)


class SolutionSectionAssessmentResponse(BaseModel):
    section_assessment_id: str
    section_code: str
    heading: str | None = None
    status: str
    score: float
    observed_signal_groups: list[str] = Field(default_factory=list)
    missing_signal_groups: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    allowed_archimate_elements: list[str] = Field(default_factory=list)
    fallback_applied: bool = False
    details: dict[str, Any] | None = None
    sort_order: int


class SolutionArchitectureEntityResponse(BaseModel):
    architecture_entity_id: str
    entity_key: str
    display_name: str
    source_kind: str | None = None
    section_code: str | None = None
    archimate_layer: str | None = None
    archimate_element_code: str | None = None
    archimate_element_title: str | None = None
    normalized_flag: bool
    confidence: float | None = None
    entity_metadata: dict[str, Any] | None = None
    sort_order: int


class SolutionArchitectureRelationResponse(BaseModel):
    architecture_relation_id: str
    relation_key: str
    relation_type: str
    source_entity_key: str | None = None
    target_entity_key: str | None = None
    section_code: str | None = None
    normalized_flag: bool
    confidence: float | None = None
    relation_metadata: dict[str, Any] | None = None
    sort_order: int


class SolutionArchitectureModelResponse(BaseModel):
    version: str = Field(default="sectioned-architecture-model.v1")
    entities: list[SolutionArchitectureEntityResponse] = Field(default_factory=list)
    relations: list[SolutionArchitectureRelationResponse] = Field(default_factory=list)
    section_summaries: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class SolutionComponentInterfaceResponse(BaseModel):
    interface_id: str
    interface_name: str
    protocol: str | None = None
    description: str | None = None
    sort_order: int


class SolutionComponentResponse(BaseModel):
    component_id: str
    component_name: str
    role_description: str
    technology_stack: str | None = None
    boundary_type: str | None = None
    external_flag: bool
    sort_order: int
    interfaces: list[SolutionComponentInterfaceResponse] = Field(default_factory=list)


class SolutionIntegrationResponse(BaseModel):
    integration_id: str
    interaction: str
    protocol: str | None = None
    rationale: str | None = None
    sort_order: int


class SolutionRiskResponse(BaseModel):
    risk_id: str
    title: str
    severity: str
    description: str
    mitigation: str | None = None
    sort_order: int


class SolutionListItemResponse(BaseModel):
    solution_list_item_id: str
    item_group: str
    item_text: str
    sort_order: int


class SolutionVerificationRunRefResponse(BaseModel):
    verification_run_id: str
    state: str
    knowledge_version_id: str
    started_at: datetime
    finished_at: datetime | None = None
    protocol_id: str | None = None


class PublicationRevisionResponse(BaseModel):
    published_artifact_id: str
    revision_no: int
    state: str
    published_at: datetime | None = None
    created_at: datetime | None = None
    superseded_at: datetime | None = None
    version_hash: str | None = None
    metadata: dict[str, Any] | None = None


class SnapshotSummaryResponse(BaseModel):
    snapshot_meta: dict[str, Any] = Field(default_factory=dict)
    knowledge_snapshot: dict[str, Any] | None = None
    prompt_contract: dict[str, Any] | None = None
    rulebook_version: str | None = None
    validation_scope: str | None = None
    retention_policy: dict[str, Any] | None = None


class SolutionResponse(BaseModel):
    solution_version_id: str
    generation_run_id: str
    task_id: str
    state: str
    published_at: datetime | None = None
    solution_title: str
    executive_summary: str
    sections: list[SolutionSectionResponse] = Field(default_factory=list)
    section_assessments: list[SolutionSectionAssessmentResponse] = Field(default_factory=list)
    architecture_model: SolutionArchitectureModelResponse | None = None
    components: list[SolutionComponentResponse] = Field(default_factory=list)
    integrations: list[SolutionIntegrationResponse] = Field(default_factory=list)
    list_items: list[SolutionListItemResponse] = Field(default_factory=list)
    risks: list[SolutionRiskResponse] = Field(default_factory=list)
    knowledge_version_id: str | None = None
    publication_artifact_id: str | None = None
    publication_revision_no: int | None = None
    artifact_state: str | None = None
    version_hash: str | None = None
    publication_history: list[PublicationRevisionResponse] = Field(default_factory=list)
    retention_policy: dict[str, Any] | None = None
    snapshot_summary: SnapshotSummaryResponse | dict[str, Any] | None = None
    knowledge_scope: dict[str, Any] | None = None
    verification_runs: list[SolutionVerificationRunRefResponse] = Field(default_factory=list)
    explainability: dict[str, Any] | None = None


class SolutionRenderedResponse(BaseModel):
    solution_version_id: str
    state: str
    published_at: datetime | None = None
    rendered_html: str | None = None
    publication_artifact_id: str | None = None
    publication_revision_no: int | None = None
    artifact_state: str | None = None
    version_hash: str | None = None
    publication_history: list[PublicationRevisionResponse] = Field(default_factory=list)
    retention_policy: dict[str, Any] | None = None
    snapshot_summary: SnapshotSummaryResponse | dict[str, Any] | None = None
    explainability: dict[str, Any] | None = None


class VerificationRunCreateRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=100)
    correlation_id: str | None = Field(default=None, max_length=100)
    knowledge_document_ids: list[str] = Field(default_factory=list)


class ExternalArchitectureSectionRequest(BaseModel):
    section_code: str = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=300)
    body_markdown: str = Field(min_length=1)


class ExternalArchitectureComponentRequest(BaseModel):
    component_name: str = Field(min_length=1, max_length=200)
    role_description: str = Field(min_length=1)
    technology_stack: str | None = None
    boundary_type: str | None = Field(default=None, max_length=100)
    external_flag: bool = False


class ExternalArchitectureIntegrationRequest(BaseModel):
    from_component: str = Field(min_length=1, max_length=200)
    to_component: str = Field(min_length=1, max_length=200)
    interaction: str = Field(min_length=1)
    protocol: str | None = Field(default=None, max_length=100)
    rationale: str | None = None


class ExternalArchitectureRiskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    severity: Severity = Severity.MAJOR
    description: str = Field(min_length=1)
    mitigation: str | None = None


class ExternalArchitectureCheckRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    architecture_text: str = Field(min_length=1)
    source_ref: str | None = Field(default=None, max_length=500)
    draft_task_id: str | None = None
    knowledge_document_ids: list[str] = Field(default_factory=list)
    sections: list[ExternalArchitectureSectionRequest] = Field(default_factory=list)
    components: list[ExternalArchitectureComponentRequest] = Field(default_factory=list)
    integrations: list[ExternalArchitectureIntegrationRequest] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    risks: list[ExternalArchitectureRiskRequest] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, max_length=100)
    correlation_id: str | None = Field(default=None, max_length=100)


class ExternalArchitectureCheckResponse(BaseModel):
    task_id: str
    solution_version_id: str
    generation_run_id: str
    publication_artifact_id: str | None = None
    verification_run_id: str
    protocol_id: str | None = None
    verification_state: str
    summary_status: str | None = None
    knowledge_version_id: str


class VerificationRunResponse(BaseModel):
    verification_run_id: str
    solution_version_id: str
    knowledge_version_id: str
    state: str
    run_state: str | None = None
    current_stage: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    protocol_id: str | None = None
    knowledge_scope: dict[str, Any] | None = None
    diagnostics: dict[str, Any] | None = None


class VerificationBasisDocumentResponse(BaseModel):
    protocol_basis_document_id: str | None = None
    document_id: str | None = None
    title: str
    role_code: str | None = None
    version_ref: str | None = None
    required_flag: bool = False
    sort_order: int


class VerificationFindingResponse(BaseModel):
    check_result_id: str
    rule_id: str | None = None
    rule_name: str | None = None
    rule_group: str | None = None
    severity: str
    status: str
    finding_text: str | None = None
    evidence: str | None = None
    related_section_ref: str | None = None
    sort_order: int


class VerificationProtocolViolationResponse(BaseModel):
    check_result_id: str
    rule_id: str | None = None
    rule_name: str | None = None
    rule_group: str | None = None
    severity: str
    status: str
    finding_text: str | None = None
    evidence: str | None = None
    related_section_ref: str | None = None
    sort_order: int


class VerificationProtocolResponse(BaseModel):
    protocol_id: str
    verification_run_id: str
    solution_version_id: str
    knowledge_version_id: str
    created_at: datetime
    state: str
    protocol_state: str | None = None
    summary_status: str
    summary_text: str
    totals_by_status: dict[str, int] = Field(default_factory=dict)
    totals_by_severity: dict[str, int] = Field(default_factory=dict)
    basis_documents: list[VerificationBasisDocumentResponse] = Field(default_factory=list)
    findings: list[VerificationFindingResponse] = Field(default_factory=list)
    grouped_findings: dict[str, list[VerificationFindingResponse]] = Field(default_factory=dict)
    compliance_summary: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] | None = None
    publication_artifact_id: str | None = None
    publication_revision_no: int | None = None
    artifact_state: str | None = None
    version_hash: str | None = None
    publication_history: list[PublicationRevisionResponse] = Field(default_factory=list)
    retention_policy: dict[str, Any] | None = None
    scope_snapshot: dict[str, Any] | None = None
    knowledge_scope: dict[str, Any] | None = None
    snapshot_summary: SnapshotSummaryResponse | dict[str, Any] | None = None


class VerificationProtocolRenderedResponse(BaseModel):
    protocol_id: str
    created_at: datetime
    summary_status: str
    protocol_state: str
    rendered_html: str
    publication_artifact_id: str | None = None
    publication_revision_no: int | None = None
    artifact_state: str | None = None
    version_hash: str | None = None
    publication_history: list[PublicationRevisionResponse] = Field(default_factory=list)
    retention_policy: dict[str, Any] | None = None
    snapshot_summary: SnapshotSummaryResponse | dict[str, Any] | None = None
    explainability: dict[str, Any] | None = None


class KnowledgeVersionResponse(BaseModel):
    knowledge_version_id: str
    version_code: str
    state: str
    created_at: datetime
    activated_at: datetime | None = None
    activated_by: str | None = None
    summary: dict[str, Any] | None = None
    knowledge_scope: dict[str, Any] | None = None


class SolutionSectionAssessmentsEnvelope(BaseModel):
    solution_version_id: str
    section_assessments: list[SolutionSectionAssessmentResponse] = Field(default_factory=list)


class SolutionArchitectureModelEnvelope(BaseModel):
    solution_version_id: str
    architecture_model: SolutionArchitectureModelResponse


class VerificationProtocolViolationsEnvelope(BaseModel):
    protocol_id: str
    violations: list[VerificationProtocolViolationResponse] = Field(default_factory=list)
