from __future__ import annotations

from types import SimpleNamespace

from app.db.enums import (
    Criticality,
    DocumentType,
    SourceDocumentStatus,
    SourceScope,
    SourceStatus,
    SourceType,
)
from app.db.models.knowledge import KnowledgeSource, SourceDocument
from app.domain.services.knowledge.update_service import KnowledgeUpdateService
from app.integrations.knowledge.source_readers import (
    RepositoryReader,
    mark_document_explicitly_excluded,
)
from app.schemas.knowledge import KnowledgeUpdateRunStartRequest, SourceDocumentUpdateRequest


def test_source_document_update_request_rejects_indexed_field_mutations() -> None:
    try:
        SourceDocumentUpdateRequest(uri="file:///new.md")
    except Exception as exc:  # pydantic validation error shape depends on version
        assert "Direct document content mutations are not allowed" in str(exc)
    else:
        raise AssertionError("Expected indexed-field patch validation to fail")


def test_repository_reader_keeps_explicitly_excluded_document_archived_when_rediscovered(
    tmp_path,
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
    excluded = SourceDocument(
        source_id=source.source_id,
        document_type=DocumentType.OTHER,
        title="keep.md",
        uri=str(keep_path.resolve()),
        is_latest=False,
        status=SourceDocumentStatus.ARCHIVED,
    )
    mark_document_explicitly_excluded(excluded, reason="removed")

    documents = RepositoryReader().resolve_documents(source, [excluded])

    assert documents == []
    assert excluded.status == SourceDocumentStatus.ARCHIVED
    assert excluded.is_latest is False
    assert (
        excluded.document_metadata and excluded.document_metadata.get("knowledge_excluded") is True
    )


def test_resolve_scope_sources_allows_selected_disabled_source() -> None:
    disabled_source = SimpleNamespace(
        source_id="src-disabled", status=SourceStatus.DISABLED, criticality=Criticality.OPTIONAL
    )

    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    service.sources = SimpleNamespace(
        list_active=lambda **kwargs: [],
        list_visible=lambda **kwargs: [disabled_source],
    )

    selected = KnowledgeUpdateService._resolve_scope_sources(
        service,
        SourceScope.SELECTED,
        ["src-disabled"],
        knowledge_base_id="kb-1",
    )

    assert selected == [disabled_source]


def test_build_public_start_payload_preserves_removed_document_ids() -> None:
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    principal = SimpleNamespace(user_id="user-1", login="architect", display_name="Architect")
    payload = KnowledgeUpdateRunStartRequest(
        knowledge_base_id="kb-1",
        source_scope="selected",
        selected_source_ids=["src-1"],
        removed_document_ids=["doc-1", "doc-1", "doc-2"],
    )

    internal = KnowledgeUpdateService.build_public_start_payload(service, payload, principal)

    assert internal.removed_document_ids == ["doc-1", "doc-2"]


def test_get_run_status_payload_does_not_create_candidate_version_when_missing() -> None:
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    run = SimpleNamespace(
        update_run_id="run-1",
        knowledge_base_id="kb-1",
        scope={"source_scope": "selected", "selected_source_ids": ["src-1"]},
    )
    service.get_run = lambda update_run_id, principal=None: run
    service._maybe_resume_queued_run_inline = lambda item: item
    service._serialize_run = lambda item: {"update_run_id": "run-1"}
    service.versions = SimpleNamespace(get_by_update_run_id=lambda update_run_id: None)
    service._resolve_scope_sources = (
        lambda source_scope, selected_source_ids, knowledge_base_id=None: [
            SimpleNamespace(
                source_id="src-1",
                name="Source 1",
                source_type=SourceType.REPOSITORY,
                criticality=Criticality.OPTIONAL,
                status=SourceStatus.ACTIVE,
            )
        ]
    )
    service._build_source_snapshot = lambda selected_sources, run, include_processing=False: {
        "sources": [{"source_id": "src-1"}],
        "captured_at": "now",
    }

    payload = KnowledgeUpdateService.get_run_status_payload(service, "run-1")

    assert payload["source_snapshot"] == {"sources": [{"source_id": "src-1"}], "captured_at": "now"}
