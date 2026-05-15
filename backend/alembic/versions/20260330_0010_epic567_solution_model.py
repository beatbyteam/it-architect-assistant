"""solution model persistence for epics 5/6/7

Revision ID: 20260330_0010
Revises: 20260329_0009
Create Date: 2026-03-30 10:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260330_0010"
down_revision = "20260329_0009"
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

    if not _table_exists(bind, "solution_section_assessments"):
        op.create_table(
            "solution_section_assessments",
            sa.Column(
                "section_assessment_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "solution_version_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("solution_versions.solution_version_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("section_code", sa.String(length=50), nullable=False),
            sa.Column("heading", sa.String(length=300), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("score", sa.Float(), nullable=False, server_default=sa.text("0")),
            sa.Column(
                "observed_signal_groups", postgresql.JSONB(astext_type=sa.Text()), nullable=True
            ),
            sa.Column(
                "missing_signal_groups", postgresql.JSONB(astext_type=sa.Text()), nullable=True
            ),
            sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column(
                "allowed_archimate_elements", postgresql.JSONB(astext_type=sa.Text()), nullable=True
            ),
            sa.Column(
                "fallback_applied", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.UniqueConstraint(
                "solution_version_id", "section_code", name="uq_solution_section_assessments_code"
            ),
            sa.UniqueConstraint(
                "solution_version_id",
                "sort_order",
                name="uq_solution_section_assessments_sort_order",
            ),
        )

    if not _table_exists(bind, "solution_architecture_entities"):
        op.create_table(
            "solution_architecture_entities",
            sa.Column(
                "architecture_entity_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "solution_version_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("solution_versions.solution_version_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("entity_key", sa.String(length=200), nullable=False),
            sa.Column("display_name", sa.String(length=300), nullable=False),
            sa.Column("source_kind", sa.String(length=50), nullable=True),
            sa.Column("section_code", sa.String(length=50), nullable=True),
            sa.Column("archimate_layer", sa.String(length=50), nullable=True),
            sa.Column("archimate_element_code", sa.String(length=100), nullable=True),
            sa.Column("archimate_element_title", sa.String(length=150), nullable=True),
            sa.Column(
                "normalized_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("entity_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.UniqueConstraint(
                "solution_version_id", "entity_key", name="uq_solution_architecture_entities_key"
            ),
            sa.UniqueConstraint(
                "solution_version_id",
                "sort_order",
                name="uq_solution_architecture_entities_sort_order",
            ),
        )

    if not _table_exists(bind, "solution_architecture_relations"):
        op.create_table(
            "solution_architecture_relations",
            sa.Column(
                "architecture_relation_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "solution_version_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("solution_versions.solution_version_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("relation_key", sa.String(length=200), nullable=False),
            sa.Column("relation_type", sa.String(length=100), nullable=False),
            sa.Column("source_entity_key", sa.String(length=200), nullable=True),
            sa.Column("target_entity_key", sa.String(length=200), nullable=True),
            sa.Column("section_code", sa.String(length=50), nullable=True),
            sa.Column(
                "normalized_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("relation_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.UniqueConstraint(
                "solution_version_id", "relation_key", name="uq_solution_architecture_relations_key"
            ),
            sa.UniqueConstraint(
                "solution_version_id",
                "sort_order",
                name="uq_solution_architecture_relations_sort_order",
            ),
        )


def downgrade() -> None:
    op.drop_table("solution_architecture_relations", if_exists=True)
    op.drop_table("solution_architecture_entities", if_exists=True)
    op.drop_table("solution_section_assessments", if_exists=True)
