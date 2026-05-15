"""core mvp baseline

Revision ID: 20260328_0001
Revises: 20260326_0009
Create Date: 2026-03-28 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from alembic import op

try:
    from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
except Exception:  # pragma: no cover

    def Vector(dimensions: int):
        return postgresql.ARRAY(sa.Float())


revision = "20260328_0001"
down_revision = "20260326_0009"
branch_labels = None
depends_on = None


def _drop_schema_views(bind) -> None:
    regular_views = (
        bind.execute(
            text(
                """
            SELECT table_name
            FROM information_schema.views
            WHERE table_schema = current_schema()
            ORDER BY table_name
            """
            )
        )
        .scalars()
        .all()
    )

    for view_name in regular_views:
        bind.execute(text(f'DROP VIEW IF EXISTS "{view_name}" CASCADE'))

    materialized_views = (
        bind.execute(
            text(
                """
            SELECT matviewname
            FROM pg_matviews
            WHERE schemaname = current_schema()
            ORDER BY matviewname
            """
            )
        )
        .scalars()
        .all()
    )

    for matview_name in materialized_views:
        bind.execute(text(f'DROP MATERIALIZED VIEW IF EXISTS "{matview_name}" CASCADE'))


def _drop_schema_tables(bind) -> None:
    table_names = (
        bind.execute(
            text(
                """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = current_schema()
              AND tablename <> 'alembic_version'
            ORDER BY tablename
            """
            )
        )
        .scalars()
        .all()
    )

    for table_name in table_names:
        bind.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))


def _table_exists(bind, table_name: str) -> bool:
    return bool(
        bind.execute(
            text(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
                """
            ),
            {"table_name": table_name},
        ).scalar_one_or_none()
    )


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    bind.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    if not _table_exists(bind, "audit_events"):
        op.create_table(
            "audit_events",
            sa.Column(
                "audit_event_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "event_time",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("event_type", sa.String(length=100), nullable=False),
            sa.Column("actor_user_id", sa.String(length=100), nullable=True),
            sa.Column("target_type", sa.String(length=100), nullable=False),
            sa.Column("target_id", sa.String(length=64), nullable=False),
            sa.Column("severity", sa.String(length=20), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("correlation_id", sa.String(length=100), nullable=True),
        )

    if not _table_exists(bind, "idempotency_records"):
        op.create_table(
            "idempotency_records",
            sa.Column(
                "idempotency_record_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("actor_user_id", sa.String(length=100), nullable=False),
            sa.Column("operation_name", sa.String(length=100), nullable=False),
            sa.Column("idempotency_key", sa.String(length=100), nullable=False),
            sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("target_type", sa.String(length=50), nullable=False),
            sa.Column("target_id", sa.String(length=100), nullable=False),
            sa.Column("correlation_id", sa.String(length=100), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "last_seen_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint(
                "actor_user_id",
                "operation_name",
                "idempotency_key",
                name="uq_idempotency_actor_operation_key",
            ),
        )

    if not _table_exists(bind, "business_tasks"):
        op.create_table(
            "business_tasks",
            sa.Column(
                "business_task_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("created_by_user_id", sa.String(length=100), nullable=False),
            sa.Column("title", sa.String(length=300), nullable=True),
            sa.Column("task_text", sa.Text(), nullable=False),
            sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    if not _table_exists(bind, "clarification_requests"):
        op.create_table(
            "clarification_requests",
            sa.Column(
                "clarification_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "business_task_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("business_tasks.business_task_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("state", sa.String(length=30), nullable=False),
            sa.Column("question_items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _table_exists(bind, "clarification_answers"):
        op.create_table(
            "clarification_answers",
            sa.Column(
                "clarification_answer_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "clarification_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("clarification_requests.clarification_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("question_code", sa.String(length=100), nullable=False),
            sa.Column("question_text", sa.Text(), nullable=True),
            sa.Column("answer_text", sa.Text(), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint(
                "clarification_id", "sort_order", name="uq_clarification_answers_sort_order"
            ),
        )

    if not _table_exists(bind, "knowledge_sources"):
        op.create_table(
            "knowledge_sources",
            sa.Column(
                "source_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("source_type", sa.String(length=30), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("base_uri", sa.String(length=1000), nullable=True),
            sa.Column("criticality", sa.String(length=30), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("refresh_policy", sa.String(length=200), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    if not _table_exists(bind, "source_documents"):
        op.create_table(
            "source_documents",
            sa.Column(
                "document_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "source_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("knowledge_sources.source_id"),
                nullable=False,
            ),
            sa.Column("document_type", sa.String(length=30), nullable=False),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("uri", sa.String(length=2000), nullable=False),
            sa.Column("version_label", sa.String(length=100), nullable=True),
            sa.Column("checksum", sa.String(length=128), nullable=True),
            sa.Column("is_latest", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column(
                "registered_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint("source_id", "uri", name="uq_source_documents_source_uri"),
        )

    if not _table_exists(bind, "knowledge_update_runs"):
        op.create_table(
            "knowledge_update_runs",
            sa.Column(
                "update_run_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("run_type", sa.String(length=30), nullable=False),
            sa.Column("initiator_user_id", sa.String(length=100), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("current_stage", sa.String(length=50), nullable=True),
            sa.Column("scope", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("correlation_id", sa.String(length=100), nullable=True),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_sec", sa.Integer(), nullable=True),
            sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )

    if not _table_exists(bind, "source_processing_results"):
        op.create_table(
            "source_processing_results",
            sa.Column(
                "processing_result_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "update_run_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("knowledge_update_runs.update_run_id"),
                nullable=False,
            ),
            sa.Column(
                "source_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("knowledge_sources.source_id"),
                nullable=False,
            ),
            sa.Column(
                "document_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("source_documents.document_id"),
                nullable=True,
            ),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("error_code", sa.String(length=100), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column(
                "processed_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    if not _table_exists(bind, "knowledge_versions"):
        op.create_table(
            "knowledge_versions",
            sa.Column(
                "knowledge_version_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("version_no", sa.String(length=50), nullable=False, unique=True),
            sa.Column(
                "update_run_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("knowledge_update_runs.update_run_id"),
                nullable=False,
            ),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("source_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column(
                "activation_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True
            ),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("activated_by_user_id", sa.String(length=100), nullable=True),
        )
        op.create_index(
            "uq_knowledge_versions_active_only",
            "knowledge_versions",
            ["status"],
            unique=True,
            postgresql_where=sa.text("status = 'active'"),
        )

    if not _table_exists(bind, "knowledge_version_documents"):
        op.create_table(
            "knowledge_version_documents",
            sa.Column(
                "version_document_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "knowledge_version_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("knowledge_versions.knowledge_version_id"),
                nullable=False,
            ),
            sa.Column(
                "document_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("source_documents.document_id"),
                nullable=False,
            ),
            sa.Column(
                "role_code", sa.String(length=100), nullable=False, server_default="reference_only"
            ),
            sa.Column(
                "required_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column(
                "included_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint(
                "knowledge_version_id", "document_id", name="uq_knowledge_version_documents_scope"
            ),
        )

    if not _table_exists(bind, "knowledge_fragments"):
        op.create_table(
            "knowledge_fragments",
            sa.Column(
                "fragment_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "knowledge_version_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("knowledge_versions.knowledge_version_id"),
                nullable=False,
            ),
            sa.Column(
                "document_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("source_documents.document_id"),
                nullable=False,
            ),
            sa.Column("fragment_type", sa.String(length=30), nullable=False),
            sa.Column("title", sa.String(length=500), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("source_location", sa.String(length=200), nullable=True),
            sa.Column("fragment_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("embedding_key", sa.String(length=255), nullable=True),
            sa.Column("embedding", Vector(16), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    if not _table_exists(bind, "normative_rules"):
        op.create_table(
            "normative_rules",
            sa.Column(
                "rule_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "knowledge_version_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("knowledge_versions.knowledge_version_id"),
                nullable=False,
            ),
            sa.Column(
                "document_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("source_documents.document_id"),
                nullable=False,
            ),
            sa.Column("rule_code", sa.String(length=100), nullable=False),
            sa.Column("rule_name", sa.String(length=300), nullable=False),
            sa.Column("rule_text", sa.Text(), nullable=False),
            sa.Column("rule_category", sa.String(length=30), nullable=False),
            sa.Column(
                "applicability_condition", postgresql.JSONB(astext_type=sa.Text()), nullable=True
            ),
            sa.Column("severity_default", sa.String(length=20), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.UniqueConstraint(
                "knowledge_version_id", "rule_code", name="uq_normative_rules_version_code"
            ),
        )

    if not _table_exists(bind, "generation_runs"):
        op.create_table(
            "generation_runs",
            sa.Column(
                "generation_run_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "business_task_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("business_tasks.business_task_id"),
                nullable=False,
            ),
            sa.Column(
                "knowledge_version_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("knowledge_versions.knowledge_version_id"),
                nullable=False,
            ),
            sa.Column("started_by_user_id", sa.String(length=100), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("current_stage", sa.String(length=50), nullable=True),
            sa.Column("correlation_id", sa.String(length=100), nullable=True),
            sa.Column("prompt_version", sa.String(length=100), nullable=True),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("input_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )

    if not _table_exists(bind, "solution_versions"):
        op.create_table(
            "solution_versions",
            sa.Column(
                "solution_version_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "business_task_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("business_tasks.business_task_id"),
                nullable=False,
            ),
            sa.Column(
                "generation_run_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("generation_runs.generation_run_id"),
                nullable=False,
                unique=True,
            ),
            sa.Column("version_no", sa.Integer(), nullable=False),
            sa.Column("solution_title", sa.String(length=300), nullable=False),
            sa.Column("executive_summary", sa.Text(), nullable=False),
            sa.Column("rendered_markdown", sa.Text(), nullable=True),
            sa.Column("rendered_html", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "business_task_id", "version_no", name="uq_solution_versions_task_version"
            ),
        )

    if not _table_exists(bind, "solution_sections"):
        op.create_table(
            "solution_sections",
            sa.Column(
                "section_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "solution_version_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("solution_versions.solution_version_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("section_code", sa.String(length=50), nullable=False),
            sa.Column("title", sa.String(length=300), nullable=False),
            sa.Column("body_markdown", sa.Text(), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.UniqueConstraint(
                "solution_version_id", "section_code", name="uq_solution_sections_code"
            ),
            sa.UniqueConstraint(
                "solution_version_id", "sort_order", name="uq_solution_sections_sort_order"
            ),
        )

    if not _table_exists(bind, "solution_section_source_refs"):
        op.create_table(
            "solution_section_source_refs",
            sa.Column(
                "section_source_ref_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "section_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("solution_sections.section_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "fragment_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("knowledge_fragments.fragment_id"),
                nullable=True,
            ),
            sa.Column(
                "document_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("source_documents.document_id"),
                nullable=True,
            ),
            sa.Column("quote_text", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.UniqueConstraint(
                "section_id", "sort_order", name="uq_solution_section_source_refs_sort_order"
            ),
        )

    if not _table_exists(bind, "solution_components"):
        op.create_table(
            "solution_components",
            sa.Column(
                "component_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "solution_version_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("solution_versions.solution_version_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("component_name", sa.String(length=200), nullable=False),
            sa.Column("role_description", sa.Text(), nullable=False),
            sa.Column("technology_stack", sa.Text(), nullable=True),
            sa.Column("boundary_type", sa.String(length=100), nullable=True),
            sa.Column(
                "external_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.UniqueConstraint(
                "solution_version_id", "component_name", name="uq_solution_components_name"
            ),
            sa.UniqueConstraint(
                "solution_version_id", "sort_order", name="uq_solution_components_sort_order"
            ),
        )

    if not _table_exists(bind, "solution_component_interfaces"):
        op.create_table(
            "solution_component_interfaces",
            sa.Column(
                "interface_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "component_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("solution_components.component_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("interface_name", sa.String(length=200), nullable=False),
            sa.Column("protocol", sa.String(length=100), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.UniqueConstraint(
                "component_id", "interface_name", name="uq_solution_component_interfaces_name"
            ),
            sa.UniqueConstraint(
                "component_id", "sort_order", name="uq_solution_component_interfaces_sort_order"
            ),
        )

    if not _table_exists(bind, "solution_integrations"):
        op.create_table(
            "solution_integrations",
            sa.Column(
                "integration_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "solution_version_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("solution_versions.solution_version_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "from_component_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("solution_components.component_id"),
                nullable=False,
            ),
            sa.Column(
                "to_component_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("solution_components.component_id"),
                nullable=False,
            ),
            sa.Column("interaction", sa.Text(), nullable=False),
            sa.Column("protocol", sa.String(length=100), nullable=True),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.UniqueConstraint(
                "solution_version_id", "sort_order", name="uq_solution_integrations_sort_order"
            ),
        )

    if not _table_exists(bind, "solution_list_items"):
        op.create_table(
            "solution_list_items",
            sa.Column(
                "solution_list_item_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "solution_version_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("solution_versions.solution_version_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("item_group", sa.String(length=30), nullable=False),
            sa.Column("item_text", sa.Text(), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.UniqueConstraint(
                "solution_version_id",
                "item_group",
                "sort_order",
                name="uq_solution_list_items_scope",
            ),
        )

    if not _table_exists(bind, "solution_risks"):
        op.create_table(
            "solution_risks",
            sa.Column(
                "risk_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "solution_version_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("solution_versions.solution_version_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("title", sa.String(length=300), nullable=False),
            sa.Column("severity", sa.String(length=20), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("mitigation", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.UniqueConstraint(
                "solution_version_id", "sort_order", name="uq_solution_risks_sort_order"
            ),
        )

    if not _table_exists(bind, "verification_runs"):
        op.create_table(
            "verification_runs",
            sa.Column(
                "verification_run_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "solution_version_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("solution_versions.solution_version_id"),
                nullable=False,
            ),
            sa.Column(
                "knowledge_version_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("knowledge_versions.knowledge_version_id"),
                nullable=False,
            ),
            sa.Column("started_by_user_id", sa.String(length=100), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("current_stage", sa.String(length=50), nullable=True),
            sa.Column("correlation_id", sa.String(length=100), nullable=True),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("scope_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )

    if not _table_exists(bind, "verification_protocols"):
        op.create_table(
            "verification_protocols",
            sa.Column(
                "verification_protocol_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "verification_run_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("verification_runs.verification_run_id"),
                nullable=False,
                unique=True,
            ),
            sa.Column("protocol_no", sa.String(length=100), nullable=True),
            sa.Column("summary_status", sa.String(length=30), nullable=False),
            sa.Column("summary_text", sa.Text(), nullable=False),
            sa.Column(
                "issued_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("status", sa.String(length=30), nullable=False),
        )

    if not _table_exists(bind, "verification_basis_documents"):
        op.create_table(
            "verification_basis_documents",
            sa.Column(
                "protocol_basis_document_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "verification_protocol_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey(
                    "verification_protocols.verification_protocol_id", ondelete="CASCADE"
                ),
                nullable=False,
            ),
            sa.Column(
                "document_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("source_documents.document_id"),
                nullable=True,
            ),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("role_code", sa.String(length=100), nullable=True),
            sa.Column("version_ref", sa.String(length=100), nullable=True),
            sa.Column(
                "required_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.UniqueConstraint(
                "verification_protocol_id",
                "sort_order",
                name="uq_verification_basis_documents_sort_order",
            ),
        )

    if not _table_exists(bind, "check_results"):
        op.create_table(
            "check_results",
            sa.Column(
                "check_result_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "verification_protocol_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey(
                    "verification_protocols.verification_protocol_id", ondelete="CASCADE"
                ),
                nullable=False,
            ),
            sa.Column(
                "rule_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("normative_rules.rule_id"),
                nullable=True,
            ),
            sa.Column("rule_name", sa.String(length=300), nullable=True),
            sa.Column("check_name", sa.String(length=300), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("severity", sa.String(length=20), nullable=False),
            sa.Column("finding_text", sa.Text(), nullable=True),
            sa.Column("evidence_ref", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column(
                "is_technical_check", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.UniqueConstraint(
                "verification_protocol_id", "sort_order", name="uq_check_results_sort_order"
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    _drop_schema_views(bind)
    _drop_schema_tables(bind)
