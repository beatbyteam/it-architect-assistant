from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_baseline_migration_is_frozen_snapshot() -> None:
    content = _read("backend/alembic/versions/20260328_0001_core_mvp_baseline.py")
    assert "Base.metadata.sorted_tables" not in content
    assert "from app.db.base import Base" not in content
    assert "from app.db import models" not in content
    assert "op.create_table" in content
    assert "business_tasks" in content


def test_embedding_dimensions_are_validated_against_db_constant() -> None:
    content = _read("backend/app/core/config.py")
    assert "EMBEDDING_DIMENSIONS_MISMATCH" in content
    assert "EMBEDDING_VECTOR_DIMENSIONS" in content


def test_session_factory_is_lazy_and_uses_runtime_settings() -> None:
    content = _read("backend/app/db/session.py")
    assert "@lru_cache(maxsize=8)" in content
    assert "def get_engine(database_url: str | None = None)" in content
    assert "settings = get_settings()" not in content


def test_generation_and_verification_runs_have_active_partial_unique_indexes() -> None:
    generation = _read("backend/app/db/models/generation.py")
    verification = _read("backend/app/db/models/verification.py")
    assert "uq_generation_runs_active_per_task" in generation
    assert "status NOT IN ('completed', 'failed', 'canceled')" in generation
    assert "uq_verification_runs_active_per_solution" in verification
    assert "status NOT IN ('completed', 'failed', 'canceled')" in verification


def test_knowledge_model_reflects_lookup_indexes_and_unique_run_constraint() -> None:
    knowledge = _read("backend/app/db/models/knowledge.py")
    assert "uq_knowledge_versions_update_run_id" in knowledge
    assert "ix_source_processing_results_update_run_id" in knowledge
    assert "ix_document_extracted_items_knowledge_version_id" in knowledge
    assert "ix_document_deltas_update_run_id" in knowledge
    assert "ix_knowledge_fragments_embedding_hnsw" in knowledge


def test_hardening_migration_adds_db_level_guards() -> None:
    migration = _read(
        "backend/alembic/versions/20260404_0015_db_hardening_indexes_and_constraints.py"
    )
    assert "_delete_duplicate_knowledge_versions" in migration
    assert "uq_knowledge_update_runs_active_per_base" in migration
    assert "uq_generation_runs_active_per_task" in migration
    assert "uq_verification_runs_active_per_solution" in migration
    assert "CREATE INDEX IF NOT EXISTS ix_knowledge_fragments_embedding_hnsw" in migration
