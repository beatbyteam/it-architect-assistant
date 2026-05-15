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
    BusinessTaskStatus,
    ClarificationRequestStatus,
    GenerationRunStatus,
    Severity,
    SolutionListItemGroup,
    SolutionVersionStatus,
)
from app.db.models.common import enum_column, uuid_primary_key

if TYPE_CHECKING:
    from app.db.models.knowledge import KnowledgeFragment, KnowledgeVersion, SourceDocument
    from app.db.models.verification import VerificationRun


class BusinessTask(Base):
    __tablename__ = "business_tasks"

    business_task_id: Mapped[str] = uuid_primary_key("business_task_id")
    created_by_user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str | None] = mapped_column(String(300))
    task_text: Mapped[str] = mapped_column(Text, nullable=False)
    task_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)
    status: Mapped[BusinessTaskStatus] = enum_column(BusinessTaskStatus)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    clarification_requests: Mapped[list[ClarificationRequest]] = relationship(
        back_populates="business_task"
    )
    generation_runs: Mapped[list[GenerationRun]] = relationship(back_populates="business_task")
    solution_versions: Mapped[list[SolutionVersion]] = relationship(back_populates="business_task")


class ClarificationRequest(Base):
    __tablename__ = "clarification_requests"

    clarification_id: Mapped[str] = uuid_primary_key("clarification_id")
    business_task_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("business_tasks.business_task_id", ondelete="CASCADE"),
        nullable=False,
    )
    state: Mapped[ClarificationRequestStatus] = enum_column(ClarificationRequestStatus)
    question_items: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    business_task: Mapped[BusinessTask] = relationship(back_populates="clarification_requests")
    answers: Mapped[list[ClarificationAnswer]] = relationship(
        back_populates="clarification_request"
    )


class ClarificationAnswer(Base):
    __tablename__ = "clarification_answers"
    __table_args__ = (
        UniqueConstraint(
            "clarification_id", "sort_order", name="uq_clarification_answers_sort_order"
        ),
    )

    clarification_answer_id: Mapped[str] = uuid_primary_key("clarification_answer_id")
    clarification_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clarification_requests.clarification_id", ondelete="CASCADE"),
        nullable=False,
    )
    question_code: Mapped[str] = mapped_column(String(100), nullable=False)
    question_text: Mapped[str | None] = mapped_column(Text)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    clarification_request: Mapped[ClarificationRequest] = relationship(back_populates="answers")


class GenerationRun(Base):
    __tablename__ = "generation_runs"
    __table_args__ = (
        Index("ix_generation_runs_task_started_at", "business_task_id", "started_at"),
        Index("ix_generation_runs_correlation_id", "correlation_id"),
        Index("ix_generation_runs_started_at", "started_at"),
        Index(
            "uq_generation_runs_active_per_task",
            "business_task_id",
            unique=True,
            postgresql_where=text("status NOT IN ('completed', 'failed', 'canceled')"),
        ),
    )

    generation_run_id: Mapped[str] = uuid_primary_key("generation_run_id")
    business_task_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_tasks.business_task_id"), nullable=False
    )
    knowledge_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_versions.knowledge_version_id"), nullable=False
    )
    started_by_user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[GenerationRunStatus] = enum_column(GenerationRunStatus)
    current_stage: Mapped[str | None] = mapped_column(String(50))
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    diagnostics: Mapped[dict | None] = mapped_column(JSONB)

    business_task: Mapped[BusinessTask] = relationship(back_populates="generation_runs")
    knowledge_version: Mapped[KnowledgeVersion] = relationship(back_populates="generation_runs")
    solution_version: Mapped[SolutionVersion | None] = relationship(back_populates="generation_run")


class SolutionVersion(Base):
    __tablename__ = "solution_versions"
    __table_args__ = (
        UniqueConstraint(
            "business_task_id", "version_no", name="uq_solution_versions_task_version"
        ),
    )

    solution_version_id: Mapped[str] = uuid_primary_key("solution_version_id")
    business_task_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_tasks.business_task_id"), nullable=False
    )
    generation_run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generation_runs.generation_run_id"),
        nullable=False,
        unique=True,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    solution_title: Mapped[str] = mapped_column(String(300), nullable=False)
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    rendered_markdown: Mapped[str | None] = mapped_column(Text)
    rendered_html: Mapped[str | None] = mapped_column(Text)
    status: Mapped[SolutionVersionStatus] = enum_column(SolutionVersionStatus)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    business_task: Mapped[BusinessTask] = relationship(back_populates="solution_versions")
    generation_run: Mapped[GenerationRun] = relationship(back_populates="solution_version")
    sections: Mapped[list[SolutionSection]] = relationship(back_populates="solution_version")
    section_assessments: Mapped[list[SolutionSectionAssessment]] = relationship(
        back_populates="solution_version"
    )
    architecture_entities: Mapped[list[SolutionArchitectureEntity]] = relationship(
        back_populates="solution_version"
    )
    architecture_relations: Mapped[list[SolutionArchitectureRelation]] = relationship(
        back_populates="solution_version"
    )
    components: Mapped[list[SolutionComponent]] = relationship(back_populates="solution_version")
    integrations: Mapped[list[SolutionIntegration]] = relationship(
        back_populates="solution_version"
    )
    list_items: Mapped[list[SolutionListItem]] = relationship(back_populates="solution_version")
    risks: Mapped[list[SolutionRisk]] = relationship(back_populates="solution_version")
    verification_runs: Mapped[list[VerificationRun]] = relationship(
        back_populates="solution_version"
    )


