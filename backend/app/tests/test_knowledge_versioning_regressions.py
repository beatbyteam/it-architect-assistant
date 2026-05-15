from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from app.core.security import AuthPrincipal
from app.db.enums import (
    AccountType,
    Criticality,
    DocumentType,
    KnowledgeBaseKind,
    KnowledgeUpdateStatus,
    KnowledgeVersionStatus,
    SourceDocumentStatus,
    SourceScope,
    SourceStatus,
    SourceType,
)
from app.db.models.knowledge import KnowledgeSource, SourceDocument
from app.domain.services.knowledge_core import (
    KnowledgeSourceService,
    KnowledgeUpdateService,
    KnowledgeVersionService,
    ValidationSummary,
)
from app.integrations.knowledge.source_readers import RepositoryReader


def test_repository_reader_refreshes_existing_documents_and_archives_removed(
    tmp_path: Path,
) -> None:
    keep_path = tmp_path / "keep.md"
    keep_path.write_text("# Keep\n", encoding="utf-8")
    source = KnowledgeSource(
        source_type=SourceType.REPOSITORY,
        name="repo",
        base_uri=str(tmp_path),
        criticality=Criticality.REQUIRED,
        status=SourceStatus.ACTIVE,
    )
    existing_keep = SourceDocument(
        source_id=source.source_id,
        document_type=DocumentType.OTHER,
        title="old-title",
        uri=str(keep_path.resolve()),
        is_latest=True,
        status=SourceDocumentStatus.FETCHED,
    )
    removed = SourceDocument(
        source_id=source.source_id,
        document_type=DocumentType.OTHER,
        title="removed.md",
        uri=str((tmp_path / "removed.md").resolve()),
        is_latest=True,
        status=SourceDocumentStatus.REGISTERED,
    )

    documents = RepositoryReader().resolve_documents(source, [existing_keep, removed])

    assert documents == [existing_keep]
    assert existing_keep.title == "keep.md"
    assert existing_keep.media_type == "text/markdown"
    assert existing_keep.status == SourceDocumentStatus.FETCHED
    assert removed.status == SourceDocumentStatus.ARCHIVED
    assert removed.is_latest is False


def test_user_managed_validation_does_not_require_mandatory_baseline() -> None:
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    candidate = SimpleNamespace(
        knowledge_base=SimpleNamespace(kind=KnowledgeBaseKind.USER_MANAGED),
        version_documents=[
            SimpleNamespace(
                role_code="reference_only",
                required_flag=False,
                document=SimpleNamespace(
                    document_id="doc-1",
                    title="Enterprise Architecture Guide",
                    uri="file:///guide.md",
                    version_label="v1",
                    document_type=DocumentType.ARCHITECTURE,
                    source=SimpleNamespace(criticality=Criticality.OPTIONAL),
                ),
            )
        ],
        knowledge_fragments=[object()],
    )

    result = service._validate_candidate_version(candidate, [], [], [])

    assert result.run_status == KnowledgeUpdateStatus.COMPLETED
    assert result.version_status == KnowledgeVersionStatus.VALIDATED
    assert result.details["missing_required_packages"]


def test_activate_supports_reactivating_previous_archived_version() -> None:
    now = datetime.now(UTC)
    previous_active = SimpleNamespace(
        knowledge_version_id="kv-active",
        knowledge_base_id="kb-1",
        version_no="KV-ACTIVE",
        status=KnowledgeVersionStatus.ACTIVE,
        archived_at=None,
    )
    archived = SimpleNamespace(
        knowledge_version_id="kv-archived",
        knowledge_base_id="kb-1",
        version_no="KV-ARCHIVED",
        status=KnowledgeVersionStatus.ARCHIVED,
        summary={"validation": "passed"},
        source_snapshot={},
        version_documents=[],
        created_at=now,
        activated_at=None,
        activated_by_user_id=None,
        activation_metadata=None,
        archived_at=now,
        knowledge_base=None,
    )
    service = KnowledgeVersionService.__new__(KnowledgeVersionService)
    service.session = Mock()
    service.versions = SimpleNamespace(
        get_for_update=lambda knowledge_version_id: archived,
        get_active_for_update=lambda **kwargs: previous_active,
    )
    service.operations = Mock()
    service.audit = Mock()
    principal = AuthPrincipal(
        user_id="user-1",
        login="architect",
        display_name="Architect",
        account_type=AccountType.HUMAN,
        role_codes=["USER"],
    )

    activated = service.activate("kv-archived", principal, reason="rollback", auto_commit=False)

    assert activated is archived
    assert archived.status == KnowledgeVersionStatus.ACTIVE
    assert archived.activated_by_user_id == "user-1"
    assert previous_active.status == KnowledgeVersionStatus.VALIDATED


