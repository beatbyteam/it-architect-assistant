"""published artifacts for rendered solution/protocol views

Revision ID: 20260328_0002
Revises: 20260328_0001
Create Date: 2026-03-28 14:45:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260328_0002"
down_revision = "20260328_0001"
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
    if _table_exists(bind, "published_artifacts"):
        return

    op.create_table(
        "published_artifacts",
        sa.Column(
            "published_artifact_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("artifact_type", sa.String(length=50), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=50), nullable=False, server_default="published"),
        sa.Column("created_by_user_id", sa.String(length=100), nullable=True),
        sa.Column("rendered_markdown", sa.Text(), nullable=True),
        sa.Column("rendered_html", sa.Text(), nullable=False),
        sa.Column("version_hash", sa.String(length=64), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "target_type", "target_id", "revision_no", name="uq_published_artifacts_target_revision"
        ),
    )
    op.create_index(
        "ix_published_artifacts_target",
        "published_artifacts",
        ["target_type", "target_id", "state"],
    )
    op.create_index("ix_published_artifacts_published_at", "published_artifacts", ["published_at"])


def downgrade() -> None:
    op.drop_index(
        "ix_published_artifacts_published_at", table_name="published_artifacts", if_exists=True
    )
    op.drop_index("ix_published_artifacts_target", table_name="published_artifacts", if_exists=True)
    op.drop_table("published_artifacts", if_exists=True)