class SolutionSection(Base):
    __tablename__ = "solution_sections"
    __table_args__ = (
        UniqueConstraint("solution_version_id", "section_code", name="uq_solution_sections_code"),
        UniqueConstraint(
            "solution_version_id", "sort_order", name="uq_solution_sections_sort_order"
        ),
    )

    section_id: Mapped[str] = uuid_primary_key("section_id")
    solution_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("solution_versions.solution_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    section_code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    solution_version: Mapped[SolutionVersion] = relationship(back_populates="sections")
    source_refs: Mapped[list[SolutionSectionSourceRef]] = relationship(back_populates="section")


class SolutionSectionSourceRef(Base):
    __tablename__ = "solution_section_source_refs"
    __table_args__ = (
        UniqueConstraint(
            "section_id", "sort_order", name="uq_solution_section_source_refs_sort_order"
        ),
    )

    section_source_ref_id: Mapped[str] = uuid_primary_key("section_source_ref_id")
    section_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("solution_sections.section_id", ondelete="CASCADE"),
        nullable=False,
    )
    fragment_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_fragments.fragment_id")
    )
    document_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_documents.document_id")
    )
    quote_text: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    section: Mapped[SolutionSection] = relationship(back_populates="source_refs")
    fragment: Mapped[KnowledgeFragment | None] = relationship(back_populates="section_source_refs")
    document: Mapped[SourceDocument | None] = relationship(back_populates="section_source_refs")


