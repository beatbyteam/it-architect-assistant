from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.enums import (
    Criticality,
    DocumentDeltaKind,
    DocumentType,
    ExtractedKnowledgeType,
    ExtractionQualityStatus,
    KnowledgeBaseKind,
    KnowledgeBaseStatus,
    KnowledgeUpdateStatus,
    KnowledgeVersionStatus,
    SourceDocumentStatus,
    SourceScope,
    SourceStatus,
    SourceSyncMode,
    SourceType,
    UpdateRunType,
)
from app.domain.services.knowledge.policies import (
    normalize_refresh_policy as _normalize_refresh_policy,
)


def _normalize_source_type_alias(value: SourceType | str) -> SourceType | str:
    if isinstance(value, SourceType):
        return value
    lowered = str(value).strip().lower()
    alias_map = {
        "url": SourceType.URL_LIST,
        "url_list": SourceType.URL_LIST,
        "repository": SourceType.REPOSITORY,
        "local_folder": SourceType.REPOSITORY,
        "manual_upload": SourceType.MANUAL_UPLOAD,
    }
    return alias_map.get(lowered, value)


def _normalize_criticality_alias(
    value: Criticality | str | bool | None,
) -> Criticality | str | None:
    if value is None or isinstance(value, Criticality):
        return value
    if isinstance(value, bool):
        return Criticality.REQUIRED if value else Criticality.OPTIONAL
    lowered = str(value).strip().lower()
    alias_map = {
        "true": Criticality.REQUIRED,
        "false": Criticality.OPTIONAL,
        "required": Criticality.REQUIRED,
        "optional": Criticality.OPTIONAL,
        "mandatory": Criticality.REQUIRED,
        "optional_flag": Criticality.OPTIONAL,
    }
    return alias_map.get(lowered, value)


