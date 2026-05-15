from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import (
    CheckResultStatus,
    ProtocolSummaryStatus,
    Severity,
    VerificationProtocolStatus,
    VerificationRunStatus,
)
from app.db.models.common import enum_column, uuid_primary_key

if TYPE_CHECKING:
    from app.db.models.generation import SolutionVersion
    from app.db.models.knowledge import KnowledgeVersion, SourceDocument


class VerificationRun(Base):
    __tablename__ = "verification_runs"
    __table_args__ = (
        Index("ix_verification_runs_solution_started_at", "solution_version_id", "started_at"),
        Index("ix_verification_runs_correlation_id", "correlation_id"),
        Index("ix_verification_runs_started_at", "started_at"),
        Index(
            "uq_verification_runs_active_per_solution",
            "solution_version_id",
            unique=True,
            postgresql_where=text("status NOT IN ('completed', 'failed', 'canceled')"),
        ),
    )

    verification_run_id: Mapped[str] = uuid_primary_key("verification_run_id")
    solution_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("solution_versions.solution_version_id"), nullable=False
    )
    knowledge_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_versions.knowledge_version_id"), nullable=False
    )
    started_by_user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[VerificationRunStatus] = enum_column(VerificationRunStatus)
    current_stage: Mapped[str | None] = mapped_column(String(50))
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scope_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    diagnostics: Mapped[dict | None] = mapped_column(JSONB)

    solution_version: Mapped[SolutionVersion] = relationship(back_populates="verification_runs")
    knowledge_version: Mapped[KnowledgeVersion] = relationship(back_populates="verification_runs")
    protocol: Mapped[VerificationProtocol | None] = relationship(back_populates="verification_run")


class VerificationProtocol(Base):
    __tablename__ = "verification_protocols"

    verification_protocol_id: Mapped[str] = uuid_primary_key("verification_protocol_id")
    verification_run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("verification_runs.verification_run_id"),
        nullable=False,
        unique=True,
    )
    protocol_no: Mapped[str | None] = mapped_column(String(100))
    summary_status: Mapped[ProtocolSummaryStatus] = enum_column(ProtocolSummaryStatus)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[VerificationProtocolStatus] = enum_column(VerificationProtocolStatus)

    verification_run: Mapped[VerificationRun] = relationship(back_populates="protocol")
    check_results: Mapped[list[CheckResult]] = relationship(back_populates="verification_protocol")
    basis_documents: Mapped[list[VerificationBasisDocument]] = relationship(
        back_populates="verification_protocol"
    )

    @property
    def findings(self) -> list[CheckResult]:
        return self.check_results


class VerificationBasisDocument(Base):
    __tablename__ = "verification_basis_documents"
    __table_args__ = (
        UniqueConstraint(
            "verification_protocol_id",
            "sort_order",
            name="uq_verification_basis_documents_sort_order",
        ),
    )

    protocol_basis_document_id: Mapped[str] = uuid_primary_key("protocol_basis_document_id")
    verification_protocol_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("verification_protocols.verification_protocol_id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_documents.document_id")
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    role_code: Mapped[str | None] = mapped_column(String(100))
    version_ref: Mapped[str | None] = mapped_column(String(100))
    required_flag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    verification_protocol: Mapped[VerificationProtocol] = relationship(
        back_populates="basis_documents"
    )
    document: Mapped[SourceDocument | None] = relationship()


class CheckResult(Base):
    __tablename__ = "check_results"
    __table_args__ = (
        UniqueConstraint(
            "verification_protocol_id", "sort_order", name="uq_check_results_sort_order"
        ),
    )

    check_result_id: Mapped[str] = uuid_primary_key("check_result_id")
    verification_protocol_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("verification_protocols.verification_protocol_id", ondelete="CASCADE"),
        nullable=False,
    )
    rule_id: Mapped[str | None] = mapped_column(String(100))
    rule_name: Mapped[str | None] = mapped_column(String(300))
    check_name: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[CheckResultStatus] = enum_column(CheckResultStatus)
    severity: Mapped[Severity] = enum_column(Severity)
    finding_text: Mapped[str | None] = mapped_column(Text)
    evidence_ref: Mapped[str | None] = mapped_column(Text)
    related_section_ref: Mapped[str | None] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_technical_check: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    verification_protocol: Mapped[VerificationProtocol] = relationship(
        back_populates="check_results"
    )


VerificationFinding = CheckResult
