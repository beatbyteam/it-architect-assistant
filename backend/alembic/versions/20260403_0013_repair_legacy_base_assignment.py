"""repair legacy knowledge-base assignment after epic 1/2 migration

Revision ID: 20260403_0013
Revises: 20260403_0012
Create Date: 2026-04-03 18:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260403_0013"
down_revision = "20260403_0012"
branch_labels = None
depends_on = None

MANDATORY_BASE_CODE = "mandatory_architecture_baseline"
DEFAULT_USER_BASE_CODE = "default_user_knowledge_base"
MANDATORY_MATCH_SQL = """
    lower(coalesce(sd.title, '')) like '%togaf%'
    or lower(coalesce(sd.title, '')) like '%archimate%'
    or lower(coalesce(sd.title, '')) like '%oda%'
    or lower(coalesce(sd.title, '')) like '%technology standard%'
    or lower(coalesce(sd.uri, '')) like '%togaf%'
    or lower(coalesce(sd.uri, '')) like '%archimate%'
    or lower(coalesce(sd.uri, '')) like '%oda%'
    or lower(coalesce(sd.uri, '')) like '%technology_standard%'
    or lower(coalesce(kvd.role_code, '')) in (
        'ig1242_oda_component_inventory',
        'oda',
        'archimate_3_2',
        'technology_standard',
        'template_or_principles'
    )
"""


def upgrade() -> None:
    bind = op.get_bind()
    mandatory_base_id = bind.execute(
        sa.text("SELECT knowledge_base_id FROM knowledge_bases WHERE code = :code"),
        {"code": MANDATORY_BASE_CODE},
    ).scalar_one_or_none()
    default_user_base_id = bind.execute(
        sa.text("SELECT knowledge_base_id FROM knowledge_bases WHERE code = :code"),
        {"code": DEFAULT_USER_BASE_CODE},
    ).scalar_one_or_none()
    if mandatory_base_id is None or default_user_base_id is None:
        return

    bind.execute(
        sa.text(
            f"""
            UPDATE knowledge_sources AS ks
            SET knowledge_base_id = :default_user_base_id
            WHERE ks.knowledge_base_id = :mandatory_base_id
              AND EXISTS (
                SELECT 1
                FROM source_documents sd
                LEFT JOIN knowledge_version_documents kvd ON kvd.document_id = sd.document_id
                WHERE sd.source_id = ks.source_id
              )
              AND NOT EXISTS (
                SELECT 1
                FROM source_documents sd
                LEFT JOIN knowledge_version_documents kvd ON kvd.document_id = sd.document_id
                WHERE sd.source_id = ks.source_id
                  AND ({MANDATORY_MATCH_SQL})
              )
            """
        ),
        {
            "mandatory_base_id": mandatory_base_id,
            "default_user_base_id": default_user_base_id,
        },
    )

    bind.execute(
        sa.text(
            f"""
            UPDATE knowledge_versions AS kv
            SET knowledge_base_id = :default_user_base_id
            WHERE kv.knowledge_base_id = :mandatory_base_id
              AND EXISTS (
                SELECT 1
                FROM knowledge_version_documents kvd
                JOIN source_documents sd ON sd.document_id = kvd.document_id
                WHERE kvd.knowledge_version_id = kv.knowledge_version_id
              )
              AND NOT EXISTS (
                SELECT 1
                FROM knowledge_version_documents kvd
                JOIN source_documents sd ON sd.document_id = kvd.document_id
                WHERE kvd.knowledge_version_id = kv.knowledge_version_id
                  AND ({MANDATORY_MATCH_SQL})
              )
            """
        ),
        {
            "mandatory_base_id": mandatory_base_id,
            "default_user_base_id": default_user_base_id,
        },
    )

    bind.execute(
        sa.text(
            """
            UPDATE knowledge_update_runs AS kur
            SET knowledge_base_id = :default_user_base_id
            WHERE kur.knowledge_base_id = :mandatory_base_id
              AND NOT EXISTS (
                SELECT 1
                FROM knowledge_versions kv
                WHERE kv.update_run_id = kur.update_run_id
                  AND kv.knowledge_base_id = :mandatory_base_id
              )
            """
        ),
        {
            "mandatory_base_id": mandatory_base_id,
            "default_user_base_id": default_user_base_id,
        },
    )


def downgrade() -> None:
    # repair migration is intentionally irreversible
    return
