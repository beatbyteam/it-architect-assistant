from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

from app.core.security import AuthPrincipal
from app.db.enums import (
    AccountType,
    DocumentDeltaKind,
    DocumentType,
    KnowledgeBaseKind,
    KnowledgeUpdateStatus,
    KnowledgeVersionStatus,
    SourceDocumentStatus,
    SourceProcessingStatus,
    SourceStatus,
    SourceType,
    UpdateRunType,
)
from app.domain.services.knowledge_core import KnowledgeSourceService
from app.domain.services.knowledge_core import KnowledgeUpdateService
from app.domain.services.mvp_canonical import CanonicalReadService


def _principal() -> AuthPrincipal:
    return AuthPrincipal(
        user_id="user-1",
        login="architect",
        display_name="Architect",
        account_type=AccountType.HUMAN,
        role_codes=["USER"],
    )


def test_remove_document_and_start_update_archives_document_and_starts_delete_run() -> None:
    service = KnowledgeSourceService.__new__(KnowledgeSourceService)
    service.session = Mock()
    service.audit = Mock()
    service._assert_document_mutable = lambda *args, **kwargs: None

    document = SimpleNamespace(
        document_id="doc-1",
        title="Customer Standard",
        source_id="src-1",
        status=SourceDocumentStatus.FETCHED,
        is_latest=True,
    )
    source = SimpleNamespace(
        source_id="src-1",
        knowledge_base_id="kb-1",
        status=SourceStatus.ACTIVE,
    )
    service.get_document = lambda document_id: document
    service.get_source = lambda source_id: source

    import app.domain.services.knowledge_core as knowledge_core_module

    captured: dict[str, object] = {}

    class FakeUpdateService:
        def __init__(self, session, settings):
            captured["session"] = session
            captured["settings"] = settings

        def start_run(self, payload, principal):
            captured["payload"] = payload
            captured["principal"] = principal
            return {"update_run_id": "run-1", "run_type": payload.run_type.value}

    original_service = knowledge_core_module.KnowledgeUpdateService
    knowledge_core_module.KnowledgeUpdateService = FakeUpdateService
    try:
        updated_document, run_payload = KnowledgeSourceService.remove_document_and_start_update(
            service,
            "doc-1",
            _principal(),
            settings=SimpleNamespace(),
            execute_inline=True,
            reason="remove duplicate",
        )
    finally:
        knowledge_core_module.KnowledgeUpdateService = original_service

    assert updated_document is document
    assert updated_document.status == SourceDocumentStatus.ARCHIVED
    assert updated_document.is_latest is False
    assert run_payload["update_run_id"] == "run-1"
    assert run_payload["run_type"] == "delete"
    assert captured["payload"].selected_source_ids == ["src-1"]
    assert captured["payload"].run_type.value == "delete"
    service.session.commit.assert_called_once()
    service.audit.record.assert_called_once()


def test_archive_source_starts_delete_run_for_archived_source_documents() -> None:
    service = KnowledgeSourceService.__new__(KnowledgeSourceService)
    service.session = Mock()
    service.audit = Mock()
    service._assert_source_mutable = lambda *args, **kwargs: None

    source = SimpleNamespace(
        source_id="src-1",
        knowledge_base_id="kb-1",
        name="Uploaded files",
        status=SourceStatus.ACTIVE,
    )
    documents = [
        SimpleNamespace(document_id="doc-1"),
        SimpleNamespace(document_id="doc-2"),
    ]
    service._get_source_compat = lambda source_id, principal: source
    service.documents = SimpleNamespace(
        list_for_source=lambda source_id, include_archived=False: documents
    )

    import app.domain.services.knowledge_core as knowledge_core_module

    captured: dict[str, object] = {}

    class FakeUpdateService:
        def __init__(self, session, settings):
            captured["session"] = session
            captured["settings"] = settings

        def start_run(self, payload, principal):
            captured["payload"] = payload
            captured["principal"] = principal
            return {"update_run_id": "run-1", "run_type": payload.run_type.value}

    original_service = knowledge_core_module.KnowledgeUpdateService
    knowledge_core_module.KnowledgeUpdateService = FakeUpdateService
    try:
        archived_source = KnowledgeSourceService.archive_source(
            service,
            "src-1",
            _principal(),
            settings=SimpleNamespace(),
            execute_inline=True,
        )
    finally:
        knowledge_core_module.KnowledgeUpdateService = original_service

    assert archived_source is source
    assert archived_source.status == SourceStatus.ARCHIVED
    assert captured["payload"].run_type.value == "delete"
    assert captured["payload"].selected_source_ids == ["src-1"]
    assert captured["payload"].removed_document_ids == ["doc-1", "doc-2"]
    service.session.refresh.assert_called_once_with(source)
    service.audit.record.assert_called_once()