class SolutionSectionAssessment(Base):
    __tablename__ = "solution_section_assessments"
    __table_args__ = (
        UniqueConstraint(
            "solution_version_id", "section_code", name="uq_solution_section_assessments_code"
        ),
        UniqueConstraint(
            "solution_version_id", "sort_order", name="uq_solution_section_assessments_sort_order"
        ),
    )

    section_assessment_id: Mapped[str] = uuid_primary_key("section_assessment_id")
    solution_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("solution_versions.solution_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    section_code: Mapped[str] = mapped_column(String(50), nullable=False)
    heading: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    score: Mapped[float] = mapped_column(nullable=False, default=0.0, server_default="0")
    observed_signal_groups: Mapped[list[str] | None] = mapped_column(JSONB)
    missing_signal_groups: Mapped[list[str] | None] = mapped_column(JSONB)
    reasons: Mapped[list[str] | None] = mapped_column(JSONB)
    allowed_archimate_elements: Mapped[list[str] | None] = mapped_column(JSONB)
    fallback_applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    details: Mapped[dict | None] = mapped_column(JSONB)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    solution_version: Mapped[SolutionVersion] = relationship(back_populates="section_assessments")


class SolutionArchitectureEntity(Base):
    __tablename__ = "solution_architecture_entities"
    __table_args__ = (
        UniqueConstraint(
            "solution_version_id", "entity_key", name="uq_solution_architecture_entities_key"
        ),
        UniqueConstraint(
            "solution_version_id", "sort_order", name="uq_solution_architecture_entities_sort_order"
        ),
    )

    architecture_entity_id: Mapped[str] = uuid_primary_key("architecture_entity_id")
    solution_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("solution_versions.solution_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_key: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(300), nullable=False)
    source_kind: Mapped[str | None] = mapped_column(String(50))
    section_code: Mapped[str | None] = mapped_column(String(50))
    archimate_layer: Mapped[str | None] = mapped_column(String(50))
    archimate_element_code: Mapped[str | None] = mapped_column(String(100))
    archimate_element_title: Mapped[str | None] = mapped_column(String(150))
    normalized_flag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    confidence: Mapped[float | None] = mapped_column()
    entity_metadata: Mapped[dict | None] = mapped_column(JSONB)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    solution_version: Mapped[SolutionVersion] = relationship(back_populates="architecture_entities")


class SolutionArchitectureRelation(Base):
    __tablename__ = "solution_architecture_relations"
    __table_args__ = (
        UniqueConstraint(
            "solution_version_id", "relation_key", name="uq_solution_architecture_relations_key"
        ),
        UniqueConstraint(
            "solution_version_id",
            "sort_order",
            name="uq_solution_architecture_relations_sort_order",
        ),
    )

    architecture_relation_id: Mapped[str] = uuid_primary_key("architecture_relation_id")
    solution_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("solution_versions.solution_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_key: Mapped[str] = mapped_column(String(200), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source_entity_key: Mapped[str | None] = mapped_column(String(200))
    target_entity_key: Mapped[str | None] = mapped_column(String(200))
    section_code: Mapped[str | None] = mapped_column(String(50))
    normalized_flag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    confidence: Mapped[float | None] = mapped_column()
    relation_metadata: Mapped[dict | None] = mapped_column(JSONB)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    solution_version: Mapped[SolutionVersion] = relationship(
        back_populates="architecture_relations"
    )


class SolutionComponent(Base):
    __tablename__ = "solution_components"
    __table_args__ = (
        UniqueConstraint(
            "solution_version_id", "component_name", name="uq_solution_components_name"
        ),
        UniqueConstraint(
            "solution_version_id", "sort_order", name="uq_solution_components_sort_order"
        ),
    )

    component_id: Mapped[str] = uuid_primary_key("component_id")
    solution_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("solution_versions.solution_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    component_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role_description: Mapped[str] = mapped_column(Text, nullable=False)
    technology_stack: Mapped[str | None] = mapped_column(Text)
    boundary_type: Mapped[str | None] = mapped_column(String(100))
    external_flag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    solution_version: Mapped[SolutionVersion] = relationship(back_populates="components")
    interfaces: Mapped[list[SolutionComponentInterface]] = relationship(back_populates="component")
    outgoing_integrations: Mapped[list[SolutionIntegration]] = relationship(
        back_populates="from_component",
        foreign_keys="SolutionIntegration.from_component_id",
    )
    incoming_integrations: Mapped[list[SolutionIntegration]] = relationship(
        back_populates="to_component",
        foreign_keys="SolutionIntegration.to_component_id",
    )


class SolutionComponentInterface(Base):
    __tablename__ = "solution_component_interfaces"
    __table_args__ = (
        UniqueConstraint(
            "component_id", "interface_name", name="uq_solution_component_interfaces_name"
        ),
        UniqueConstraint(
            "component_id", "sort_order", name="uq_solution_component_interfaces_sort_order"
        ),
    )

    interface_id: Mapped[str] = uuid_primary_key("interface_id")
    component_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("solution_components.component_id", ondelete="CASCADE"),
        nullable=False,
    )
    interface_name: Mapped[str] = mapped_column(String(200), nullable=False)
    protocol: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    component: Mapped[SolutionComponent] = relationship(back_populates="interfaces")


class SolutionIntegration(Base):
    __tablename__ = "solution_integrations"
    __table_args__ = (
        UniqueConstraint(
            "solution_version_id", "sort_order", name="uq_solution_integrations_sort_order"
        ),
    )

    integration_id: Mapped[str] = uuid_primary_key("integration_id")
    solution_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("solution_versions.solution_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    from_component_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("solution_components.component_id"), nullable=False
    )
    to_component_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("solution_components.component_id"), nullable=False
    )
    interaction: Mapped[str] = mapped_column(Text, nullable=False)
    protocol: Mapped[str | None] = mapped_column(String(100))
    rationale: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    solution_version: Mapped[SolutionVersion] = relationship(back_populates="integrations")
    from_component: Mapped[SolutionComponent] = relationship(
        back_populates="outgoing_integrations",
        foreign_keys=[from_component_id],
    )
    to_component: Mapped[SolutionComponent] = relationship(
        back_populates="incoming_integrations",
        foreign_keys=[to_component_id],
    )


class SolutionListItem(Base):
    __tablename__ = "solution_list_items"
    __table_args__ = (
        UniqueConstraint(
            "solution_version_id", "item_group", "sort_order", name="uq_solution_list_items_scope"
        ),
    )

    solution_list_item_id: Mapped[str] = uuid_primary_key("solution_list_item_id")
    solution_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("solution_versions.solution_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    item_group: Mapped[SolutionListItemGroup] = enum_column(SolutionListItemGroup)
    item_text: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    solution_version: Mapped[SolutionVersion] = relationship(back_populates="list_items")


class SolutionRisk(Base):
    __tablename__ = "solution_risks"
    __table_args__ = (
        UniqueConstraint("solution_version_id", "sort_order", name="uq_solution_risks_sort_order"),
    )

    risk_id: Mapped[str] = uuid_primary_key("risk_id")
    solution_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("solution_versions.solution_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    severity: Mapped[Severity] = enum_column(Severity)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    mitigation: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    solution_version: Mapped[SolutionVersion] = relationship(back_populates="risks")
