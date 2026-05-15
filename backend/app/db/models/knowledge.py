from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

try:
    from pgvector.sqlalchemy import Vector as PgVector  # type: ignore[import-untyped]

    def Vector(dimensions: int | None = None):
        return PgVector(dimensions) if dimensions is not None else PgVector()
except Exception:  # pragma: no cover

    def Vector(dimensions: int | None = None):
        return ARRAY(Float)


from app.db.base import Base
from app.db.constants import EMBEDDING_VECTOR_DIMENSIONS
from app.db.enums import (
    Criticality,
    DocumentDeltaKind,
    DocumentType,
    ExtractedKnowledgeType,
    ExtractionQualityStatus,
    FragmentStatus,
    FragmentType,
    KnowledgeBaseKind,
    KnowledgeBaseStatus,
    KnowledgeUpdateStatus,
    KnowledgeVersionStatus,
    NormativeRuleStatus,
    RuleCategory,
    Severity,
    SourceDocumentStatus,
    SourceProcessingStatus,
    SourceStatus,
    SourceSyncMode,
    SourceType,
    UpdateRunType,
)
from app.db.models.common import enum_column, uuid_primary_key

if TYPE_CHECKING:
    from app.db.models.generation import GenerationRun, SolutionSectionSourceRef
    from app.db.models.verification import VerificationRun


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (UniqueConstraint("code", name="uq_knowledge_bases_code"),)

    knowledge_base_id: Mapped[str] = uuid_primary_key("knowledge_base_id")
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[KnowledgeBaseKind] = enum_column(KnowledgeBaseKind)
    status: Mapped[KnowledgeBaseStatus] = enum_column(KnowledgeBaseStatus)
    owner_user_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    preferred_embedding_space_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("embedding_spaces.embedding_space_id")
    )

    preferred_embedding_space: Mapped[EmbeddingSpace | None] = relationship(
        foreign_keys=[preferred_embedding_space_id]
    )
    sources: Mapped[list[KnowledgeSource]] = relationship(back_populates="knowledge_base")
    update_runs: Mapped[list[KnowledgeUpdateRun]] = relationship(back_populates="knowledge_base")
    versions: Mapped[list[KnowledgeVersion]] = relationship(back_populates="knowledge_base")
    document_deltas: Mapped[list[DocumentDelta]] = relationship(back_populates="knowledge_base")
    selections: Mapped[list[KnowledgeBaseSelection]] = relationship(
        back_populates="selected_knowledge_base"
    )


class KnowledgeBaseSelection(Base):
    __tablename__ = "knowledge_base_selections"
    __table_args__ = (
        UniqueConstraint("selection_scope", name="uq_knowledge_base_selections_scope"),
        ForeignKeyConstraint(
            ["selected_knowledge_base_id", "selected_knowledge_version_id"],
            ["knowledge_versions.knowledge_base_id", "knowledge_versions.knowledge_version_id"],
            name="fk_knowledge_base_selections_selected_version_scope",
        ),
    )

    knowledge_base_selection_id: Mapped[str] = uuid_primary_key("knowledge_base_selection_id")
    selection_scope: Mapped[str] = mapped_column(
        String(100), nullable=False, default="generation", server_default="generation"
    )
    selected_knowledge_base_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=False
    )
    selected_knowledge_version_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_versions.knowledge_version_id")
    )
    updated_by_user_id: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    selected_knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="selections")
    selected_knowledge_version: Mapped[KnowledgeVersion | None] = relationship(
        foreign_keys=[selected_knowledge_version_id]
    )


