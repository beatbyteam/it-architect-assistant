from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.v1.routes import mvp as mvp_routes
from app.core.security import AuthPrincipal
from app.db.enums import (
    AccountType,
    Criticality,
    DocumentType,
    KnowledgeUpdateStatus,
    KnowledgeVersionStatus,
    SourceDocumentStatus,
    SourceProcessingStatus,
    SourceScope,
    SourceStatus,
    SourceType,
    UpdateRunType,
)
from app.db.models.knowledge import (
    KnowledgeSource,
    KnowledgeUpdateRun,
    KnowledgeVersion,
    SourceDocument,
)
from app.domain.services.knowledge.update_runtime import execute_knowledge_update_run
from app.domain.services.knowledge.update_service import KnowledgeUpdateService, ValidationSummary
from app.domain.services.knowledge_query import KnowledgeQueryService
from app.domain.services.knowledge_snapshot import build_knowledge_version_snapshot
from app.integrations.knowledge.content_loader import NormalizedDocument, StructuredSection
from app.integrations.knowledge.source_readers import RepositoryReader, UrlListReader


class _ProcessingResultsRepo:
    def __init__(self) -> None:
        self.items: list[object] = []

    def get_for_scope(self, **_kwargs):
        return None

    def add(self, entity: object) -> None:
        self.items.append(entity)


class _Session:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.commits = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def delete(self, obj: object) -> None:
        self.deleted.append(obj)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _obj: object) -> None:
        return None

    def rollback(self) -> None:
        return None

    def scalars(self, *_args, **_kwargs):
        return []


class _DocumentsRepo:
    def __init__(self, documents: list[SourceDocument]) -> None:
        self.documents = documents

    def list_for_source(
        self, source_id: str, include_archived: bool = True
    ) -> list[SourceDocument]:
        return [item for item in self.documents if str(item.source_id) == str(source_id)]

    def add(self, document: SourceDocument) -> None:
        if document not in self.documents:
            self.documents.append(document)


def test_mvp_list_tasks_uses_canonical_task_state_for_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    tasks = [
        SimpleNamespace(business_task_id="task-1", title="Alpha integration"),
        SimpleNamespace(business_task_id="task-2", title="Beta migration"),
    ]
    state_by_id = {"task-1": "ready_for_generation", "task-2": "draft"}

    class _FakeCanonicalTaskService:
        def __init__(self, session, settings) -> None:
            self.session = session
            self.settings = settings
            self.tasks = SimpleNamespace()

        def list_tasks(self, principal):
            return tasks

        def _canonical_task_state(self, task) -> str:
            return state_by_id[str(task.business_task_id)]

    class _FakeCanonicalReadService:
        def __init__(self, session, settings) -> None:
            self.session = session
            self.settings = settings

        def build_task_snapshot(self, task) -> dict[str, object]:
            return {
                "task_id": str(task.business_task_id),
                "title": task.title,
                "state": state_by_id[str(task.business_task_id)],
                "created_at": now,
                "updated_at": now,
                "latest_knowledge_version_id": None,
                "open_clarification_count": 0,
                "overdue_clarification_flag": False,
            }

    monkeypatch.setattr(mvp_routes, "CanonicalTaskService", _FakeCanonicalTaskService)
    monkeypatch.setattr(mvp_routes, "CanonicalReadService", _FakeCanonicalReadService)

    principal = AuthPrincipal(
        user_id="user-1",
        login="alice",
        display_name="Alice",
        account_type=AccountType.HUMAN,
        role_codes=["USER"],
    )

    result = mvp_routes.list_tasks(
        session=object(),
        settings=object(),
        principal=principal,
        state="ready_for_generation",
        search="alpha",
        limit=10,
        _guard=principal,
    )

    assert [item.task_id for item in result] == ["task-1"]


def test_build_knowledge_version_snapshot_serializes_uuid_fields() -> None:
    version_id = uuid4()
    base_id = uuid4()
    document_id = uuid4()
    created_at = datetime.now(UTC)
    version = SimpleNamespace(
        knowledge_version_id=version_id,
        knowledge_base_id=base_id,
        knowledge_base=SimpleNamespace(code="kb-user"),
        version_no=3,
        status=KnowledgeVersionStatus.VALIDATED,
        created_at=created_at,
        activated_at=None,
        activated_by_user_id=None,
        source_snapshot={
            "source_scope": "selected",
            "selected_source_ids": [str(uuid4())],
            "sources": [{"source_id": "src-1"}],
        },
        version_documents=[
            SimpleNamespace(
                document_id=document_id,
                title="Reference",
                role_code="oda",
                version_ref="v1",
                required_flag=True,
            )
        ],
    )

    snapshot = build_knowledge_version_snapshot(version)

    assert snapshot["knowledge_version_id"] == str(version_id)
    assert snapshot["knowledge_base_id"] == str(base_id)
    assert snapshot["basis_documents"][0]["document_id"] == str(document_id)
    assert snapshot["created_at"] == created_at.isoformat()
    assert snapshot["snapshot_hash"]