def _normalize_str_id_list(values: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values or []:
        value = str(item).strip()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def _derive_source_name(name: str | None, base_uri: str | None) -> str:
    normalized_name = (name or "").strip()
    if normalized_name:
        return normalized_name[:200]
    normalized_uri = (base_uri or "").strip()
    if normalized_uri:
        parsed = urlparse(normalized_uri)
        if parsed.netloc:
            path = unquote(parsed.path or "").strip("/")
            candidate = f"{parsed.netloc}/{path}" if path else parsed.netloc
        else:
            candidate = unquote(parsed.path or normalized_uri).rstrip("/").rsplit("/", 1)[-1]
        candidate = candidate.strip()
        if candidate:
            return candidate[:200]
    return "Knowledge source"


def _normalize_source_scope_selection(
    scope: SourceScope, selected_source_ids: list[str]
) -> tuple[SourceScope, list[str]]:
    normalized_ids: list[str] = []
    seen: set[str] = set()
    for item in selected_source_ids:
        value = str(item).strip()
        if not value or value in seen:
            continue
        normalized_ids.append(value)
        seen.add(value)
    if scope == SourceScope.SELECTED and not normalized_ids:
        raise ValueError("selected_source_ids must be provided when source_scope=selected")
    if scope != SourceScope.SELECTED and normalized_ids:
        raise ValueError("selected_source_ids can only be provided when source_scope=selected")
    return scope, normalized_ids


class SourceCreateRequest(BaseModel):
    @field_validator("criticality", mode="before")
    @classmethod
    def normalize_criticality_value(
        cls, value: Criticality | str | bool | None
    ) -> Criticality | str | None:
        return _normalize_criticality_alias(value)

    @field_validator("source_type", mode="before")
    @classmethod
    def normalize_source_type(cls, value: SourceType | str) -> SourceType | str:
        return _normalize_source_type_alias(value)

    @field_validator("refresh_policy", mode="before")
    @classmethod
    def normalize_refresh_policy_value(cls, value: str | None) -> str | None:
        return _normalize_refresh_policy(value)

    knowledge_base_id: UUID | str | None = None
    source_type: SourceType = Field(validation_alias=AliasChoices("source_type"))
    name: str | None = Field(
        default=None, max_length=200, validation_alias=AliasChoices("name", "source_name")
    )
    base_uri: str | None = Field(
        default=None, max_length=1000, validation_alias=AliasChoices("base_uri", "source_url")
    )
    criticality: Criticality | None = Field(
        default=None, validation_alias=AliasChoices("criticality", "required_flag")
    )
    refresh_policy: str | None = Field(default=None, max_length=200)
    sync_mode: SourceSyncMode = SourceSyncMode.FULL_SCAN
    source_metadata: dict[str, Any] | None = None
    active_flag: bool | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def normalize(self) -> SourceCreateRequest:
        if self.criticality is None:
            self.criticality = Criticality.REQUIRED
        self.name = _derive_source_name(self.name, self.base_uri)
        if self.active_flag is False:
            raise ValueError(
                "SourceCreateRequest does not support creating disabled sources; source is registered in draft state and can be activated later"
            )
        return self


class SourceUpdateRequest(BaseModel):
    @field_validator("criticality", mode="before")
    @classmethod
    def normalize_criticality_value(
        cls, value: Criticality | str | bool | None
    ) -> Criticality | str | None:
        return _normalize_criticality_alias(value)

    @field_validator("refresh_policy", mode="before")
    @classmethod
    def normalize_refresh_policy_value(cls, value: str | None) -> str | None:
        return _normalize_refresh_policy(value)

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        validation_alias=AliasChoices("name", "source_name"),
    )
    base_uri: str | None = Field(
        default=None, max_length=1000, validation_alias=AliasChoices("base_uri", "source_url")
    )
    criticality: Criticality | None = Field(
        default=None, validation_alias=AliasChoices("criticality", "required_flag")
    )
    status: SourceStatus | None = None
    refresh_policy: str | None = Field(default=None, max_length=200)
    sync_mode: SourceSyncMode | None = None
    source_metadata: dict[str, Any] | None = None
    active_flag: bool | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def normalize(self) -> SourceUpdateRequest:
        if self.active_flag is not None:
            self.status = SourceStatus.ACTIVE if self.active_flag else SourceStatus.DISABLED
        return self


class SourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_validator("source_type", mode="before")
    @classmethod
    def normalize_source_type_value(cls, value: SourceType | str) -> SourceType | str:
        public_map = {
            SourceType.REPOSITORY: SourceType.LOCAL_FOLDER,
            SourceType.URL_LIST: SourceType.URL,
            "repository": SourceType.LOCAL_FOLDER,
            "url_list": SourceType.URL,
        }
        return public_map.get(value, value)

    source_id: UUID | str
    knowledge_base_id: UUID | str
    source_type: SourceType
    name: str
    base_uri: str | None
    criticality: Criticality
    status: SourceStatus
    refresh_policy: str | None
    sync_mode: SourceSyncMode
    source_metadata: dict[str, Any] | None = None
    created_at: datetime
    last_discovered_at: datetime | None = None
    last_sync_time: datetime | None = None
    next_sync_time: datetime | None = None
    availability_status: str | None = None
    document_count: int = 0
    latest_document_registered_at: datetime | None = None
    last_processed_at: datetime | None = None
    last_processing_status: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    update_run_id: UUID | str | None = None


class SourceDocumentCreateRequest(BaseModel):
    document_type: DocumentType
    title: str = Field(min_length=1, max_length=500)
    uri: str = Field(min_length=1, max_length=2000)
    version_label: str | None = Field(default=None, max_length=100)
    checksum: str | None = Field(default=None, max_length=128)
    is_latest: bool = True


