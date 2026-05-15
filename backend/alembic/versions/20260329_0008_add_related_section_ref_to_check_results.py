"""add related_section_ref to check_results

Revision ID: 20260329_0008
Revises: 20260329_0007
Create Date: 2026-03-29 00:35:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

revision = "20260329_0008"
down_revision = "20260329_0007"
branch_labels = None
depends_on = None


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
    if _column_exists(bind, "check_results", "related_section_ref"):
        return
    op.add_column(
        "check_results", sa.Column("related_section_ref", sa.String(length=200), nullable=True)
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not _column_exists(bind, "check_results", "related_section_ref"):
        return
    op.drop_column("check_results", "related_section_ref")
