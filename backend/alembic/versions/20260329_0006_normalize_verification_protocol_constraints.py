"""normalize verification protocol constraints

Revision ID: 20260329_0006
Revises: 20260329_0005
Create Date: 2026-03-29 00:25:00.000000
"""

from __future__ import annotations

revision = "20260329_0006"
down_revision = "20260329_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Current baseline models already create the canonical verification protocol schema.
    pass


def downgrade() -> None:
    pass
