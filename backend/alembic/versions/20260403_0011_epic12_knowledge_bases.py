"""knowledge bases and mandatory baseline for epics 1/2

Revision ID: 20260403_0011
Revises: 20260330_0010
Create Date: 2026-04-03 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260403_0011"
down_revision = "20260330_0010"
branch_labels = None
depends_on = None

MANDATORY_BASE_CODE = "mandatory_architecture_baseline"
DEFAULT_USER_BASE_CODE = "default_user_knowledge_base"


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


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    return bool(
        bind.execute(
            sa.text(
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


def _constraint_exists(bind, table_name: str, constraint_name: str) -> bool:
    return bool(
        bind.execute(
            sa.text(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
                  AND constraint_name = :constraint_name
                """
            ),
            {"table_name": table_name, "constraint_name": constraint_name},
        ).scalar_one_or_none()
    )


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "knowledge_bases"):
        op.create_table(
            "knowledge_bases",
            sa.Column(
                "knowledge_base_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("code", sa.String(length=120), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("kind", sa.String(length=30), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint("code", name="uq_knowledge_bases_code"),
        )

    bind.execute(
        sa.text(
            """
            INSERT INTO knowledge_bases (code, name, description, kind, status)
            VALUES (:code, :name, :description, :kind, :status)
            ON CONFLICT (code) DO NOTHING
            """
        ),
        {
            "code": MANDATORY_BASE_CODE,
            "name": "Mandatory Architecture Baseline",
            "description": "System mandatory baseline for TOGAF and ArchiMate 3.2.",
            "kind": "system_mandatory",
            "status": "active",
        },
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO knowledge_bases (code, name, description, kind, status)
            VALUES (:code, :name, :description, :kind, :status)
            ON CONFLICT (code) DO NOTHING
            """
        ),
        {
            "code": DEFAULT_USER_BASE_CODE,
            "name": "Default User Knowledge Base",
            "description": "Default user-managed knowledge base for enterprise-specific documents.",
            "kind": "user_managed",
            "status": "active",
        },
    )

    for table_name in ("knowledge_sources", "knowledge_update_runs", "knowledge_versions"):
        if not _column_exists(bind, table_name, "knowledge_base_id"):
            op.add_column(
                table_name,
                sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=True),
            )

    bind.execute(
        sa.text("SELECT knowledge_base_id FROM knowledge_bases WHERE code = :code"),
        {"code": MANDATORY_BASE_CODE},
    ).scalar_one()
    default_user_base_id = bind.execute(
        sa.text("SELECT knowledge_base_id FROM knowledge_bases WHERE code = :code"),
        {"code": DEFAULT_USER_BASE_CODE},
    ).scalar_one()

    bind.execute(
        sa.text(
            "UPDATE knowledge_sources SET knowledge_base_id = :base_id WHERE knowledge_base_id IS NULL"
        ),
        {"base_id": default_user_base_id},
    )
    bind.execute(
        sa.text(
            "UPDATE knowledge_update_runs SET knowledge_base_id = :base_id WHERE knowledge_base_id IS NULL"
        ),
        {"base_id": default_user_base_id},
    )
    bind.execute(
        sa.text(
            """
            UPDATE knowledge_versions AS kv
            SET knowledge_base_id = COALESCE(kur.knowledge_base_id, :base_id)
            FROM knowledge_update_runs AS kur
            WHERE kv.update_run_id = kur.update_run_id
              AND kv.knowledge_base_id IS NULL
            """
        ),
        {"base_id": default_user_base_id},
    )
    bind.execute(
        sa.text(
            "UPDATE knowledge_versions SET knowledge_base_id = :base_id WHERE knowledge_base_id IS NULL"
        ),
        {"base_id": default_user_base_id},
    )

    if not _constraint_exists(
        bind, "knowledge_sources", "fk_knowledge_sources_knowledge_base_id_knowledge_bases"
    ):
        op.create_foreign_key(
            "fk_knowledge_sources_knowledge_base_id_knowledge_bases",
            "knowledge_sources",
            "knowledge_bases",
            ["knowledge_base_id"],
            ["knowledge_base_id"],
        )
    if not _constraint_exists(
        bind, "knowledge_update_runs", "fk_knowledge_update_runs_knowledge_base_id_knowledge_bases"
    ):
        op.create_foreign_key(
            "fk_knowledge_update_runs_knowledge_base_id_knowledge_bases",
            "knowledge_update_runs",
            "knowledge_bases",
            ["knowledge_base_id"],
            ["knowledge_base_id"],
        )
    if not _constraint_exists(
        bind, "knowledge_versions", "fk_knowledge_versions_knowledge_base_id_knowledge_bases"
    ):
        op.create_foreign_key(
            "fk_knowledge_versions_knowledge_base_id_knowledge_bases",
            "knowledge_versions",
            "knowledge_bases",
            ["knowledge_base_id"],
            ["knowledge_base_id"],
        )

    op.alter_column(
        "knowledge_sources",
        "knowledge_base_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.alter_column(
        "knowledge_update_runs",
        "knowledge_base_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.alter_column(
        "knowledge_versions",
        "knowledge_base_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )

    op.execute(sa.text("DROP INDEX IF EXISTS uq_knowledge_versions_active_only"))
    op.create_index(
        "uq_knowledge_versions_active_only",
        "knowledge_versions",
        ["knowledge_base_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    if not _table_exists(bind, "knowledge_base_selections"):
        op.create_table(
            "knowledge_base_selections",
            sa.Column(
                "knowledge_base_selection_id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "selection_scope",
                sa.String(length=100),
                nullable=False,
                server_default=sa.text("'generation'"),
            ),
            sa.Column(
                "selected_knowledge_base_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("knowledge_bases.knowledge_base_id"),
                nullable=False,
            ),
            sa.Column(
                "selected_knowledge_version_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("knowledge_versions.knowledge_version_id"),
                nullable=True,
            ),
            sa.Column("updated_by_user_id", sa.String(length=100), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint("selection_scope", name="uq_knowledge_base_selections_scope"),
        )

    bind.execute(
        sa.text(
            """
            INSERT INTO knowledge_base_selections (
                selection_scope,
                selected_knowledge_base_id,
                selected_knowledge_version_id
            )
            VALUES ('generation', :base_id, NULL)
            ON CONFLICT (selection_scope) DO NOTHING
            """
        ),
        {"base_id": default_user_base_id},
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_table("knowledge_base_selections", if_exists=True)
    op.execute(sa.text("DROP INDEX IF EXISTS uq_knowledge_versions_active_only"))
    op.create_index(
        "uq_knowledge_versions_active_only",
        "knowledge_versions",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    for table_name, fk_name in (
        ("knowledge_versions", "fk_knowledge_versions_knowledge_base_id_knowledge_bases"),
        ("knowledge_update_runs", "fk_knowledge_update_runs_knowledge_base_id_knowledge_bases"),
        ("knowledge_sources", "fk_knowledge_sources_knowledge_base_id_knowledge_bases"),
    ):
        if _constraint_exists(bind, table_name, fk_name):
            op.drop_constraint(fk_name, table_name, type_="foreignkey")

    if _column_exists(bind, "knowledge_versions", "knowledge_base_id"):
        op.drop_column("knowledge_versions", "knowledge_base_id")
    if _column_exists(bind, "knowledge_update_runs", "knowledge_base_id"):
        op.drop_column("knowledge_update_runs", "knowledge_base_id")
    if _column_exists(bind, "knowledge_sources", "knowledge_base_id"):
        op.drop_column("knowledge_sources", "knowledge_base_id")
    op.drop_table("knowledge_bases", if_exists=True)