def test_mark_source_failure_can_keep_source_active_for_document_errors() -> None:
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    service.processing_results = _ProcessingResultsRepo()
    service.session = _Session()

    run = KnowledgeUpdateRun(
        update_run_id="run-1",
        knowledge_base_id="kb-1",
        run_type=UpdateRunType.MANUAL,
        status=KnowledgeUpdateStatus.RUNNING,
    )
    source = KnowledgeSource(
        source_id="src-1",
        knowledge_base_id="kb-1",
        source_type=SourceType.URL_LIST,
        name="Portal",
        criticality=Criticality.REQUIRED,
        status=SourceStatus.ACTIVE,
    )
    document = SourceDocument(
        document_id="doc-1",
        source_id="src-1",
        document_type=DocumentType.NORMATIVE,
        title="Guide",
        uri="https://example.com/guide.md",
        status=SourceDocumentStatus.REGISTERED,
    )

    payload = KnowledgeUpdateService._mark_source_failure(
        service,
        run,
        source,
        document,
        "PARSE_FAILED",
        "bad format",
        stage="parsing",
        deactivate_source=False,
    )

    assert source.status == SourceStatus.ACTIVE
    assert payload["stage"] == "parsing"
    assert service.processing_results.items[-1].status == SourceProcessingStatus.FAILED


def test_run_due_scheduled_syncs_starts_new_source_immediately() -> None:
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    now = datetime.now(UTC)
    base = SimpleNamespace(knowledge_base_id="kb-1", status=SourceStatus.ACTIVE)
    new_source = SimpleNamespace(
        source_id="src-new",
        refresh_policy="monthly",
        last_discovered_at=None,
        created_at=now - timedelta(hours=2),
    )
    service.settings = SimpleNamespace(knowledge_auto_sync_interval_days=30)
    service.sources = SimpleNamespace(list_active=lambda knowledge_base_id=None: [new_source])
    service.processing_results = SimpleNamespace(
        get_latest_success_for_source=lambda _source_id: None
    )
    service._list_visible_bases = lambda principal=None: [base]
    created_payloads: list[object] = []

    def _call_create_run(**kwargs):
        created_payloads.append(kwargs["payload"])
        return SimpleNamespace(update_run_id="run-1", knowledge_base_id="kb-1")

    service._call_create_run = _call_create_run
    service._settings_value = lambda name, default=None: getattr(service.settings, name, default)
    service._run_identifier = lambda run, field: getattr(run, field, None)

    payload = KnowledgeUpdateService.run_due_scheduled_syncs(service, now=now, execute_inline=False)

    assert payload["started_run_ids"] == ["run-1"]
    assert created_payloads[0].selected_source_ids == ["src-new"]


def test_repository_reader_discovers_txt_and_json_and_respects_depth_limit(tmp_path) -> None:
    (tmp_path / "policy.txt").write_text("shall", encoding="utf-8")
    (tmp_path / "catalog.json").write_text('{"ok": true}', encoding="utf-8")
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "too_deep.md").write_text("ignore", encoding="utf-8")
    source = KnowledgeSource(
        source_type=SourceType.REPOSITORY,
        name="repo",
        base_uri=tmp_path.as_uri(),
        criticality=Criticality.REQUIRED,
        status=SourceStatus.ACTIVE,
    )

    documents = RepositoryReader().resolve_documents(source, [])

    assert sorted(item.title for item in documents) == ["catalog.json", "policy.txt"]


def test_remote_plaintext_seed_is_parsed_as_url_list(monkeypatch) -> None:
    source = KnowledgeSource(
        source_type=SourceType.URL_LIST,
        name="seed",
        base_uri="https://example.com/list.txt",
        criticality=Criticality.REQUIRED,
        status=SourceStatus.ACTIVE,
    )

    class _DummyClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, exc, _tb):
            return False

    monkeypatch.setattr("app.integrations.knowledge.source_readers.httpx.Client", _DummyClient)
    monkeypatch.setattr(
        "app.integrations.knowledge.source_readers._fetch_remote_discovery_page",
        lambda client, current: (
            current,
            "text/plain",
            "https://example.com/a.json\nhttps://example.com/download?id=42\n",
        ),
    )

    documents = UrlListReader().resolve_documents(source, [])

    assert [item.uri for item in documents] == [
        "https://example.com/a.json",
        "https://example.com/download?id=42",
    ]


