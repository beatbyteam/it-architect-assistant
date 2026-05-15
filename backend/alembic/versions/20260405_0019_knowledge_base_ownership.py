"""knowledge base ownership

Revision ID: 20260405_0019
Revises: 20260404_0018
Create Date: 2026-04-05
"""

import sqlalchemy as sa

from alembic import op

revision = "20260405_0019"
down_revision = "20260404_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases", sa.Column("owner_user_id", sa.String(length=100), nullable=True)
    )
    op.create_index(
        "ix_knowledge_bases_owner_user_id", "knowledge_bases", ["owner_user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_bases_owner_user_id", table_name="knowledge_bases")
    op.drop_column("knowledge_bases", "owner_user_id")