def test_list_base_document_payloads_includes_deleted_entries() -> None:
    service = KnowledgeSourceService.__new__(KnowledgeSourceService)
    service.session = None
    now = datetime.now(UTC)

    active_document = SimpleNamespace(
        document_id="doc-a",
        source_id="src-1",
        title="Architecture Guide",
        uri="file:///active.md",
        document_type=DocumentType.ARCHITECTURE,
        version_label="v1",
        checksum="chk-a",
        status=SourceDocumentStatus.FETCHED,
        registered_at=now,
        discovered_at=now,
        source=SimpleNamespace(name="Repo", source_type=SourceType.REPOSITORY),
    )
    version = SimpleNamespace(
        knowledge_version_id="kv-1",
        knowledge_base_id="kb-1",
        update_run_id="run-1",
        version_documents=[
            SimpleNamespace(
                document=active_document, role_code="reference_only", required_flag=False
            ),
        ],
    )
    deleted_document = SimpleNamespace(
        document_id="doc-b",
        title="Old Policy",
        uri="file:///old.md",
        document_type=DocumentType.NORMATIVE,
        version_label="v0",
        status=SourceDocumentStatus.ARCHIVED,
        registered_at=now,
        discovered_at=now,
        source=SimpleNamespace(name="Repo", source_type=SourceType.REPOSITORY),
    )
    deleted_delta = SimpleNamespace(
        document_id="doc-b",
        source_id="src-1",
        delta_kind=DocumentDeltaKind.DELETED,
        uri="file:///old.md",
        details={},
        checksum_before="chk-b",
    )
    service.versions = SimpleNamespace(
        get_with_documents=lambda knowledge_version_id: version,
        get_active=lambda **kwargs: version,
    )
    service.document_deltas = SimpleNamespace(list_for_run=lambda update_run_id: [deleted_delta])
    service.documents = SimpleNamespace(
        get=lambda document_id: deleted_document if document_id == "doc-b" else None
    )
    service.processing_results = SimpleNamespace(
        list_for_run=lambda update_run_id: [
            SimpleNamespace(
                document_id="doc-a",
                status=SourceProcessingStatus.PARSED,
                error_code=None,
                error_message=None,
            )
        ]
    )
    service.sources = SimpleNamespace(
        get=lambda source_id: SimpleNamespace(name="Repo", source_type=SourceType.REPOSITORY)
    )

    import app.domain.services.knowledge_core as knowledge_core_module

    original_service = knowledge_core_module.KnowledgeBaseService
    knowledge_core_module.KnowledgeBaseService = lambda session: SimpleNamespace(
        get_base=lambda knowledge_base_id: SimpleNamespace(knowledge_base_id="kb-1")
    )
    try:
        rows = KnowledgeSourceService.list_base_document_payloads(
            service, "kb-1", knowledge_version_id="kv-1", include_deleted=True
        )
    finally:
        knowledge_core_module.KnowledgeBaseService = original_service

    assert len(rows) == 2
    present = next(item for item in rows if item["present_in_version"] is True)
    deleted = next(item for item in rows if item["present_in_version"] is False)
    assert present["document_id"] == "doc-a"
    assert present["processing_status"] == "parsed"
    assert deleted["document_id"] == "doc-b"
    assert deleted["delta_kind"] == "deleted"
    assert deleted["title"] == "Old Policy"


