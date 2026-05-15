"""operation steps and epic 3/4 lifecycle support

Revision ID: 20260328_0003
Revises: 20260328_0002
Create Date: 2026-03-28 16:20:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260328_0003"
down_revision = "20260328_0002"
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
    if _table_exists(bind, "operation_steps"):
        return

    op.create_table(
        "operation_steps",
        sa.Column(
            "operation_step_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("operation_kind", sa.String(length=50), nullable=False),
        sa.Column("operation_id", sa.String(length=64), nullable=False),
        sa.Column("step_code", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("actor_user_id", sa.String(length=100), nullable=True),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "operation_kind", "operation_id", "step_code", name="uq_operation_steps_scope"
        ),
    )
    op.create_index(
        "ix_operation_steps_lookup",
        "operation_steps",
        ["operation_kind", "operation_id", "started_at"],
    )
    op.create_index("ix_operation_steps_correlation", "operation_steps", ["correlation_id"])


def downgrade() -> None:
    op.drop_index("ix_operation_steps_correlation", table_name="operation_steps", if_exists=True)
    op.drop_index("ix_operation_steps_lookup", table_name="operation_steps", if_exists=True)
    op.drop_table("operation_steps", if_exists=True)
