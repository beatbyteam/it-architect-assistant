"""normalize check_results schema

Revision ID: 20260329_0007
Revises: 20260329_0006
Create Date: 2026-03-29 00:30:00.000000
"""

from __future__ import annotations

revision = "20260329_0007"
down_revision = "20260329_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Current baseline models already create the canonical check_results schema.
    pass


def downgrade() -> None:
    pass
