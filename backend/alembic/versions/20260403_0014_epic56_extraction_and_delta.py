"""document memory extraction and incremental delta storage for epics 5/6

Revision ID: 20260403_0014
Revises: 20260403_0013
Create Date: 2026-04-03 15:45:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260403_0014"
down_revision = "20260403_0013"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name: str) -> bool:
    return bool(
        bind.execute(
            sa.text(
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

    if not _table_exists(bind, "document_extracted_items"):
        op.create_table(
            "document_extracted_items",
            sa.Column(
                "extracted_item_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "knowledge_version_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("knowledge_versions.knowledge_version_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "document_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("source_documents.document_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "document_chunk_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("document_chunks.document_chunk_id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("item_type", sa.String(length=50), nullable=False),
            sa.Column("title", sa.String(length=500), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("normalized_value", sa.String(length=500), nullable=True),
            sa.Column("source_location", sa.String(length=200), nullable=True),
            sa.Column("confidence_score", sa.Float(), nullable=True),
            sa.Column("quality_status", sa.String(length=30), nullable=False),
            sa.Column("evidence_quote", sa.Text(), nullable=True),
            sa.Column("structured_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index(
            "ix_document_extracted_items_knowledge_version_id",
            "document_extracted_items",
            ["knowledge_version_id"],
        )
        op.create_index(
            "ix_document_extracted_items_document_id", "document_extracted_items", ["document_id"]
        )

    if not _table_exists(bind, "document_deltas"):
        op.create_table(
            "document_deltas",
            sa.Column(
                "document_delta_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "update_run_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("knowledge_update_runs.update_run_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "knowledge_base_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("knowledge_bases.knowledge_base_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "knowledge_version_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("knowledge_versions.knowledge_version_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "source_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("knowledge_sources.source_id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "document_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("source_documents.document_id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("delta_kind", sa.String(length=30), nullable=False),
            sa.Column("uri", sa.String(length=2000), nullable=True),
            sa.Column("checksum_before", sa.String(length=128), nullable=True),
            sa.Column("checksum_after", sa.String(length=128), nullable=True),
            sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index("ix_document_deltas_update_run_id", "document_deltas", ["update_run_id"])
        op.create_index(
            "ix_document_deltas_knowledge_version_id", "document_deltas", ["knowledge_version_id"]
        )


def downgrade() -> None:
    op.drop_index(
        "ix_document_deltas_knowledge_version_id", table_name="document_deltas", if_exists=True
    )
    op.drop_index("ix_document_deltas_update_run_id", table_name="document_deltas", if_exists=True)
    op.drop_table("document_deltas", if_exists=True)
    op.drop_index(
        "ix_document_extracted_items_document_id",
        table_name="document_extracted_items",
        if_exists=True,
    )
    op.drop_index(
        "ix_document_extracted_items_knowledge_version_id",
        table_name="document_extracted_items",
        if_exists=True,
    )
    op.drop_table("document_extracted_items", if_exists=True)
