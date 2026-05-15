"""manual upload source uniqueness

Revision ID: 20260406_0020
Revises: 20260405_0019
Create Date: 2026-04-06
"""

from __future__ import annotations

from sqlalchemy import text

from alembic import op

revision = "20260406_0020"
down_revision = "20260405_0019"
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


def _deduplicate_manual_upload_sources(bind) -> None:
    bind.execute(
        text(
            """
            WITH ranked AS (
                SELECT source_id,
                       row_number() OVER (
                           PARTITION BY knowledge_base_id
                           ORDER BY created_at ASC, source_id ASC
                       ) AS row_no
                FROM knowledge_sources
                WHERE source_type = 'manual_upload'
            ), duplicates AS (
                SELECT source_id
                FROM ranked
                WHERE row_no > 1
            )
            DELETE FROM knowledge_sources ks
            USING duplicates d
            WHERE ks.source_id = d.source_id
            """
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    _deduplicate_manual_upload_sources(bind)
    if not _index_exists(bind, "uq_knowledge_sources_manual_upload_per_base"):
        bind.execute(
            text(
                "CREATE UNIQUE INDEX uq_knowledge_sources_manual_upload_per_base "
                "ON knowledge_sources (knowledge_base_id, source_type) "
                "WHERE source_type = 'manual_upload'"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP INDEX IF EXISTS uq_knowledge_sources_manual_upload_per_base"))
