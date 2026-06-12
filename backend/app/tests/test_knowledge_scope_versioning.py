from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.db.enums import (
    Criticality,
    KnowledgeVersionStatus,
    SourceStatus,
    SourceSyncMode,
    SourceType,
)
from app.domain.services.knowledge_core import KnowledgeSourceService
from app.domain.services.knowledge_snapshot import build_knowledge_scope_snapshot
from app.domain.services.mvp_canonical import CanonicalReadService
from app.schemas.mvp import KnowledgeVersionResponse


class _ProcessingResultsRepo:
    def __init__(self, latest=None):
        self.latest = latest

    def get_latest_for_source(self, _source_id: str):
        return self.latest

    def get_latest_success_for_source(self, _source_id: str):
        return self.latest


class _DocumentsRepo:
    def list_for_source(self, _source_id: str, include_archived: bool = True):
        return []


class _UpdateRunsRepo:
    def __init__(self, finished_at: datetime | None) -> None:
        self.finished_at = finished_at

    def get_latest_finished(self, knowledge_base_id: str | None = None):
        if self.finished_at is None:
            return None
        return SimpleNamespace(finished_at=self.finished_at)


def test_serialize_source_exposes_last_and_next_sync_time_for_auto_policy() -> None:
    now = datetime.now(UTC)
    service = KnowledgeSourceService.__new__(KnowledgeSourceService)
    service.processing_results = _ProcessingResultsRepo(SimpleNamespace(processed_at=now))
    service.documents = _DocumentsRepo()
    service.settings = SimpleNamespace(knowledge_auto_sync_interval_days=30)

    source = SimpleNamespace(
        source_id="src-1",
        knowledge_base_id="kb-1",
        source_type=SourceType.URL_LIST,
        name="Portal",
        base_uri="https://example.com/index.html",
        criticality=Criticality.OPTIONAL,
        status=SourceStatus.ACTIVE,
        refresh_policy="monthly",
        sync_mode=SourceSyncMode.FULL_SCAN,
        source_metadata={},
        created_at=now - timedelta(days=2),
        last_discovered_at=now - timedelta(days=1),
    )

    payload = KnowledgeSourceService._serialize_source(service, source)

    assert payload["last_sync_time"] == now
    assert payload["next_sync_time"] == now + timedelta(days=30)


def test_serialize_source_omits_next_sync_time_for_manual_policy() -> None:
    now = datetime.now(UTC)
    service = KnowledgeSourceService.__new__(KnowledgeSourceService)
    service.processing_results = _ProcessingResultsRepo(SimpleNamespace(processed_at=now))
    service.documents = _DocumentsRepo()
    service.settings = SimpleNamespace(knowledge_auto_sync_interval_days=30)

    source = SimpleNamespace(
        source_id="src-1",
        knowledge_base_id="kb-1",
        source_type=SourceType.REPOSITORY,
        name="Share",
        base_uri="file:///data/knowledge",
        criticality=Criticality.OPTIONAL,
        status=SourceStatus.ACTIVE,
        refresh_policy="manual",
        sync_mode=SourceSyncMode.FULL_SCAN,
        source_metadata={},
        created_at=now - timedelta(days=5),
        last_discovered_at=now - timedelta(days=3),
    )

    payload = KnowledgeSourceService._serialize_source(service, source)

    assert payload["last_sync_time"] == now
    assert payload["next_sync_time"] is None


def test_active_knowledge_version_payload_preserves_knowledge_scope() -> None:
    read_service = CanonicalReadService.__new__(CanonicalReadService)
    read_service.session = None
    read_service.settings = None

    mandatory_version = SimpleNamespace(
        knowledge_version_id="kv-mandatory",
        version_no="KV-MANDATORY",
        status=KnowledgeVersionStatus.ACTIVE,
        created_at=datetime.now(UTC),
        activated_at=datetime.now(UTC),
        activated_by_user_id=None,
        summary={"kind": "mandatory"},
    )
    user_version = SimpleNamespace(
        knowledge_version_id="kv-user",
        version_no="KV-USER",
        status=KnowledgeVersionStatus.ACTIVE,
        created_at=datetime.now(UTC),
        activated_at=datetime.now(UTC),
        activated_by_user_id="user-1",
        summary={"kind": "user"},
    )
    scope = SimpleNamespace(
        mandatory_version=mandatory_version,
        selected_user_version=user_version,
        selected_user_base=SimpleNamespace(knowledge_base_id="kb-user"),
        selected_generation_version=lambda: user_version,
    )

    import app.domain.services.mvp_canonical as mvp_canonical_module

    original_service = mvp_canonical_module.KnowledgeBaseService
    mvp_canonical_module.KnowledgeBaseService = lambda session: SimpleNamespace(
        get_effective_scope=lambda: scope
    )
    try:
        payload = CanonicalReadService.get_active_knowledge_version_payload(read_service)
        response = KnowledgeVersionResponse.model_validate(payload)
    finally:
        mvp_canonical_module.KnowledgeBaseService = original_service

    assert response.knowledge_version_id == "kv-user"
    assert response.knowledge_scope == {
        "mandatory_version_id": "kv-mandatory",
        "selected_user_version_id": "kv-user",
        "selected_user_base_id": "kb-user",
    }


def test_scope_snapshot_uses_only_selected_user_version_when_user_base_is_selected() -> None:
    now = datetime.now(UTC)
    mandatory_version = SimpleNamespace(
        knowledge_version_id="kv-mandatory",
        knowledge_base_id="kb-mandatory",
        knowledge_base=SimpleNamespace(kind="system_mandatory", code="mandatory"),
        version_no="MANDATORY-1",
        status=KnowledgeVersionStatus.ACTIVE,
        created_at=now,
        activated_at=now,
        activated_by_user_id=None,
        version_documents=[],
        source_snapshot={},
    )
    user_version = SimpleNamespace(
        knowledge_version_id="kv-user",
        knowledge_base_id="kb-user",
        knowledge_base=SimpleNamespace(kind="user_managed", code="user"),
        version_no="USER-1",
        status=KnowledgeVersionStatus.ACTIVE,
        created_at=now,
        activated_at=now,
        activated_by_user_id="user-1",
        version_documents=[],
        source_snapshot={},
    )

    snapshot = build_knowledge_scope_snapshot(
        mandatory_version=mandatory_version,
        selected_user_version=user_version,
    )

    assert snapshot["mandatory_version"] == {}
    assert snapshot["selected_generation_version_id"] == "kv-user"
    assert snapshot["effective_version_ids"] == ["kv-user"]
