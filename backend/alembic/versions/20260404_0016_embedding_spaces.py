"""embedding spaces and fragment embedding storage

Revision ID: 20260404_0016
Revises: 20260404_0015
Create Date: 2026-04-04 07:45:00.000000
"""

from __future__ import annotations

import json
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import ARRAY, UUID

from alembic import op

revision = "20260404_0016"
down_revision = "20260404_0015"
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


def _coerce_embedding(embedding):
    if embedding is None:
        return None
    if isinstance(embedding, str):
        embedding = embedding.strip()
        if not embedding:
            return None
        try:
            parsed = json.loads(embedding)
        except json.JSONDecodeError:
            parsed = [part.strip() for part in embedding.strip("[]").split(",") if part.strip()]
        return [float(value) for value in parsed]
    if isinstance(embedding, list | tuple):
        return [float(value) for value in embedding]
    try:
        return [float(value) for value in embedding]
    except TypeError:
        value = str(embedding).strip()
        if not value:
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = [part.strip() for part in value.strip("[]").split(",") if part.strip()]
        return [float(item) for item in parsed]


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "embedding_spaces"):
        op.create_table(
            "embedding_spaces",
            sa.Column("embedding_space_id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("code", sa.String(length=120), nullable=False),
            sa.Column("provider_name", sa.String(length=100), nullable=False),
            sa.Column("model_id", sa.String(length=255), nullable=False),
            sa.Column("dimensions", sa.Integer(), nullable=False),
            sa.Column(
                "distance_metric", sa.String(length=32), nullable=False, server_default="cosine"
            ),
            sa.Column("query_template", sa.Text(), nullable=True),
            sa.Column("document_template", sa.Text(), nullable=True),
            sa.Column("normalize_l2", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("truncate_dim", sa.Integer(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("code", name="uq_embedding_spaces_code"),
        )
    if not _index_exists(bind, "uq_embedding_spaces_active_only"):
        op.create_index(
            "uq_embedding_spaces_active_only",
            "embedding_spaces",
            ["is_active"],
            unique=True,
            postgresql_where=sa.text("is_active = true"),
        )

    if not _table_exists(bind, "knowledge_fragment_embeddings"):
        op.create_table(
            "knowledge_fragment_embeddings",
            sa.Column(
                "fragment_embedding_id", UUID(as_uuid=True), primary_key=True, nullable=False
            ),
            sa.Column(
                "fragment_id",
                UUID(as_uuid=True),
                sa.ForeignKey("knowledge_fragments.fragment_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "embedding_space_id",
                UUID(as_uuid=True),
                sa.ForeignKey("embedding_spaces.embedding_space_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("embedding_key", sa.String(length=255), nullable=True),
            sa.Column("embedding", ARRAY(sa.Float()), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "fragment_id", "embedding_space_id", name="uq_knowledge_fragment_embeddings_scope"
            ),
        )
    if not _index_exists(bind, "ix_knowledge_fragment_embeddings_fragment_id"):
        op.create_index(
            "ix_knowledge_fragment_embeddings_fragment_id",
            "knowledge_fragment_embeddings",
            ["fragment_id"],
        )
    if not _index_exists(bind, "ix_knowledge_fragment_embeddings_embedding_space_id"):
        op.create_index(
            "ix_knowledge_fragment_embeddings_embedding_space_id",
            "knowledge_fragment_embeddings",
            ["embedding_space_id"],
        )

    embedding_spaces = sa.table(
        "embedding_spaces",
        sa.column("embedding_space_id", UUID(as_uuid=True)),
        sa.column("code", sa.String()),
        sa.column("provider_name", sa.String()),
        sa.column("model_id", sa.String()),
        sa.column("dimensions", sa.Integer()),
        sa.column("distance_metric", sa.String()),
        sa.column("query_template", sa.Text()),
        sa.column("document_template", sa.Text()),
        sa.column("normalize_l2", sa.Boolean()),
        sa.column("truncate_dim", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
    )
    fragment_embeddings = sa.table(
        "knowledge_fragment_embeddings",
        sa.column("fragment_embedding_id", UUID(as_uuid=True)),
        sa.column("fragment_id", UUID(as_uuid=True)),
        sa.column("embedding_space_id", UUID(as_uuid=True)),
        sa.column("embedding_key", sa.String()),
        sa.column("embedding", ARRAY(sa.Float())),
    )

    existing_space_id = bind.execute(
        sa.select(embedding_spaces.c.embedding_space_id).where(
            embedding_spaces.c.code == "legacy_statistical_default"
        )
    ).scalar_one_or_none()
    if existing_space_id is None:
        existing_space_id = uuid4()
        bind.execute(
            sa.insert(embedding_spaces).values(
                embedding_space_id=existing_space_id,
                code="legacy_statistical_default",
                provider_name="statistical",
                model_id="local-statistical-v2",
                dimensions=16,
                distance_metric="cosine",
                query_template=None,
                document_template=None,
                normalize_l2=True,
                truncate_dim=None,
                is_active=True,
            )
        )

    rows = bind.execute(
        text(
            """
            SELECT fragment_id, embedding_key, embedding
            FROM knowledge_fragments
            WHERE embedding IS NOT NULL
            """
        )
    ).fetchall()
    existing_fragment_ids = {
        str(row[0])
        for row in bind.execute(
            text(
                """
                SELECT fragment_id
                FROM knowledge_fragment_embeddings
                WHERE embedding_space_id = :embedding_space_id
                """
            ),
            {"embedding_space_id": existing_space_id},
        ).fetchall()
    }
    payload = []
    for fragment_id, embedding_key, embedding in rows:
        if str(fragment_id) in existing_fragment_ids:
            continue
        payload.append(
            {
                "fragment_embedding_id": uuid4(),
                "fragment_id": fragment_id,
                "embedding_space_id": existing_space_id,
                "embedding_key": embedding_key,
                "embedding": _coerce_embedding(embedding),
            }
        )
    if payload:
        bind.execute(sa.insert(fragment_embeddings), payload)


def downgrade() -> None:
    bind = op.get_bind()
    if _index_exists(bind, "ix_knowledge_fragment_embeddings_embedding_space_id"):
        op.drop_index(
            "ix_knowledge_fragment_embeddings_embedding_space_id",
            table_name="knowledge_fragment_embeddings",
        )
    if _index_exists(bind, "ix_knowledge_fragment_embeddings_fragment_id"):
        op.drop_index(
            "ix_knowledge_fragment_embeddings_fragment_id",
            table_name="knowledge_fragment_embeddings",
        )
    if _table_exists(bind, "knowledge_fragment_embeddings"):
        op.drop_table("knowledge_fragment_embeddings")
    if _index_exists(bind, "uq_embedding_spaces_active_only"):
        op.drop_index("uq_embedding_spaces_active_only", table_name="embedding_spaces")
    if _table_exists(bind, "embedding_spaces"):
        op.drop_table("embedding_spaces")