class SourceDocumentUpdateRequest(BaseModel):
    @model_validator(mode="after")
    def validate_safe_patch_fields(self) -> SourceDocumentUpdateRequest:
        forbidden_fields = [
            field_name
            for field_name in ("document_type", "uri", "checksum", "status")
            if getattr(self, field_name) is not None
        ]
        if forbidden_fields:
            raise ValueError(
                "Direct document content mutations are not allowed for knowledge-indexed fields; "
                "use upload/reindex/remove flows instead"
            )
        return self

    document_type: DocumentType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=500)
    uri: str | None = Field(default=None, min_length=1, max_length=2000)
    version_label: str | None = Field(default=None, max_length=100)
    checksum: str | None = Field(default=None, max_length=128)
    is_latest: bool | None = None
    status: SourceDocumentStatus | None = None


class SourceDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: UUID | str
    knowledge_base_id: UUID | str | None = None
    source_id: UUID | str
    source_type: SourceType | str | None = None
    document_type: DocumentType
    title: str
    uri: str
    version_label: str | None
    checksum: str | None
    media_type: str | None = None
    size_bytes: int | None = None
    resolved_uri: str | None = None
    fetched_at: datetime | None = None
    discovered_at: datetime | None = None
    document_metadata: dict[str, Any] | None = None
    is_latest: bool
    status: SourceDocumentStatus
    registered_at: datetime
    availability_status: str | None = None
    last_processed_at: datetime | None = None
    last_processing_status: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    update_run_id: UUID | str | None = None


class KnowledgeBundleImportRequest(BaseModel):
    manifest_uri: str = Field(min_length=1, max_length=2000)
    knowledge_base_id: UUID | str | None = None
    activate_if_validated: bool = False
    execute_update_inline: bool | None = None
    reason: str | None = Field(default=None, max_length=500)
    requested_by: str | None = Field(default=None, max_length=200)


class KnowledgeBundleImportResponse(BaseModel):
    manifest_uri: str
    imported_source_ids: list[str] = Field(default_factory=list)
    imported_document_ids: list[str] = Field(default_factory=list)
    update_run_id: UUID | str | None = None
    candidate_knowledge_version_id: UUID | str | None = None
    activated_knowledge_version_id: UUID | str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class KnowledgeUpdateRunStartRequest(BaseModel):
    @model_validator(mode="after")
    def validate_scope(self) -> KnowledgeUpdateRunStartRequest:
        self.source_scope, self.selected_source_ids = _normalize_source_scope_selection(
            self.source_scope, self.selected_source_ids
        )
        self.document_ids = _normalize_str_id_list(self.document_ids)
        self.removed_document_ids = _normalize_str_id_list(self.removed_document_ids)
        self.force_reindex_document_ids = _normalize_str_id_list(self.force_reindex_document_ids)
        if self.document_ids and self.source_scope != SourceScope.SELECTED:
            raise ValueError("document_ids require source_scope=selected")
        return self

    knowledge_base_id: UUID | str | None = None
    run_type: UpdateRunType = UpdateRunType.MANUAL
    source_scope: SourceScope = SourceScope.ALL
    selected_source_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    removed_document_ids: list[str] = Field(default_factory=list)
    force_reindex_all_in_scope: bool = False
    force_reindex_document_ids: list[str] = Field(default_factory=list)
    target_embedding_profile: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=500)
    requested_by: str | None = Field(default=None, max_length=200)
    idempotency_key: str | None = Field(default=None, max_length=100)
    execute_inline: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("execute_inline", "execute_update_inline"),
        serialization_alias="execute_inline",
    )