class EmbeddingSpace(Base):
    __tablename__ = "embedding_spaces"
    __table_args__ = (
        UniqueConstraint("code", name="uq_embedding_spaces_code"),
        Index(
            "uq_embedding_spaces_active_only",
            "is_active",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )

    embedding_space_id: Mapped[str] = uuid_primary_key("embedding_space_id")
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_metric: Mapped[str] = mapped_column(
        String(32), nullable=False, default="cosine", server_default="cosine"
    )
    query_template: Mapped[str | None] = mapped_column(Text)
    document_template: Mapped[str | None] = mapped_column(Text)
    normalize_l2: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    truncate_dim: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    fragment_embeddings: Mapped[list[KnowledgeFragmentEmbedding]] = relationship(
        back_populates="embedding_space"
    )


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"
    __table_args__ = (
        Index("ix_knowledge_sources_knowledge_base_created_at", "knowledge_base_id", "created_at"),
        Index(
            "uq_knowledge_sources_manual_upload_per_base",
            "knowledge_base_id",
            "source_type",
            unique=True,
            postgresql_where=text("source_type = 'manual_upload'"),
        ),
    )

    source_id: Mapped[str] = uuid_primary_key("source_id")
    knowledge_base_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=False
    )
    source_type: Mapped[SourceType] = enum_column(SourceType)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_uri: Mapped[str | None] = mapped_column(String(1000))
    criticality: Mapped[Criticality] = enum_column(Criticality)
    status: Mapped[SourceStatus] = enum_column(SourceStatus)
    refresh_policy: Mapped[str | None] = mapped_column(String(200))
    sync_mode: Mapped[SourceSyncMode] = enum_column(
        SourceSyncMode,
        default=SourceSyncMode.FULL_SCAN,
        server_default=SourceSyncMode.FULL_SCAN.value,
    )
    source_metadata: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="sources")
    source_documents: Mapped[list[SourceDocument]] = relationship(back_populates="source")
    processing_results: Mapped[list[SourceProcessingResult]] = relationship(back_populates="source")


class SourceDocument(Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        UniqueConstraint("source_id", "uri", name="uq_source_documents_source_uri"),
        Index("ix_source_documents_source_registered_at", "source_id", "registered_at"),
    )

    document_id: Mapped[str] = uuid_primary_key("document_id")
    source_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_sources.source_id"), nullable=False
    )
    document_type: Mapped[DocumentType] = enum_column(DocumentType)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    uri: Mapped[str] = mapped_column(String(2000), nullable=False)
    version_label: Mapped[str | None] = mapped_column(String(100))
    checksum: Mapped[str | None] = mapped_column(String(128))
    media_type: Mapped[str | None] = mapped_column(String(200))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    resolved_uri: Mapped[str | None] = mapped_column(String(2000))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    document_metadata: Mapped[dict | None] = mapped_column(JSONB)
    is_latest: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    status: Mapped[SourceDocumentStatus] = enum_column(SourceDocumentStatus)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    source: Mapped[KnowledgeSource] = relationship(back_populates="source_documents")
    processing_results: Mapped[list[SourceProcessingResult]] = relationship(
        back_populates="document"
    )
    knowledge_version_documents: Mapped[list[KnowledgeVersionDocument]] = relationship(
        back_populates="document"
    )
    document_snapshots: Mapped[list[DocumentSnapshot]] = relationship(back_populates="document")
    knowledge_fragments: Mapped[list[KnowledgeFragment]] = relationship(back_populates="document")
    normative_rules: Mapped[list[NormativeRule]] = relationship(back_populates="document")
    extracted_items: Mapped[list[DocumentExtractedItem]] = relationship(back_populates="document")
    document_deltas: Mapped[list[DocumentDelta]] = relationship(back_populates="document")
    section_source_refs: Mapped[list[SolutionSectionSourceRef]] = relationship(
        back_populates="document"
    )


class KnowledgeUpdateRun(Base):
    __tablename__ = "knowledge_update_runs"
    __table_args__ = (
        Index(
            "ix_knowledge_update_runs_knowledge_base_started_at", "knowledge_base_id", "started_at"
        ),
        Index("ix_knowledge_update_runs_correlation_id", "correlation_id"),
        Index("ix_knowledge_update_runs_status_started_at", "status", "started_at"),
        Index("ix_knowledge_update_runs_started_at", "started_at"),
        Index(
            "uq_knowledge_update_runs_active_per_base",
            "knowledge_base_id",
            unique=True,
            postgresql_where=text(
                "status NOT IN ('completed', 'completed_with_warnings', 'failed', 'canceled')"
            ),
        ),
    )

    update_run_id: Mapped[str] = uuid_primary_key("update_run_id")
    knowledge_base_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=False
    )
    run_type: Mapped[UpdateRunType] = enum_column(UpdateRunType)
    initiator_user_id: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[KnowledgeUpdateStatus] = enum_column(KnowledgeUpdateStatus)
    current_stage: Mapped[str | None] = mapped_column(String(50))
    scope: Mapped[dict | None] = mapped_column(JSONB)
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[dict | None] = mapped_column(JSONB)

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="update_runs")
    processing_results: Mapped[list[SourceProcessingResult]] = relationship(
        back_populates="update_run"
    )
    knowledge_versions: Mapped[list[KnowledgeVersion]] = relationship(back_populates="update_run")
    document_deltas: Mapped[list[DocumentDelta]] = relationship(back_populates="update_run")


