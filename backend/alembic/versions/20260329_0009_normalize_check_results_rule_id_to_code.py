"""normalize check_results.rule_id to rule code text

Revision ID: 20260329_0009
Revises: 20260329_0008
Create Date: 2026-03-29 00:40:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260329_0009"
down_revision = "20260329_0008"
branch_labels = None
depends_on = None

UUID_LIKE_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"


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


def _drop_foreign_keys_on_column(bind, table_name: str, column_name: str) -> None:
    fk_names = (
        bind.execute(
            text(
                """
            SELECT con.conname
            FROM pg_constraint AS con
            JOIN pg_class AS rel
              ON rel.oid = con.conrelid
            JOIN pg_namespace AS nsp
              ON nsp.oid = rel.relnamespace
            JOIN unnest(con.conkey) AS key_col(attnum)
              ON TRUE
            JOIN pg_attribute AS attr
              ON attr.attrelid = rel.oid
             AND attr.attnum = key_col.attnum
            WHERE nsp.nspname = current_schema()
              AND rel.relname = :table_name
              AND con.contype = 'f'
              AND attr.attname = :column_name
            """
            ),
            {"table_name": table_name, "column_name": column_name},
        )
        .scalars()
        .all()
    )

    for fk_name in fk_names:
        op.drop_constraint(fk_name, table_name, type_="foreignkey")


def upgrade() -> None:
    bind = op.get_bind()
    current_type = _column_udt_name(bind, "check_results", "rule_id")

    if current_type in {"varchar", "text"}:
        return
    if current_type != "uuid":
        raise RuntimeError(f"Unsupported check_results.rule_id type for upgrade: {current_type!r}")

    _drop_foreign_keys_on_column(bind, "check_results", "rule_id")

    op.add_column("check_results", sa.Column("rule_id_code", sa.String(length=100), nullable=True))

    bind.execute(
        text(
            """
            UPDATE check_results AS cr
            SET rule_id_code = nr.rule_code
            FROM normative_rules AS nr
            WHERE cr.rule_id = nr.rule_id
            """
        )
    )

    unmatched = bind.execute(
        text(
            """
            SELECT count(*)
            FROM check_results
            WHERE rule_id IS NOT NULL
              AND rule_id_code IS NULL
            """
        )
    ).scalar_one()
    if unmatched:
        raise RuntimeError(
            "Cannot normalize check_results.rule_id to rule code text: "
            f"{unmatched} rows do not match normative_rules.rule_id."
        )

    op.drop_column("check_results", "rule_id")
    op.execute("ALTER TABLE check_results RENAME COLUMN rule_id_code TO rule_id")


def downgrade() -> None:
    bind = op.get_bind()
    current_type = _column_udt_name(bind, "check_results", "rule_id")

    if current_type == "uuid":
        return
    if current_type not in {"varchar", "text"}:
        raise RuntimeError(
            f"Unsupported check_results.rule_id type for downgrade: {current_type!r}"
        )

    op.add_column(
        "check_results", sa.Column("rule_id_uuid", postgresql.UUID(as_uuid=True), nullable=True)
    )

    bind.execute(
        text(
            """
            UPDATE check_results AS cr
            SET rule_id_uuid = nr.rule_id
            FROM verification_protocols AS vp,
                 verification_runs AS vr,
                 normative_rules AS nr
            WHERE cr.verification_protocol_id = vp.verification_protocol_id
              AND vr.verification_run_id = vp.verification_run_id
              AND nr.knowledge_version_id = vr.knowledge_version_id
              AND nr.rule_code = cr.rule_id
              AND cr.rule_id IS NOT NULL
              AND btrim(cr.rule_id) <> ''
            """
        )
    )

    bind.execute(
        text(
            """
            WITH globally_unique_rule_codes AS (
                SELECT rule_code, min(rule_id::text)::uuid AS rule_id
                FROM normative_rules
                GROUP BY rule_code
                HAVING count(*) = 1
            )
            UPDATE check_results AS cr
            SET rule_id_uuid = gurc.rule_id
            FROM globally_unique_rule_codes AS gurc
            WHERE cr.rule_id_uuid IS NULL
              AND cr.rule_id IS NOT NULL
              AND btrim(cr.rule_id) <> ''
              AND gurc.rule_code = cr.rule_id
            """
        )
    )

    bind.execute(
        text(
            f"""
            UPDATE check_results
            SET rule_id_uuid = rule_id::uuid
            WHERE rule_id_uuid IS NULL
              AND rule_id IS NOT NULL
              AND btrim(rule_id) <> ''
              AND rule_id ~* '{UUID_LIKE_RE}'
            """
        )
    )

    op.drop_column("check_results", "rule_id")
    op.execute("ALTER TABLE check_results RENAME COLUMN rule_id_uuid TO rule_id")
    op.create_foreign_key(
        "fk_check_results_rule_id_normative_rules",
        "check_results",
        "normative_rules",
        ["rule_id"],
        ["rule_id"],
    )
