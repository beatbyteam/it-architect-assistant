"""epic78 version embedding space and base preference

Revision ID: 20260404_0017
Revises: 20260404_0016
Create Date: 2026-04-04 08:55:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260404_0017"
down_revision = "20260404_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column("preferred_embedding_space_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "knowledge_versions",
        sa.Column("embedding_space_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_knowledge_bases_preferred_embedding_space",
        "knowledge_bases",
        "embedding_spaces",
        ["preferred_embedding_space_id"],
        ["embedding_space_id"],
    )
    op.create_foreign_key(
        "fk_knowledge_versions_embedding_space",
        "knowledge_versions",
        "embedding_spaces",
        ["embedding_space_id"],
        ["embedding_space_id"],
    )
    op.create_index(
        "ix_knowledge_versions_embedding_space_id", "knowledge_versions", ["embedding_space_id"]
    )
    op.execute(
        """
        UPDATE knowledge_versions kv
        SET embedding_space_id = ks.preferred_embedding_space_id
        FROM knowledge_bases ks
        WHERE kv.knowledge_base_id = ks.knowledge_base_id
          AND kv.status = 'active'
          AND ks.preferred_embedding_space_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_versions_embedding_space_id", table_name="knowledge_versions")
    op.drop_constraint(
        "fk_knowledge_versions_embedding_space", "knowledge_versions", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_knowledge_bases_preferred_embedding_space", "knowledge_bases", type_="foreignkey"
    )
    op.drop_column("knowledge_versions", "embedding_space_id")
    op.drop_column("knowledge_bases", "preferred_embedding_space_id")