def test_html_discovery_accepts_suffixless_download_links() -> None:
    source = KnowledgeSource(
        source_type=SourceType.URL_LIST,
        name="portal",
        base_uri="https://example.com/index.html",
        criticality=Criticality.REQUIRED,
        status=SourceStatus.ACTIVE,
    )

    docs = UrlListReader()._documents_from_html(
        source,
        "https://example.com/portal/page",
        '<a href="/download?id=7" download>Spec export</a>',
    )

    assert [item.uri for item in docs] == ["https://example.com/download?id=7"]


def test_db_vector_search_is_enabled_for_matching_versioned_embedding_space() -> None:
    service = KnowledgeQueryService.__new__(KnowledgeQueryService)
    service.session = SimpleNamespace(
        get=lambda model, key: KnowledgeVersion(
            knowledge_version_id="kv-1",
            knowledge_base_id="kb-1",
            version_no="KV-1",
            update_run_id="run-1",
            embedding_space_id="space-1",
            status=KnowledgeVersionStatus.ACTIVE,
        )
    )

    supported = KnowledgeQueryService._supports_db_vector_search(
        service,
        active_space=SimpleNamespace(embedding_space_id="space-1"),
        knowledge_version_id="kv-1",
    )

    assert supported is True


def test_db_vector_search_is_disabled_for_mismatched_versioned_embedding_space() -> None:
    service = KnowledgeQueryService.__new__(KnowledgeQueryService)
    service.session = SimpleNamespace(
        get=lambda model, key: KnowledgeVersion(
            knowledge_version_id="kv-1",
            knowledge_base_id="kb-1",
            version_no="KV-1",
            update_run_id="run-1",
            embedding_space_id="space-1",
            status=KnowledgeVersionStatus.ACTIVE,
        )
    )

    supported = KnowledgeQueryService._supports_db_vector_search(
        service,
        active_space=SimpleNamespace(embedding_space_id="space-2"),
        knowledge_version_id="kv-1",
    )

    assert supported is False