def test_activate_user_managed_validated_version_allows_missing_required_packages() -> None:
    version = SimpleNamespace(
        knowledge_version_id="kv-user",
        knowledge_base_id="kb-user",
        version_no="KV-USER",
        status=KnowledgeVersionStatus.VALIDATED,
        summary={
            "validation": "passed",
            "missing_required_packages": ["oda", "archimate_3_2"],
            "required_source_failures": [],
        },
        source_snapshot={},
        version_documents=[],
        created_at=datetime.now(UTC),
        activated_at=None,
        activated_by_user_id=None,
        activation_metadata=None,
        archived_at=None,
        knowledge_base=SimpleNamespace(
            kind=KnowledgeBaseKind.USER_MANAGED,
            preferred_embedding_space_id=None,
        ),
        embedding_space_id=None,
        embedding_space=None,
    )
    service = KnowledgeVersionService.__new__(KnowledgeVersionService)
    service.session = Mock()
    service.versions = SimpleNamespace(
        get_for_update=lambda knowledge_version_id: version,
        get_active_for_update=lambda **kwargs: None,
    )
    service.operations = Mock()
    service.audit = Mock()
    principal = AuthPrincipal(
        user_id="user-1",
        login="architect",
        display_name="Architect",
        account_type=AccountType.HUMAN,
        role_codes=["USER"],
    )

    activated = service.activate("kv-user", principal, reason="upload", auto_commit=False)

    assert activated is version
    assert version.status == KnowledgeVersionStatus.ACTIVE
    service.session.commit.assert_not_called()


def test_execute_run_records_automatic_activation() -> None:
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    service.session = Mock()
    service.audit = Mock()
    service.settings = SimpleNamespace(knowledge_sync_sla_seconds=3600)
    service.embeddings = SimpleNamespace(
        describe=lambda: {"provider_name": "stub", "model_id": "stub", "dimensions": 1}
    )
    service.documents = SimpleNamespace(list_for_source=lambda *args, **kwargs: [])
    service.versions = SimpleNamespace(get_active=lambda **kwargs: None)
    service.document_deltas = SimpleNamespace(
        summarize_for_run=lambda update_run_id: {
            "new": 0,
            "changed": 0,
            "deleted": 0,
            "unchanged": 0,
        }
    )
    service.get_run = lambda update_run_id: run
    service._get_or_create_candidate_version = lambda _run: candidate
    service._resolve_scope_sources = lambda *args, **kwargs: []
    service._set_stage = lambda *args, **kwargs: None
    service._validate_candidate_version = lambda *args, **kwargs: ValidationSummary(
        run_status=KnowledgeUpdateStatus.COMPLETED,
        version_status=KnowledgeVersionStatus.VALIDATED,
        details={"validation": "passed"},
    )
    service._build_source_snapshot = lambda *args, **kwargs: {}
    service._build_active_diff_summary = lambda *args, **kwargs: None
    service._record_operation_step = lambda *args, **kwargs: None

    def _activate(_candidate, _run):
        _candidate.status = KnowledgeVersionStatus.ACTIVE
        _candidate.activation_metadata = {"auto": True}
        return _candidate

    service._auto_activate_candidate_version = _activate

    now = datetime.now(UTC)
    run = SimpleNamespace(
        update_run_id="run-1",
        knowledge_base_id="kb-1",
        status=KnowledgeUpdateStatus.QUEUED,
        current_stage="queued",
        scope={"source_scope": "all", "selected_source_ids": [], "requested_by": "system"},
        started_at=now,
        finished_at=None,
        duration_sec=None,
        summary={},
        initiator_user_id=None,
        correlation_id="corr-1",
    )
    candidate = SimpleNamespace(
        knowledge_version_id="kv-1",
        knowledge_base_id="kb-1",
        status=KnowledgeVersionStatus.DRAFT,
        summary=None,
        source_snapshot=None,
        activation_metadata=None,
        version_documents=[],
        knowledge_fragments=[object()],
        document_snapshots=[],
        normative_rules=[],
    )

    completed_run = service.execute_run("run-1")

    assert completed_run.current_stage == KnowledgeVersionStatus.ACTIVE.value
    assert completed_run.summary["activated_knowledge_version_id"] == "kv-1"
    assert completed_run.summary["activation_metadata"] == {"auto": True}
    assert any(item["stage"] == "active" for item in completed_run.summary["stage_history"])


def test_manual_run_uses_settings_default_inline_execution() -> None:
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    service.settings = SimpleNamespace(knowledge_execute_inline=True)
    captured: dict[str, object] = {}

    def _create_run(*, payload, initiator_user_id, audit_message, execute_inline):
        captured["execute_inline"] = execute_inline
        return SimpleNamespace(update_run_id="run-1")

    service._create_run = _create_run

    run = KnowledgeUpdateService.start_manual_run(
        service,
        knowledge_base_id="kb-1",
        source_scope=SourceScope.ALL,
    )

    assert run.update_run_id == "run-1"
    assert captured["execute_inline"] is True


def test_register_document_prefers_uri_for_type_inference_when_title_is_arbitrary() -> None:
    service = KnowledgeSourceService.__new__(KnowledgeSourceService)
    service.session = Mock()
    service.audit = Mock()
    service.documents = SimpleNamespace(
        get_by_source_and_uri=lambda source_id, uri: None,
        unset_latest_for_uri=lambda *args, **kwargs: None,
        add=lambda document: None,
    )
    source = SimpleNamespace(source_id="source-1")
    service.get_source = lambda source_id: source
    service._assert_source_mutable = lambda *args, **kwargs: None
    service._validate_document_uri = lambda uri, **kwargs: None

    principal = AuthPrincipal(
        user_id="user-1",
        login="architect",
        display_name="Architect",
        account_type=AccountType.HUMAN,
        role_codes=["USER"],
    )

    payload = SimpleNamespace(
        document_type=DocumentType.OTHER,
        title="с",
        uri="file:///selected_technology_standard.md",
        version_label=None,
        checksum=None,
        is_latest=True,
    )

    document = KnowledgeSourceService.register_document(service, "source-1", payload, principal)

    assert document.document_type == DocumentType.NORMATIVE
