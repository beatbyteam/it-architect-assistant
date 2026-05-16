from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.v1.routes import knowledge_sources_routes
from app.core.exceptions import ValidationError
from app.db.enums import SourceStatus, SourceType
from app.domain.services.knowledge_core import KnowledgeUpdateService
from app.integrations.knowledge.source_security import validate_source_base_uri
from app.schemas.knowledge import SourceCreateRequest


def test_source_create_request_normalizes_source_type_aliases() -> None:
    payload = SourceCreateRequest(
        knowledge_base_id="kb-1",
        source_type="local_folder",
        name="Mounted folder",
        base_uri="file:///tmp/docs",
        criticality="required",
        refresh_policy="auto_monthly",
    )

    assert payload.source_type == SourceType.REPOSITORY
    assert payload.refresh_policy == "monthly"


def test_source_create_request_derives_name_when_blank() -> None:
    payload = SourceCreateRequest(
        knowledge_base_id="kb-1",
        source_type="url",
        name="",
        base_uri="https://docs.example.com/architecture/",
        criticality="optional",
    )

    assert payload.source_type == SourceType.URL_LIST
    assert payload.name == "docs.example.com/architecture"


def test_create_source_route_rejects_local_folder_sources() -> None:
    payload = SourceCreateRequest(
        knowledge_base_id="kb-1",
        source_type="local_folder",
        name="Mounted folder",
        base_uri="file:///tmp/docs",
        criticality="optional",
    )

    with pytest.raises(ValidationError) as exc:
        knowledge_sources_routes.create_source(payload, None, None, None)

    assert exc.value.error_code == "LOCAL_FOLDER_SOURCE_DISABLED"


def test_validate_source_base_uri_rejects_paths_outside_allowed_roots(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    blocked_root = tmp_path / "blocked"
    allowed_root.mkdir()
    blocked_root.mkdir()

    with pytest.raises(ValidationError) as exc:
        validate_source_base_uri(
            source_type=SourceType.REPOSITORY,
            base_uri=str(blocked_root),
            allowed_local_roots=[str(allowed_root)],
        )

    assert exc.value.error_code == "SOURCE_PATH_FORBIDDEN"


def test_run_due_scheduled_syncs_skips_manual_only_sources() -> None:
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    now = datetime.now(UTC)
    manual_only_base = SimpleNamespace(knowledge_base_id="kb-manual", status=SourceStatus.ACTIVE)
    auto_base = SimpleNamespace(knowledge_base_id="kb-auto", status=SourceStatus.ACTIVE)
    service.settings = SimpleNamespace(knowledge_auto_sync_interval_days=30)
    service.sources = SimpleNamespace(
        list_active=lambda knowledge_base_id=None: [SimpleNamespace(refresh_policy="manual")]
        if knowledge_base_id == "kb-manual"
        else [SimpleNamespace(refresh_policy="monthly")]
    )
    service.update_runs = SimpleNamespace(
        get_latest_finished=lambda knowledge_base_id=None: SimpleNamespace(
            finished_at=now - timedelta(days=45)
        )
    )
    service._create_run = lambda **kwargs: SimpleNamespace(
        update_run_id=f"run-{kwargs['payload'].knowledge_base_id}",
        knowledge_base_id=kwargs["payload"].knowledge_base_id,
    )
    service.session = None

    import app.domain.services.knowledge_core as knowledge_core_module

    original_service = knowledge_core_module.KnowledgeBaseService
    knowledge_core_module.KnowledgeBaseService = lambda session: SimpleNamespace(
        bases=SimpleNamespace(list_visible=lambda: [manual_only_base, auto_base])
    )
    try:
        payload = KnowledgeUpdateService.run_due_scheduled_syncs(
            service, now=now, execute_inline=False
        )
    finally:
        knowledge_core_module.KnowledgeBaseService = original_service

    assert payload["started_knowledge_base_ids"] == ["kb-auto"]
    assert "kb-manual" in payload["skipped_knowledge_base_ids"]
    assert payload["diagnostics"]["skipped_details"]["kb-manual"] == "no_auto_sync_sources"
