"""knowledge integrity repairs and embedding dimension alignment

Revision ID: 20260404_0018
Revises: 20260404_0017
Create Date: 2026-04-04 13:35:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20260404_0018"
down_revision = "20260404_0017"
branch_labels = None
depends_on = None


def _constraint_exists(bind, constraint_name: str) -> bool:
    return bool(
        bind.execute(
            text(
                """
                SELECT 1
                FROM pg_constraint
                WHERE conname = :constraint_name
                """
            ),
            {"constraint_name": constraint_name},
        ).scalar_one_or_none()
    )


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


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    return bool(
        bind.execute(
            text(
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

    bind.execute(
        text("""
        UPDATE knowledge_base_selections kbs
        SET selected_knowledge_version_id = NULL
        WHERE selected_knowledge_version_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM knowledge_versions kv
              WHERE kv.knowledge_version_id = kbs.selected_knowledge_version_id
                AND kv.knowledge_base_id = kbs.selected_knowledge_base_id
          )
    """)
    )

    bind.execute(
        text("""
        UPDATE document_chunks dc
        SET knowledge_version_id = ds.knowledge_version_id,
            document_id = ds.document_id
        FROM document_snapshots ds
        WHERE ds.document_snapshot_id = dc.document_snapshot_id
          AND (
              dc.knowledge_version_id IS DISTINCT FROM ds.knowledge_version_id
              OR dc.document_id IS DISTINCT FROM ds.document_id
          )
    """)
    )

    if _column_exists(bind, "knowledge_fragments", "embedding"):
        if _index_exists(bind, "ix_knowledge_fragments_embedding_hnsw"):
            op.drop_index("ix_knowledge_fragments_embedding_hnsw", table_name="knowledge_fragments")
        bind.execute(
            text(
                "UPDATE knowledge_fragments SET embedding = NULL WHERE embedding IS NOT NULL AND vector_dims(embedding) <> 1024"
            )
        )
        op.execute("ALTER TABLE knowledge_fragments ALTER COLUMN embedding TYPE vector(1024)")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_fragments_embedding_hnsw "
            "ON knowledge_fragments USING hnsw (embedding vector_cosine_ops)"
        )

    op.alter_column(
        "embedding_spaces",
        "embedding_space_id",
        existing_type=UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
    )
    op.alter_column(
        "knowledge_fragment_embeddings",
        "fragment_embedding_id",
        existing_type=UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
    )

    if not _constraint_exists(bind, "uq_knowledge_versions_base_version"):
        op.create_unique_constraint(
            "uq_knowledge_versions_base_version",
            "knowledge_versions",
            ["knowledge_base_id", "knowledge_version_id"],
        )

    if not _constraint_exists(bind, "uq_document_snapshots_id_version_document"):
        op.create_unique_constraint(
            "uq_document_snapshots_id_version_document",
            "document_snapshots",
            ["document_snapshot_id", "knowledge_version_id", "document_id"],
        )

    if not _constraint_exists(bind, "fk_knowledge_base_selections_selected_version_scope"):
        op.create_foreign_key(
            "fk_knowledge_base_selections_selected_version_scope",
            "knowledge_base_selections",
            "knowledge_versions",
            ["selected_knowledge_base_id", "selected_knowledge_version_id"],
            ["knowledge_base_id", "knowledge_version_id"],
        )

    if not _constraint_exists(bind, "fk_document_chunks_snapshot_scope"):
        op.create_foreign_key(
            "fk_document_chunks_snapshot_scope",
            "document_chunks",
            "document_snapshots",
            ["document_snapshot_id", "knowledge_version_id", "document_id"],
            ["document_snapshot_id", "knowledge_version_id", "document_id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _constraint_exists(bind, "fk_document_chunks_snapshot_scope"):
        op.drop_constraint(
            "fk_document_chunks_snapshot_scope", "document_chunks", type_="foreignkey"
        )
    if _constraint_exists(bind, "fk_knowledge_base_selections_selected_version_scope"):
        op.drop_constraint(
            "fk_knowledge_base_selections_selected_version_scope",
            "knowledge_base_selections",
            type_="foreignkey",
        )
    if _constraint_exists(bind, "uq_document_snapshots_id_version_document"):
        op.drop_constraint(
            "uq_document_snapshots_id_version_document", "document_snapshots", type_="unique"
        )
    if _constraint_exists(bind, "uq_knowledge_versions_base_version"):
        op.drop_constraint(
            "uq_knowledge_versions_base_version", "knowledge_versions", type_="unique"
        )

    op.alter_column(
        "knowledge_fragment_embeddings",
        "fragment_embedding_id",
        existing_type=UUID(as_uuid=True),
        server_default=None,
    )
    op.alter_column(
        "embedding_spaces",
        "embedding_space_id",
        existing_type=UUID(as_uuid=True),
        server_default=None,
    )

    if _column_exists(bind, "knowledge_fragments", "embedding"):
        if _index_exists(bind, "ix_knowledge_fragments_embedding_hnsw"):
            op.drop_index("ix_knowledge_fragments_embedding_hnsw", table_name="knowledge_fragments")
        bind.execute(
            text(
                "UPDATE knowledge_fragments SET embedding = NULL WHERE embedding IS NOT NULL AND vector_dims(embedding) <> 16"
            )
        )
        op.execute("ALTER TABLE knowledge_fragments ALTER COLUMN embedding TYPE vector(16)")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_fragments_embedding_hnsw "
            "ON knowledge_fragments USING hnsw (embedding vector_cosine_ops)"
        )
