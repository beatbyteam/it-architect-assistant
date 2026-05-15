from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_latest_success_for_source_excludes_skipped_runs() -> None:
    content = _read("backend/app/db/repositories/knowledge.py")
    assert "SourceProcessingStatus.SKIPPED" in content


def test_knowledge_models_have_cross_scope_integrity_constraints() -> None:
    content = _read("backend/app/db/models/knowledge.py")
    assert "fk_knowledge_base_selections_selected_version_scope" in content
    assert "uq_knowledge_versions_base_version" in content
    assert "fk_document_chunks_snapshot_scope" in content
    assert "uq_document_snapshots_id_version_document" in content


def test_followup_migration_repairs_db_integrity_and_embedding_dimensions() -> None:
    content = _read("backend/alembic/versions/20260404_0018_db_knowledge_integrity_repairs.py")
    assert "ALTER TABLE knowledge_fragments ALTER COLUMN embedding TYPE vector(1024)" in content
    assert "gen_random_uuid()" in content
    assert "fk_document_chunks_snapshot_scope" in content
    assert "fk_knowledge_base_selections_selected_version_scope" in content