def test_execute_run_cleans_failed_document_artifacts_on_indexing_error(monkeypatch) -> None:
    source = KnowledgeSource(
        source_id="src-1",
        knowledge_base_id="kb-1",
        source_type=SourceType.URL_LIST,
        name="Portal",
        base_uri="https://example.com/index.html",
        criticality=Criticality.REQUIRED,
        status=SourceStatus.ACTIVE,
    )
    document = SourceDocument(
        document_id="doc-1",
        source_id=source.source_id,
        document_type=DocumentType.NORMATIVE,
        title="Standard",
        uri="https://example.com/standard.md",
        status=SourceDocumentStatus.REGISTERED,
        is_latest=True,
    )
    document.source = source
    run = KnowledgeUpdateRun(
        update_run_id="run-1",
        knowledge_base_id="kb-1",
        run_type=UpdateRunType.MANUAL,
        status=KnowledgeUpdateStatus.QUEUED,
        current_stage="queued",
        scope={
            "source_scope": SourceScope.ALL.value,
            "selected_source_ids": [str(source.source_id)],
        },
        summary={"stage_history": []},
        started_at=datetime.now(UTC),
    )
    candidate = KnowledgeVersion(
        knowledge_version_id="kv-1",
        knowledge_base_id="kb-1",
        update_run_id=run.update_run_id,
        version_no="KV-1",
        status=KnowledgeVersionStatus.DRAFT,
    )
    candidate.version_documents = []
    candidate.knowledge_fragments = []
    candidate.normative_rules = []
    candidate.extracted_items = []

    service = SimpleNamespace()
    service.settings = SimpleNamespace(
        knowledge_fetch_timeout_sec=1.0,
        knowledge_max_document_size_bytes=10_000,
        knowledge_chunk_target_tokens=800,
        knowledge_chunk_overlap_pct=15,
        knowledge_chunk_max_chars=6000,
        knowledge_sync_sla_seconds=3600,
    )
    service.session = _Session()
    service.audit = SimpleNamespace(record=lambda **kwargs: None)
    service.documents = _DocumentsRepo([document])
    service.versions = SimpleNamespace(get_active=lambda **kwargs: None)
    service.document_snapshots = SimpleNamespace(
        get_latest_for_document=lambda *args, **kwargs: None
    )
    service.document_chunks = SimpleNamespace(list_for_snapshot=lambda snapshot_id: [])
    service.extracted_items = SimpleNamespace(list_for_document=lambda *args, **kwargs: [])
    service.document_deltas = SimpleNamespace(summarize_for_run=lambda update_run_id: {})
    service.embeddings = SimpleNamespace(
        describe=lambda: {
            "provider_name": "stub",
            "model_id": "stub",
            "dimensions": 3,
            "profile_code": "stub-profile",
        },
        encode_documents=lambda texts, titles=None: (_ for _ in ()).throw(
            RuntimeError("embed failure")
        ),
    )
    service._embedding_service_for_profile = lambda profile: service.embeddings
    service.resolve_embedding_space = lambda **kwargs: SimpleNamespace(
        embedding_space_id="space-1", code="stub-profile"
    )
    service.get_run = lambda update_run_id: run
    service._get_or_create_candidate_version = lambda _current_run: candidate
    service._resolve_scope_sources = lambda source_scope, selected_source_ids, knowledge_base_id: [
        source
    ]
    service._probe_source_availability = lambda source_type, base_uri: {"ok": True}
    service._resolve_documents_for_source = lambda source_obj, documents: [document]
    service._set_stage = lambda *args, **kwargs: None
    service._ensure_within_sla = lambda *args, **kwargs: None
    service._build_source_snapshot = lambda *args, **kwargs: {"sources": ["src-1"]}
    service._build_active_diff_summary = lambda candidate_obj: {
        "added_document_count": len(candidate_obj.version_documents)
    }
    service._append_stage_history = lambda history, stage, **kwargs: [
        *history,
        {"stage": stage, **kwargs},
    ]
    service._record_operation_step = lambda *args, **kwargs: None
    service._record_document_delta = lambda *args, **kwargs: None
    service._classify_document_error_code = (
        lambda message, default="DOCUMENT_PROCESSING_FAILED": default
    )
    recorded_failures: list[dict[str, object]] = []
    service._mark_source_failure = (
        lambda _run_obj,
        source_obj,
        document_obj,
        error_code,
        message,
        stage="",
        deactivate_source=True: recorded_failures.append(
            {
                "source_id": str(source_obj.source_id),
                "document_id": str(document_obj.document_id) if document_obj is not None else None,
                "stage": stage,
                "error_code": error_code,
                "error_message": message,
                "deactivate_source": deactivate_source,
            }
        )
        or recorded_failures[-1]
    )
    service._upsert_processing_result = lambda *args, **kwargs: None
    service._validate_candidate_version = lambda *args, **kwargs: ValidationSummary(
        run_status=KnowledgeUpdateStatus.COMPLETED,
        version_status=KnowledgeVersionStatus.VALIDATED,
        details={
            "validation": "passed",
            "required_source_failures": [],
            "missing_required_packages": [],
        },
    )
    service._auto_activate_candidate_version = lambda candidate_obj, _run_obj: None

    monkeypatch.setattr(
        "app.domain.services.knowledge_core.fetch_uri",
        lambda uri, timeout_sec=10.0, max_size_bytes=None: (b"# Title\nBody", uri, "text/markdown"),
    )
    monkeypatch.setattr(
        "app.domain.services.knowledge_core.normalize_document_payload",
        lambda uri, data, media_type=None: NormalizedDocument(
            text="# Title\nBody",
            content_format="text/markdown",
            parser_name="markdown",
            sections=[
                StructuredSection(heading="Title", content="Body", source_location="lines:1-2")
            ],
            metadata={},
        ),
    )
    monkeypatch.setattr(
        "app.domain.services.knowledge_core.resolve_basis_assignment",
        lambda document_obj: ("reference_only", False),
    )
    monkeypatch.setattr(
        "app.domain.services.knowledge.update_runtime.prepare_document_index",
        lambda normalized,
        document_type=None,
        document_title=None,
        chunk_target_tokens=800,
        chunk_overlap_pct=15,
        chunk_max_chars=6000: SimpleNamespace(
            chunks=[
                SimpleNamespace(
                    content="Body",
                    title="Title",
                    source_location="lines:1-2",
                    metadata={},
                    fragment_type="rule",
                )
            ],
            canonical_metadata={},
            metrics={},
        ),
    )

    result = execute_knowledge_update_run(service, str(run.update_run_id))

    assert result.status == KnowledgeUpdateStatus.COMPLETED
    assert document.status == SourceDocumentStatus.FAILED
    assert candidate.version_documents == []
    assert candidate.knowledge_fragments == []
    assert candidate.normative_rules == []
    assert candidate.extracted_items == []
    assert recorded_failures == [
        {
            "source_id": "src-1",
            "document_id": "doc-1",
            "stage": "indexing",
            "error_code": "INDEXING_FAILED",
            "error_message": "embed failure",
            "deactivate_source": False,
        }
    ]