def test_delete_run_can_activate_empty_user_version_after_last_document_removed() -> None:
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    candidate = SimpleNamespace(
        version_documents=[],
        knowledge_fragments=[],
        knowledge_base=SimpleNamespace(kind=KnowledgeBaseKind.USER_MANAGED),
        update_run=SimpleNamespace(run_type=UpdateRunType.DELETE),
    )

    validation = KnowledgeUpdateService._validate_candidate_version(
        service,
        candidate,
        selected_sources=[],
        problem_sources=[],
        rules_for_conflicts=[],
    )

    assert validation.run_status == KnowledgeUpdateStatus.COMPLETED
    assert validation.version_status == KnowledgeVersionStatus.VALIDATED
    assert validation.details["validation"] == "passed"
    assert validation.details["empty_knowledge_version"] is True


def test_get_generation_run_payload_exposes_knowledge_scope() -> None:
    read_service = CanonicalReadService.__new__(CanonicalReadService)
    read_service.session = None
    read_service.settings = None
    read_service.tasks = SimpleNamespace(
        _get_task=lambda task_id, principal: SimpleNamespace(clarification_requests=[]),
        _canonical_task_state=lambda task: "ready_for_generation",
    )
    run = SimpleNamespace(
        generation_run_id="gr-1",
        business_task_id="task-1",
        knowledge_version_id="kv-user",
        status=SimpleNamespace(value="queued"),
        current_stage="queued",
        started_at=datetime.now(UTC),
        finished_at=None,
        solution_version=None,
        diagnostics={},
        input_snapshot={
            "knowledge_snapshot": {
                "mandatory_version": {"knowledge_version_id": "kv-mandatory"},
                "selected_user_version": {"knowledge_version_id": "kv-user"},
                "effective_version_ids": ["kv-mandatory", "kv-user"],
                "selected_generation_version_id": "kv-user",
            }
        },
    )

    import app.domain.services.mvp_canonical as mvp_canonical_module

    original_service = mvp_canonical_module.GenerationRunService
    mvp_canonical_module.GenerationRunService = lambda session, settings: SimpleNamespace(
        get_run=lambda run_id, principal: run
    )
    try:
        payload = CanonicalReadService.get_generation_run_payload(
            read_service, "gr-1", _principal()
        )
    finally:
        mvp_canonical_module.GenerationRunService = original_service

    assert payload["knowledge_scope"]["selected_generation_version_id"] == "kv-user"
    assert payload["knowledge_scope"]["effective_version_ids"] == ["kv-mandatory", "kv-user"]


def test_get_verification_run_payload_exposes_knowledge_scope() -> None:
    read_service = CanonicalReadService.__new__(CanonicalReadService)
    read_service.session = None
    read_service.settings = None
    run = SimpleNamespace(
        verification_run_id="vr-1",
        solution_version_id="sol-1",
        knowledge_version_id="kv-user",
        status=SimpleNamespace(value="queued"),
        current_stage="queued",
        started_at=datetime.now(UTC),
        finished_at=None,
        protocol=None,
        diagnostics={},
        scope_snapshot={
            "knowledge_snapshot": {
                "mandatory_version": {"knowledge_version_id": "kv-mandatory"},
                "selected_user_version": {"knowledge_version_id": "kv-user"},
                "effective_version_ids": ["kv-mandatory", "kv-user"],
                "selected_generation_version_id": "kv-user",
            }
        },
    )

    import app.domain.services.mvp_canonical as mvp_canonical_module

    original_service = mvp_canonical_module.VerificationRunService
    mvp_canonical_module.VerificationRunService = lambda session, settings: SimpleNamespace(
        get_run=lambda run_id, principal: run
    )
    try:
        payload = CanonicalReadService.get_verification_run_payload(
            read_service, "vr-1", _principal()
        )
    finally:
        mvp_canonical_module.VerificationRunService = original_service

    assert payload["knowledge_scope"]["selected_generation_version_id"] == "kv-user"
    assert payload["knowledge_scope"]["effective_version_ids"] == ["kv-mandatory", "kv-user"]
