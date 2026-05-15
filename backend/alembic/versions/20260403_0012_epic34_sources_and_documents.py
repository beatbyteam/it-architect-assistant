"""source discovery and normalized document storage for epics 3/4

Revision ID: 20260403_0012
Revises: 20260403_0011
Create Date: 2026-04-03 13:30:00.000000
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260403_0012"
down_revision = "20260403_0011"
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


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    return bool(
        bind.execute(
            sa.text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
                  AND column_name = :column_name
                """
            ),
            {"table_name": table_name, "column_name": column_name},
        ).scalar_one_or_none()
    )


def upgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "knowledge_sources"):
        if not _column_exists(bind, "knowledge_sources", "sync_mode"):
            op.add_column(
                "knowledge_sources",
                sa.Column(
                    "sync_mode", sa.String(length=30), nullable=False, server_default="full_scan"
                ),
            )
        if not _column_exists(bind, "knowledge_sources", "source_metadata"):
            op.add_column(
                "knowledge_sources",
                sa.Column(
                    "source_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True
                ),
            )
        if not _column_exists(bind, "knowledge_sources", "last_discovered_at"):
            op.add_column(
                "knowledge_sources",
                sa.Column("last_discovered_at", sa.DateTime(timezone=True), nullable=True),
            )

    if _table_exists(bind, "source_documents"):
        additions: list[tuple[str, sa.Column[Any]]] = [
            ("media_type", sa.Column("media_type", sa.String(length=200), nullable=True)),
            ("size_bytes", sa.Column("size_bytes", sa.Integer(), nullable=True)),
            ("resolved_uri", sa.Column("resolved_uri", sa.String(length=2000), nullable=True)),
            ("fetched_at", sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True)),
            (
                "discovered_at",
                sa.Column(
                    "discovered_at",
                    sa.DateTime(timezone=True),
                    nullable=True,
                    server_default=sa.text("now()"),
                ),
            ),
            (
                "document_metadata",
                sa.Column(
                    "document_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True
                ),
            ),
        ]
        for name, column in additions:
            if not _column_exists(bind, "source_documents", name):
                op.add_column("source_documents", column)

    if not _table_exists(bind, "document_snapshots"):
        op.create_table(
            "document_snapshots",
            sa.Column(
                "document_snapshot_id",
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
            sa.Column("checksum", sa.String(length=128), nullable=True),
            sa.Column("content_format", sa.String(length=50), nullable=False),
            sa.Column("parser_name", sa.String(length=100), nullable=False),
            sa.Column("normalized_text", sa.Text(), nullable=False),
            sa.Column("structure_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint(
                "knowledge_version_id", "document_id", name="uq_document_snapshots_version_document"
            ),
        )

    if not _table_exists(bind, "document_chunks"):
        op.create_table(
            "document_chunks",
            sa.Column(
                "document_chunk_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "document_snapshot_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("document_snapshots.document_snapshot_id", ondelete="CASCADE"),
                nullable=False,
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
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=500), nullable=True),
            sa.Column("source_location", sa.String(length=200), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("start_offset", sa.Integer(), nullable=True),
            sa.Column("end_offset", sa.Integer(), nullable=True),
            sa.Column("chunk_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint(
                "document_snapshot_id", "chunk_index", name="uq_document_chunks_snapshot_idx"
            ),
        )


def downgrade() -> None:
    op.drop_table("document_chunks", if_exists=True)
    op.drop_table("document_snapshots", if_exists=True)
    for table, columns in {
        "source_documents": [
            "document_metadata",
            "discovered_at",
            "fetched_at",
            "resolved_uri",
            "size_bytes",
            "media_type",
        ],
        "knowledge_sources": ["last_discovered_at", "source_metadata", "sync_mode"],
    }.items():
        for column in columns:
            op.drop_column(table, column, if_exists=True)
