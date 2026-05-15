"""database hardening for run uniqueness, lookup indexes, and vector search

Revision ID: 20260404_0015
Revises: 20260403_0014
Create Date: 2026-04-04 03:40:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

revision = "20260404_0015"
down_revision = "20260403_0014"
branch_labels = None
depends_on = None


def _index_exists(bind, index_name: str) -> bool:
    return bool(
        bind.execute(
            text(
                """
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND indexname = :index_name
                """
            ),
            {"index_name": index_name},
        ).scalar_one_or_none()
    )


def _constraint_exists(bind, table_name: str, constraint_name: str) -> bool:
    return bool(
        bind.execute(
            text(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
                  AND constraint_name = :constraint_name
                """
            ),
            {"table_name": table_name, "constraint_name": constraint_name},
        ).scalar_one_or_none()
    )


def _delete_duplicate_knowledge_versions(bind) -> None:
    bind.execute(
        text(
            """
            DELETE FROM knowledge_versions AS kv
            USING (
                SELECT knowledge_version_id
                FROM (
                    SELECT knowledge_version_id,
                           row_number() OVER (
                               PARTITION BY update_run_id
                               ORDER BY created_at DESC, knowledge_version_id DESC
                           ) AS row_no
                    FROM knowledge_versions
                ) AS ranked
                WHERE ranked.row_no > 1
            ) AS duplicates
            WHERE kv.knowledge_version_id = duplicates.knowledge_version_id
            """
        )
    )


