"""normalize business task status constraint

Revision ID: 20260329_0005
Revises: 20260329_0004
Create Date: 2026-03-29 00:20:00.000000
"""

from __future__ import annotations

revision = "20260329_0005"
down_revision = "20260329_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Current baseline models already create the canonical business_tasks.status shape.
    # Keep the revision idempotent for migration smoke on fresh databases.
    pass


def downgrade() -> None:
    pass