class InternalKnowledgeUpdateRunStartRequest(BaseModel):
    @model_validator(mode="after")
    def validate_scope(self) -> InternalKnowledgeUpdateRunStartRequest:
        self.source_scope, self.selected_source_ids = _normalize_source_scope_selection(
            self.source_scope, self.selected_source_ids
        )
        self.document_ids = _normalize_str_id_list(self.document_ids)
        self.removed_document_ids = _normalize_str_id_list(self.removed_document_ids)
        self.force_reindex_document_ids = _normalize_str_id_list(self.force_reindex_document_ids)
        if self.document_ids and self.source_scope != SourceScope.SELECTED:
            raise ValueError("document_ids require source_scope=selected")
        return self

    knowledge_base_id: UUID | str | None = None
    run_type: UpdateRunType = UpdateRunType.MANUAL
    source_scope: SourceScope = SourceScope.ALL
    selected_source_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    removed_document_ids: list[str] = Field(default_factory=list)
    force_reindex_all_in_scope: bool = False
    force_reindex_document_ids: list[str] = Field(default_factory=list)
    target_embedding_profile: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=500)
    requested_by: str | None = Field(default=None, max_length=200)
    correlation_id: str | None = Field(default=None, max_length=100)
    idempotency_key: str | None = Field(default=None, max_length=100)
    execute_inline: bool | None = None
    auto_activate_if_validated: bool = False


class KnowledgeUpdateRunResponse(BaseModel):
    update_run_id: UUID | str
    knowledge_base_id: UUID | str | None = None
    run_type: UpdateRunType
    status: KnowledgeUpdateStatus
    current_stage: str | None
    source_scope: SourceScope
    selected_source_ids: list[str] = Field(default_factory=list)
    requested_by: str | None = None
    reason: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    duration_sec: int | None = None
    candidate_knowledge_version_id: UUID | str | None = None
    activated_knowledge_version_id: UUID | str | None = None
    problem_sources: list[dict[str, Any]] = Field(default_factory=list)
    quality_summary: dict[str, Any] = Field(default_factory=dict)
    validation_report: dict[str, Any] = Field(default_factory=dict)
    comparison_to_active: dict[str, Any] | None = None
    activation_metadata: dict[str, Any] | None = None
    diagnostics: dict[str, Any] | None = None
    active_embedding_space_id: UUID | str | None = None
    active_embedding_space_code: str | None = None


class KnowledgeUpdateRunStatusResponse(KnowledgeUpdateRunResponse):
    source_snapshot: dict[str, Any] | None = None


class KnowledgeVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    knowledge_version_id: UUID | str
    knowledge_base_id: UUID | str
    version_no: str
    update_run_id: UUID | str
    status: KnowledgeVersionStatus
    summary: dict[str, Any] | None
    source_snapshot: dict[str, Any] | None
    activation_metadata: dict[str, Any] | None
    activated_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    activated_by_user_id: UUID | str | None
    validation_summary: dict[str, Any] = Field(default_factory=dict)
    validation_report: dict[str, Any] = Field(default_factory=dict)
    required_source_failures: list[str] = Field(default_factory=list)
    missing_required_packages: list[str] = Field(default_factory=list)
    comparison_to_active: dict[str, Any] | None = None
    active_version_diff: dict[str, Any] | None = None
    run_type: UpdateRunType | None = None
    run_reason: str | None = None
    run_requested_by: str | None = None
    document_count: int | None = None
    processing_error_count: int | None = None
    sla: dict[str, Any] | None = None
    embedding_space_id: UUID | str | None = None
    embedding_space_code: str | None = None


class KnowledgeVersionActivateRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class KnowledgeReindexRequest(BaseModel):
    execute_inline: bool | None = None
    reason: str | None = Field(default=None, max_length=500)


class KnowledgeEmbeddingProfileSwitchRequest(BaseModel):
    target_embedding_profile: str = Field(min_length=1, max_length=120)
    execute_inline: bool | None = None
    reason: str | None = Field(default=None, max_length=500)