def upgrade() -> None:
    bind = op.get_bind()

    if not _index_exists(bind, "ix_generation_runs_task_started_at"):
        op.create_index(
            "ix_generation_runs_task_started_at",
            "generation_runs",
            ["business_task_id", "started_at"],
        )
    if not _index_exists(bind, "ix_generation_runs_correlation_id"):
        op.create_index("ix_generation_runs_correlation_id", "generation_runs", ["correlation_id"])
    if not _index_exists(bind, "ix_generation_runs_started_at"):
        op.create_index("ix_generation_runs_started_at", "generation_runs", ["started_at"])
    if not _index_exists(bind, "uq_generation_runs_active_per_task"):
        op.create_index(
            "uq_generation_runs_active_per_task",
            "generation_runs",
            ["business_task_id"],
            unique=True,
            postgresql_where=sa.text("status NOT IN ('completed', 'failed', 'canceled')"),
        )

    if not _index_exists(bind, "ix_verification_runs_solution_started_at"):
        op.create_index(
            "ix_verification_runs_solution_started_at",
            "verification_runs",
            ["solution_version_id", "started_at"],
        )
    if not _index_exists(bind, "ix_verification_runs_correlation_id"):
        op.create_index(
            "ix_verification_runs_correlation_id", "verification_runs", ["correlation_id"]
        )
    if not _index_exists(bind, "ix_verification_runs_started_at"):
        op.create_index("ix_verification_runs_started_at", "verification_runs", ["started_at"])
    if not _index_exists(bind, "uq_verification_runs_active_per_solution"):
        op.create_index(
            "uq_verification_runs_active_per_solution",
            "verification_runs",
            ["solution_version_id"],
            unique=True,
            postgresql_where=sa.text("status NOT IN ('completed', 'failed', 'canceled')"),
        )

    if not _index_exists(bind, "ix_knowledge_update_runs_knowledge_base_started_at"):
        op.create_index(
            "ix_knowledge_update_runs_knowledge_base_started_at",
            "knowledge_update_runs",
            ["knowledge_base_id", "started_at"],
        )
    if not _index_exists(bind, "ix_knowledge_update_runs_correlation_id"):
        op.create_index(
            "ix_knowledge_update_runs_correlation_id", "knowledge_update_runs", ["correlation_id"]
        )
    if not _index_exists(bind, "ix_knowledge_update_runs_status_started_at"):
        op.create_index(
            "ix_knowledge_update_runs_status_started_at",
            "knowledge_update_runs",
            ["status", "started_at"],
        )
    if not _index_exists(bind, "ix_knowledge_update_runs_started_at"):
        op.create_index(
            "ix_knowledge_update_runs_started_at", "knowledge_update_runs", ["started_at"]
        )
    if not _index_exists(bind, "uq_knowledge_update_runs_active_per_base"):
        op.create_index(
            "uq_knowledge_update_runs_active_per_base",
            "knowledge_update_runs",
            ["knowledge_base_id"],
            unique=True,
            postgresql_where=sa.text(
                "status NOT IN ('completed', 'completed_with_warnings', 'failed', 'canceled')"
            ),
        )

    if not _index_exists(bind, "ix_knowledge_sources_knowledge_base_created_at"):
        op.create_index(
            "ix_knowledge_sources_knowledge_base_created_at",
            "knowledge_sources",
            ["knowledge_base_id", "created_at"],
        )
    if not _index_exists(bind, "ix_source_documents_source_registered_at"):
        op.create_index(
            "ix_source_documents_source_registered_at",
            "source_documents",
            ["source_id", "registered_at"],
        )

    if not _index_exists(bind, "ix_source_processing_results_update_run_id"):
        op.create_index(
            "ix_source_processing_results_update_run_id",
            "source_processing_results",
            ["update_run_id"],
        )
    if not _index_exists(bind, "ix_source_processing_results_source_processed_at"):
        op.create_index(
            "ix_source_processing_results_source_processed_at",
            "source_processing_results",
            ["source_id", "processed_at"],
        )
    if not _index_exists(bind, "ix_source_processing_results_document_processed_at"):
        op.create_index(
            "ix_source_processing_results_document_processed_at",
            "source_processing_results",
            ["document_id", "processed_at"],
        )

    _delete_duplicate_knowledge_versions(bind)
    if not _constraint_exists(bind, "knowledge_versions", "uq_knowledge_versions_update_run_id"):
        op.create_unique_constraint(
            "uq_knowledge_versions_update_run_id", "knowledge_versions", ["update_run_id"]
        )

    if not _index_exists(bind, "ix_knowledge_fragments_embedding_hnsw"):
        vector_extension = bind.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one_or_none()
        embedding_udt = bind.execute(
            text(
                """
                SELECT udt_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'knowledge_fragments'
                  AND column_name = 'embedding'
                """
            )
        ).scalar_one_or_none()
        if vector_extension and embedding_udt == "vector":
            bind.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_knowledge_fragments_embedding_hnsw "
                    "ON knowledge_fragments USING hnsw (embedding vector_cosine_ops)"
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    for table_name, index_name in (
        ("generation_runs", "uq_generation_runs_active_per_task"),
        ("generation_runs", "ix_generation_runs_started_at"),
        ("generation_runs", "ix_generation_runs_correlation_id"),
        ("generation_runs", "ix_generation_runs_task_started_at"),
        ("verification_runs", "uq_verification_runs_active_per_solution"),
        ("verification_runs", "ix_verification_runs_started_at"),
        ("verification_runs", "ix_verification_runs_correlation_id"),
        ("verification_runs", "ix_verification_runs_solution_started_at"),
        ("knowledge_update_runs", "uq_knowledge_update_runs_active_per_base"),
        ("knowledge_update_runs", "ix_knowledge_update_runs_started_at"),
        ("knowledge_update_runs", "ix_knowledge_update_runs_status_started_at"),
        ("knowledge_update_runs", "ix_knowledge_update_runs_correlation_id"),
        ("knowledge_update_runs", "ix_knowledge_update_runs_knowledge_base_started_at"),
        ("knowledge_sources", "ix_knowledge_sources_knowledge_base_created_at"),
        ("source_documents", "ix_source_documents_source_registered_at"),
        ("source_processing_results", "ix_source_processing_results_document_processed_at"),
        ("source_processing_results", "ix_source_processing_results_source_processed_at"),
        ("source_processing_results", "ix_source_processing_results_update_run_id"),
    ):
        op.drop_index(index_name, table_name=table_name, if_exists=True)

    if _constraint_exists(bind, "knowledge_versions", "uq_knowledge_versions_update_run_id"):
        op.drop_constraint(
            "uq_knowledge_versions_update_run_id", "knowledge_versions", type_="unique"
        )
    bind.execute(text("DROP INDEX IF EXISTS ix_knowledge_fragments_embedding_hnsw"))