class SourceProcessingResult(Base):
    __tablename__ = "source_processing_results"
    __table_args__ = (
        Index("ix_source_processing_results_update_run_id", "update_run_id"),
        Index("ix_source_processing_results_source_processed_at", "source_id", "processed_at"),
        Index("ix_source_processing_results_document_processed_at", "document_id", "processed_at"),
    )

    processing_result_id: Mapped[str] = uuid_primary_key("processing_result_id")
    update_run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_update_runs.update_run_id"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_sources.source_id"), nullable=False
    )
    document_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_documents.document_id")
    )
    status: Mapped[SourceProcessingStatus] = enum_column(SourceProcessingStatus)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict | None] = mapped_column(JSONB)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    update_run: Mapped[KnowledgeUpdateRun] = relationship(back_populates="processing_results")
    source: Mapped[KnowledgeSource] = relationship(back_populates="processing_results")
    document: Mapped[SourceDocument | None] = relationship(back_populates="processing_results")


class DocumentSnapshot(Base):
    __tablename__ = "document_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_version_id", "document_id", name="uq_document_snapshots_version_document"
        ),
        UniqueConstraint(
            "document_snapshot_id",
            "knowledge_version_id",
            "document_id",
            name="uq_document_snapshots_id_version_document",
        ),
    )

    document_snapshot_id: Mapped[str] = uuid_primary_key("document_snapshot_id")
    knowledge_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_versions.knowledge_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_documents.document_id", ondelete="CASCADE"),
        nullable=False,
    )
    checksum: Mapped[str | None] = mapped_column(String(128))
    content_format: Mapped[str] = mapped_column(String(50), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(100), nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    structure_metadata: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    knowledge_version: Mapped[KnowledgeVersion] = relationship(back_populates="document_snapshots")
    document: Mapped[SourceDocument] = relationship(back_populates="document_snapshots")
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document_snapshot",
        cascade="all, delete-orphan",
        foreign_keys="DocumentChunk.document_snapshot_id",
        primaryjoin="DocumentSnapshot.document_snapshot_id == DocumentChunk.document_snapshot_id",
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_snapshot_id", "chunk_index", name="uq_document_chunks_snapshot_idx"
        ),
        ForeignKeyConstraint(
            ["document_snapshot_id", "knowledge_version_id", "document_id"],
            [
                "document_snapshots.document_snapshot_id",
                "document_snapshots.knowledge_version_id",
                "document_snapshots.document_id",
            ],
            name="fk_document_chunks_snapshot_scope",
            ondelete="CASCADE",
        ),
    )

    document_chunk_id: Mapped[str] = uuid_primary_key("document_chunk_id")
    document_snapshot_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_snapshots.document_snapshot_id", ondelete="CASCADE"),
        nullable=False,
    )
    knowledge_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_versions.knowledge_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_documents.document_id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    source_location: Mapped[str | None] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int | None] = mapped_column(Integer)
    end_offset: Mapped[int | None] = mapped_column(Integer)
    chunk_metadata: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document_snapshot: Mapped[DocumentSnapshot] = relationship(
        back_populates="chunks",
        foreign_keys=[document_snapshot_id],
        primaryjoin="DocumentChunk.document_snapshot_id == DocumentSnapshot.document_snapshot_id",
    )
    knowledge_version: Mapped[KnowledgeVersion] = relationship(back_populates="document_chunks")
    document: Mapped[SourceDocument] = relationship()
    extracted_items: Mapped[list[DocumentExtractedItem]] = relationship(
        back_populates="document_chunk"
    )