class RetrievalEvaluationCaseRequest(BaseModel):
    case_id: str | None = Field(default=None, max_length=120)
    query_text: str = Field(min_length=1, max_length=4000)
    use_case: str = Field(default="generation", max_length=50)
    section_code: str | None = Field(default=None, max_length=120)
    expected_fragment_ids: list[str] = Field(default_factory=list)
    expected_document_ids: list[str] = Field(default_factory=list)
    relevance_by_fragment_id: dict[str, float] = Field(default_factory=dict)
    relevance_by_document_id: dict[str, float] = Field(default_factory=dict)
    top_k: int = Field(default=10, ge=1, le=25)

    @model_validator(mode="after")
    def validate_targets(self) -> RetrievalEvaluationCaseRequest:
        self.expected_fragment_ids = _normalize_str_id_list(self.expected_fragment_ids)
        self.expected_document_ids = _normalize_str_id_list(self.expected_document_ids)
        self.relevance_by_fragment_id = {
            str(key).strip(): float(value)
            for key, value in dict(self.relevance_by_fragment_id or {}).items()
            if str(key).strip()
        }
        self.relevance_by_document_id = {
            str(key).strip(): float(value)
            for key, value in dict(self.relevance_by_document_id or {}).items()
            if str(key).strip()
        }
        if not (
            self.expected_fragment_ids
            or self.expected_document_ids
            or self.relevance_by_fragment_id
            or self.relevance_by_document_id
        ):
            raise ValueError("At least one expected fragment/document target is required")
        return self


class RetrievalEvaluationRequest(BaseModel):
    knowledge_version_id: UUID | str
    dataset_name: str | None = Field(default=None, max_length=200)
    cases: list[RetrievalEvaluationCaseRequest] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_cases(self) -> RetrievalEvaluationRequest:
        if not self.cases:
            raise ValueError("At least one evaluation case is required")
        return self


class RetrievalEvaluationCaseResponse(BaseModel):
    case_id: str
    query_text: str
    use_case: str
    section_code: str | None = None
    top_k: int
    expected_target_count: int
    predicted_fragment_ids: list[str] = Field(default_factory=list)
    predicted_document_ids: list[str] = Field(default_factory=list)
    recall_at_5: float
    recall_at_10: float
    mrr_at_10: float
    ndcg_at_10: float
    hit_at_10: float
    hit_after_rerank: float
    first_relevant_rank: int | None = None
    matched_targets: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class RetrievalEvaluationResponse(BaseModel):
    dataset_name: str | None = None
    knowledge_version_id: UUID | str
    case_count: int
    metrics: dict[str, float] = Field(default_factory=dict)
    cases: list[RetrievalEvaluationCaseResponse] = Field(default_factory=list)


class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class KnowledgeBaseUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    status: KnowledgeBaseStatus | None = None


class KnowledgeBaseSelectRequest(BaseModel):
    knowledge_version_id: UUID | str | None = None


class KnowledgeBaseResponse(BaseModel):
    knowledge_base_id: UUID | str
    code: str
    name: str
    description: str | None = None
    kind: KnowledgeBaseKind
    status: KnowledgeBaseStatus
    created_at: datetime
    updated_at: datetime
    active_knowledge_version_id: UUID | str | None = None
    active_version_no: str | None = None
    selected_for_generation: bool = False
    selected_knowledge_version_id: UUID | str | None = None
    selected_knowledge_version_no: str | None = None
    active_embedding_space_id: UUID | str | None = None
    active_embedding_space_code: str | None = None
    source_count: int = 0
    active_source_count: int = 0
    document_count: int = 0
    latest_sync_at: datetime | None = None
    latest_sync_status: KnowledgeUpdateStatus | None = None
    latest_sync_run_id: UUID | str | None = None
    latest_successful_sync_at: datetime | None = None
    last_sync_duration_sec: int | None = None
    last_sync_error_count: int = 0
    versions: list[dict[str, Any]] = Field(default_factory=list)


class DocumentChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_chunk_id: UUID | str
    document_snapshot_id: UUID | str
    knowledge_version_id: UUID | str
    document_id: UUID | str
    chunk_index: int
    title: str | None = None
    source_location: str | None = None
    content: str
    start_offset: int | None = None
    end_offset: int | None = None
    chunk_metadata: dict[str, Any] | None = None
    created_at: datetime


class DocumentSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_snapshot_id: UUID | str
    knowledge_version_id: UUID | str
    document_id: UUID | str
    checksum: str | None = None
    content_format: str
    parser_name: str
    normalized_text: str
    structure_metadata: dict[str, Any] | None = None
    created_at: datetime
    chunks: list[DocumentChunkResponse] = Field(default_factory=list)


class ExtractedKnowledgeItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    extracted_item_id: UUID | str
    knowledge_version_id: UUID | str
    document_id: UUID | str
    document_chunk_id: UUID | str | None = None
    item_type: ExtractedKnowledgeType
    title: str | None = None
    content: str
    normalized_value: str | None = None
    source_location: str | None = None
    confidence_score: float | None = None
    quality_status: ExtractionQualityStatus
    evidence_quote: str | None = None
    structured_payload: dict[str, Any] | None = None
    created_at: datetime


class DocumentMemoryResponse(BaseModel):
    document_id: UUID | str
    knowledge_version_id: UUID | str | None = None
    summary: str | None = None
    counters: dict[str, int] = Field(default_factory=dict)
    extraction_method: str | None = None
    llm_attempted: bool = False
    fallback_applied: bool = False
    fallback_reason: str | None = None
    items: list[ExtractedKnowledgeItemResponse] = Field(default_factory=list)


class DocumentExtractedItemsResponse(BaseModel):
    document_id: UUID | str
    knowledge_version_id: UUID | str | None = None
    item_count: int = 0
    items: list[ExtractedKnowledgeItemResponse] = Field(default_factory=list)


class DocumentDeltaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_delta_id: UUID | str
    update_run_id: UUID | str
    knowledge_base_id: UUID | str
    knowledge_version_id: UUID | str
    source_id: UUID | str | None = None
    document_id: UUID | str | None = None
    delta_kind: DocumentDeltaKind
    uri: str | None = None
    checksum_before: str | None = None
    checksum_after: str | None = None
    details: dict[str, Any] | None = None
    created_at: datetime


class KnowledgeBaseDocumentResponse(BaseModel):
    document_id: UUID | str | None = None
    knowledge_base_id: UUID | str
    knowledge_version_id: UUID | str
    source_id: UUID | str | None = None
    source_name: str | None = None
    source_type: SourceType | str | None = None
    source_status: SourceStatus | str | None = None
    title: str
    uri: str | None = None
    document_type: DocumentType | str | None = None
    version_label: str | None = None
    checksum: str | None = None
    role_code: str | None = None
    required_flag: bool = False
    present_in_version: bool = True
    delta_kind: DocumentDeltaKind | None = None
    document_status: SourceDocumentStatus | str | None = None
    processing_status: str | None = None
    processing_error_code: str | None = None
    processing_error_message: str | None = None
    registered_at: datetime | None = None
    discovered_at: datetime | None = None


class DocumentMutationResponse(BaseModel):
    document: SourceDocumentResponse
    update_run: KnowledgeUpdateRunResponse | None = None


class DocumentBatchMutationResponse(BaseModel):
    documents: list[SourceDocumentResponse]
    update_run: KnowledgeUpdateRunResponse | None = None


class ScheduledKnowledgeSyncResponse(BaseModel):
    started_run_ids: list[str] = Field(default_factory=list)
    started_knowledge_base_ids: list[str] = Field(default_factory=list)
    skipped_knowledge_base_ids: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class KnowledgeNotificationResponse(BaseModel):
    notification_id: str
    knowledge_base_id: UUID | str
    knowledge_base_name: str
    update_run_id: UUID | str
    knowledge_version_id: UUID | str | None = None
    title: str
    message: str
    tone: str
    status: KnowledgeUpdateStatus
    created_at: datetime
