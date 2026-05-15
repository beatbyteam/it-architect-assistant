from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.enums import AuditSeverity


class OperationJournalItemResponse(BaseModel):
    operation_kind: str
    operation_id: UUID | str
    status: str
    current_stage: str | None = None
    correlation_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    initiator_user_id: UUID | str | None = None
    actor_label: str | None = None
    duration_sec: int | None = None
    error_code: str | None = None
    entity_refs: dict[str, str | None] = Field(default_factory=dict)
    diagnostics: dict[str, Any] | None = None
    last_problem_step: str | None = None


class OperationMetricsCounterResponse(BaseModel):
    count: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)


class QualityMetricSummaryResponse(BaseModel):
    count: int = 0
    average_groundedness_score: float | None = None
    average_citation_coverage: float | None = None
    fallback_rate: float | None = None
    retrieval_empty_rate: float | None = None
    average_check_count: float | None = None


class VersionDistributionResponse(BaseModel):
    count: int = 0
    by_value: dict[str, int] = Field(default_factory=dict)


class PipelineObservabilitySummaryResponse(BaseModel):
    count: int = 0
    average_total_stage_duration_sec: float | None = None
    average_runtime_sec: float | None = None
    average_stage_count: float | None = None
    average_failed_stage_count: float | None = None
    longest_stage_distribution: dict[str, int] = Field(default_factory=dict)


class PipelineObservabilityDashboardResponse(BaseModel):
    knowledge_updates: PipelineObservabilitySummaryResponse = Field(
        default_factory=PipelineObservabilitySummaryResponse
    )
    generation_runs: PipelineObservabilitySummaryResponse = Field(
        default_factory=PipelineObservabilitySummaryResponse
    )
    verification_runs: PipelineObservabilitySummaryResponse = Field(
        default_factory=PipelineObservabilitySummaryResponse
    )


class DataLlmDashboardResponse(BaseModel):
    generation_quality: QualityMetricSummaryResponse = Field(
        default_factory=QualityMetricSummaryResponse
    )
    verification_quality: QualityMetricSummaryResponse = Field(
        default_factory=QualityMetricSummaryResponse
    )
    retrieval_policy_versions: VersionDistributionResponse = Field(
        default_factory=VersionDistributionResponse
    )
    embedding_model_versions: VersionDistributionResponse = Field(
        default_factory=VersionDistributionResponse
    )
    chunking_policy_versions: VersionDistributionResponse = Field(
        default_factory=VersionDistributionResponse
    )
    pipeline_observability: PipelineObservabilityDashboardResponse = Field(
        default_factory=PipelineObservabilityDashboardResponse
    )


class OperationMetricsResponse(BaseModel):
    generated_at: datetime
    knowledge_updates: OperationMetricsCounterResponse
    generation_runs: OperationMetricsCounterResponse
    verification_runs: OperationMetricsCounterResponse
    audit_events: OperationMetricsCounterResponse
    data_llm_dashboard: DataLlmDashboardResponse = Field(default_factory=DataLlmDashboardResponse)


class OperationStepResponse(BaseModel):
    code: str
    title: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    detail: str | None = None
    error_code: str | None = None
    payload: dict | None = None


class OperationDetailResponse(OperationJournalItemResponse):
    summary_text: str | None = None
    steps: list[OperationStepResponse] = Field(default_factory=list)
    audit_events: list[AuditEventResponse] = Field(default_factory=list)


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    audit_event_id: UUID | str
    event_time: datetime
    event_type: str
    actor_user_id: UUID | str | None
    target_type: str
    target_id: UUID | str
    severity: AuditSeverity
    message: str
    payload: dict | None = None
    correlation_id: str | None = None


OperationDetailResponse.model_rebuild()