class KnowledgeVersion(Base):
    __tablename__ = "knowledge_versions"
    __table_args__ = (
        UniqueConstraint("update_run_id", name="uq_knowledge_versions_update_run_id"),
        UniqueConstraint(
            "knowledge_base_id", "knowledge_version_id", name="uq_knowledge_versions_base_version"
        ),
        Index(
            "uq_knowledge_versions_active_only",
            "knowledge_base_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    knowledge_version_id: Mapped[str] = uuid_primary_key("knowledge_version_id")
    knowledge_base_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.knowledge_base_id"), nullable=False
    )
    version_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    update_run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_update_runs.update_run_id"), nullable=False
    )
    embedding_space_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("embedding_spaces.embedding_space_id")
    )
    status: Mapped[KnowledgeVersionStatus] = enum_column(KnowledgeVersionStatus)
    summary: Mapped[dict | None] = mapped_column(JSONB)
    source_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    activation_metadata: Mapped[dict | None] = mapped_column(JSONB)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_by_user_id: Mapped[str | None] = mapped_column(String(100))

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="versions")
    update_run: Mapped[KnowledgeUpdateRun] = relationship(back_populates="knowledge_versions")
    embedding_space: Mapped[EmbeddingSpace | None] = relationship(foreign_keys=[embedding_space_id])
    document_snapshots: Mapped[list[DocumentSnapshot]] = relationship(
        back_populates="knowledge_version", cascade="all, delete-orphan"
    )
    document_chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="knowledge_version", cascade="all, delete-orphan"
    )
    version_documents: Mapped[list[KnowledgeVersionDocument]] = relationship(
        back_populates="knowledge_version"
    )
    knowledge_fragments: Mapped[list[KnowledgeFragment]] = relationship(
        back_populates="knowledge_version"
    )
    normative_rules: Mapped[list[NormativeRule]] = relationship(back_populates="knowledge_version")
    extracted_items: Mapped[list[DocumentExtractedItem]] = relationship(
        back_populates="knowledge_version"
    )
    document_deltas: Mapped[list[DocumentDelta]] = relationship(back_populates="knowledge_version")
    generation_runs: Mapped[list[GenerationRun]] = relationship(back_populates="knowledge_version")
    verification_runs: Mapped[list[VerificationRun]] = relationship(
        back_populates="knowledge_version"
    )


class KnowledgeVersionDocument(Base):
    __tablename__ = "knowledge_version_documents"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_version_id", "document_id", name="uq_knowledge_version_documents_scope"
        ),
    )

    version_document_id: Mapped[str] = uuid_primary_key("version_document_id")
    knowledge_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_versions.knowledge_version_id"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_documents.document_id"), nullable=False
    )
    role_code: Mapped[str] = mapped_column(
        String(100), nullable=False, default="reference_only", server_default="reference_only"
    )
    required_flag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    included_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    knowledge_version: Mapped[KnowledgeVersion] = relationship(back_populates="version_documents")
    document: Mapped[SourceDocument] = relationship(back_populates="knowledge_version_documents")


class DocumentExtractedItem(Base):
    __tablename__ = "document_extracted_items"
    __table_args__ = (
        Index("ix_document_extracted_items_knowledge_version_id", "knowledge_version_id"),
        Index("ix_document_extracted_items_document_id", "document_id"),
    )

    extracted_item_id: Mapped[str] = uuid_primary_key("extracted_item_id")
    knowledge_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_versions.knowledge_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_documents.document_id", ondelete="CASCADE"),
        nullable=False,
    )
    document_chunk_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_chunks.document_chunk_id", ondelete="SET NULL")
    )
    item_type: Mapped[ExtractedKnowledgeType] = enum_column(ExtractedKnowledgeType)
    title: Mapped[str | None] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str | None] = mapped_column(String(500))
    source_location: Mapped[str | None] = mapped_column(String(200))
    confidence_score: Mapped[float | None] = mapped_column(Float)
    quality_status: Mapped[ExtractionQualityStatus] = enum_column(ExtractionQualityStatus)
    evidence_quote: Mapped[str | None] = mapped_column(Text)
    structured_payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    knowledge_version: Mapped[KnowledgeVersion] = relationship(back_populates="extracted_items")
    document: Mapped[SourceDocument] = relationship(back_populates="extracted_items")
    document_chunk: Mapped[DocumentChunk | None] = relationship(back_populates="extracted_items")


