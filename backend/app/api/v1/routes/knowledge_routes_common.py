from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Body, Depends, File, Form, Query, UploadFile, status

from app.api.deps import PrincipalDep, SessionDep, SettingsDep, WriteGuardDep, require_roles
from app.bootstrap.bundles import import_knowledge_bundle
from app.core.exceptions import ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import (
    ROLE_USER,
    DocumentType,
    KnowledgeUpdateStatus,
    SourceScope,
    SourceType,
    UpdateRunType,
)
from app.domain.services.knowledge.source_service import KnowledgeSourceService
from app.domain.services.knowledge.update_service import KnowledgeUpdateService
from app.domain.services.knowledge.version_service import KnowledgeVersionService
from app.domain.services.knowledge_bases import KnowledgeBaseService
from app.domain.services.knowledge_query import KnowledgeQueryService
from app.domain.services.principal_keys import principal_requested_by
from app.integrations.knowledge.evaluation import (
    aggregate_retrieval_eval,
    evaluate_retrieval_case,
    parse_eval_case,
)
from app.integrations.knowledge.source_readers import guess_document_type_from_name
from app.integrations.knowledge.source_security import (
    enforce_document_size_limit,
)
from app.schemas.knowledge import (
    DocumentBatchMutationResponse,
    DocumentChunkResponse,
    DocumentExtractedItemsResponse,
    DocumentMemoryResponse,
    DocumentMutationResponse,
    DocumentSnapshotResponse,
    InternalKnowledgeUpdateRunStartRequest,
    KnowledgeBaseCreateRequest,
    KnowledgeBaseDocumentResponse,
    KnowledgeBaseResponse,
    KnowledgeBaseSelectRequest,
    KnowledgeBaseUpdateRequest,
    KnowledgeBundleImportRequest,
    KnowledgeBundleImportResponse,
    KnowledgeEmbeddingProfileSwitchRequest,
    KnowledgeNotificationResponse,
    KnowledgeReindexRequest,
    KnowledgeUpdateRunResponse,
    KnowledgeUpdateRunStartRequest,
    KnowledgeUpdateRunStatusResponse,
    KnowledgeVersionActivateRequest,
    KnowledgeVersionResponse,
    RetrievalEvaluationRequest,
    RetrievalEvaluationResponse,
    ScheduledKnowledgeSyncResponse,
    SourceCreateRequest,
    SourceDocumentCreateRequest,
    SourceDocumentResponse,
    SourceDocumentUpdateRequest,
    SourceResponse,
    SourceUpdateRequest,
)

UserDep = Depends(require_roles(ROLE_USER))

__all__ = [
    "APIRouter",
    "AuthPrincipal",
    "Body",
    "DocumentBatchMutationResponse",
    "DocumentChunkResponse",
    "DocumentExtractedItemsResponse",
    "DocumentMemoryResponse",
    "DocumentMutationResponse",
    "DocumentSnapshotResponse",
    "DocumentType",
    "File",
    "Form",
    "InternalKnowledgeUpdateRunStartRequest",
    "KnowledgeBaseCreateRequest",
    "KnowledgeBaseDocumentResponse",
    "KnowledgeBaseResponse",
    "KnowledgeBaseSelectRequest",
    "KnowledgeBaseService",
    "KnowledgeBaseUpdateRequest",
    "KnowledgeBundleImportRequest",
    "KnowledgeBundleImportResponse",
    "KnowledgeEmbeddingProfileSwitchRequest",
    "KnowledgeNotificationResponse",
    "KnowledgeQueryService",
    "KnowledgeReindexRequest",
    "KnowledgeSourceService",
    "KnowledgeUpdateRunResponse",
    "KnowledgeUpdateRunStartRequest",
    "KnowledgeUpdateRunStatusResponse",
    "KnowledgeUpdateService",
    "KnowledgeUpdateStatus",
    "KnowledgeVersionActivateRequest",
    "KnowledgeVersionResponse",
    "KnowledgeVersionService",
    "PrincipalDep",
    "Query",
    "RetrievalEvaluationRequest",
    "RetrievalEvaluationResponse",
    "ScheduledKnowledgeSyncResponse",
    "SessionDep",
    "SettingsDep",
    "SourceCreateRequest",
    "SourceDocumentCreateRequest",
    "SourceDocumentResponse",
    "SourceDocumentUpdateRequest",
    "SourceResponse",
    "SourceScope",
    "SourceType",
    "SourceUpdateRequest",
    "UpdateRunType",
    "UploadFile",
    "UserDep",
    "ValidationError",
    "WriteGuardDep",
    "aggregate_retrieval_eval",
    "enforce_document_size_limit",
    "evaluate_retrieval_case",
    "guess_document_type_from_name",
    "import_knowledge_bundle",
    "parse_eval_case",
    "principal_requested_by",
    "status",
    "uuid4",
]
