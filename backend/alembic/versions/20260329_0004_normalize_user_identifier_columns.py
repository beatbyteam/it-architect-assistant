"""align audit_events.target_id with uuid ids

Revision ID: 20260329_0004
Revises: 20260328_0003
Create Date: 2026-03-29 00:10:00.000000
"""

from __future__ import annotations

from sqlalchemy import text

from alembic import op

revision = "20260329_0004"
down_revision = "20260328_0003"
branch_labels = None
depends_on = None


def _column_udt_name(bind, table_name: str, column_name: str) -> str | None:
    return bind.execute(
        text(
            """
            SELECT udt_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).scalar_one_or_none()


def upgrade() -> None:
    bind = op.get_bind()
    udt_name = _column_udt_name(bind, "audit_events", "target_id")
    if udt_name is None or udt_name == "uuid":
        return

    bind.execute(
        text(
            """
            ALTER TABLE audit_events
            ALTER COLUMN target_id TYPE uuid
            USING target_id::uuid
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    udt_name = _column_udt_name(bind, "audit_events", "target_id")
    if udt_name is None or udt_name in {"varchar", "text"}:
        return

    bind.execute(
        text(
            """
            ALTER TABLE audit_events
            ALTER COLUMN target_id TYPE varchar(64)
            USING target_id::text
            """
        )
    )