class DocumentDelta(Base):
    __tablename__ = "document_deltas"
    __table_args__ = (
        Index("ix_document_deltas_update_run_id", "update_run_id"),
        Index("ix_document_deltas_knowledge_version_id", "knowledge_version_id"),
    )

    document_delta_id: Mapped[str] = uuid_primary_key("document_delta_id")
    update_run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_update_runs.update_run_id", ondelete="CASCADE"),
        nullable=False,
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.knowledge_base_id", ondelete="CASCADE"),
        nullable=False,
    )
    knowledge_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_versions.knowledge_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_sources.source_id", ondelete="SET NULL")
    )
    document_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_documents.document_id", ondelete="SET NULL")
    )
    delta_kind: Mapped[DocumentDeltaKind] = enum_column(DocumentDeltaKind)
    uri: Mapped[str | None] = mapped_column(String(2000))
    checksum_before: Mapped[str | None] = mapped_column(String(128))
    checksum_after: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    update_run: Mapped[KnowledgeUpdateRun] = relationship(back_populates="document_deltas")
    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="document_deltas")
    knowledge_version: Mapped[KnowledgeVersion] = relationship(back_populates="document_deltas")
    document: Mapped[SourceDocument | None] = relationship(back_populates="document_deltas")


class KnowledgeFragment(Base):
    __tablename__ = "knowledge_fragments"
    __table_args__ = (
        Index("ix_knowledge_fragments_knowledge_version_id", "knowledge_version_id"),
        Index("ix_knowledge_fragments_document_id", "document_id"),
        Index(
            "ix_knowledge_fragments_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    fragment_id: Mapped[str] = uuid_primary_key("fragment_id")
    knowledge_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_versions.knowledge_version_id"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_documents.document_id"), nullable=False
    )
    fragment_type: Mapped[FragmentType] = enum_column(FragmentType)
    title: Mapped[str | None] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_location: Mapped[str | None] = mapped_column(String(200))
    fragment_metadata: Mapped[dict | None] = mapped_column(JSONB)
    embedding_key: Mapped[str | None] = mapped_column(String(255))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_VECTOR_DIMENSIONS))
    status: Mapped[FragmentStatus] = enum_column(FragmentStatus)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    knowledge_version: Mapped[KnowledgeVersion] = relationship(back_populates="knowledge_fragments")
    document: Mapped[SourceDocument] = relationship(back_populates="knowledge_fragments")
    fragment_embeddings: Mapped[list[KnowledgeFragmentEmbedding]] = relationship(
        back_populates="fragment", cascade="all, delete-orphan"
    )
    section_source_refs: Mapped[list[SolutionSectionSourceRef]] = relationship(
        back_populates="fragment"
    )


class KnowledgeFragmentEmbedding(Base):
    __tablename__ = "knowledge_fragment_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "fragment_id", "embedding_space_id", name="uq_knowledge_fragment_embeddings_scope"
        ),
        Index("ix_knowledge_fragment_embeddings_fragment_id", "fragment_id"),
        Index("ix_knowledge_fragment_embeddings_embedding_space_id", "embedding_space_id"),
    )

    fragment_embedding_id: Mapped[str] = uuid_primary_key("fragment_embedding_id")
    fragment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_fragments.fragment_id", ondelete="CASCADE"),
        nullable=False,
    )
    embedding_space_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("embedding_spaces.embedding_space_id", ondelete="CASCADE"),
        nullable=False,
    )
    embedding_key: Mapped[str | None] = mapped_column(String(255))
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    fragment: Mapped[KnowledgeFragment] = relationship(back_populates="fragment_embeddings")
    embedding_space: Mapped[EmbeddingSpace] = relationship(back_populates="fragment_embeddings")


class NormativeRule(Base):
    __tablename__ = "normative_rules"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_version_id", "rule_code", name="uq_normative_rules_version_code"
        ),
    )

    rule_id: Mapped[str] = uuid_primary_key("rule_id")
    knowledge_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_versions.knowledge_version_id"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_documents.document_id"), nullable=False
    )
    rule_code: Mapped[str] = mapped_column(String(100), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(300), nullable=False)
    rule_text: Mapped[str] = mapped_column(Text, nullable=False)
    rule_category: Mapped[RuleCategory] = enum_column(RuleCategory)
    applicability_condition: Mapped[dict | None] = mapped_column(JSONB)
    severity_default: Mapped[Severity] = enum_column(Severity)
    status: Mapped[NormativeRuleStatus] = enum_column(NormativeRuleStatus)

    knowledge_version: Mapped[KnowledgeVersion] = relationship(back_populates="normative_rules")
    document: Mapped[SourceDocument] = relationship(back_populates="normative_rules")
