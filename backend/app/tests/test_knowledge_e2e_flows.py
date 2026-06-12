from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from app.core.security import AuthPrincipal
from app.db.enums import (
    AccountType,
    BusinessTaskStatus,
    Criticality,
    DocumentDeltaKind,
    DocumentType,
    GenerationRunStatus,
    KnowledgeBaseKind,
    KnowledgeBaseStatus,
    KnowledgeUpdateStatus,
    KnowledgeVersionStatus,
    SourceDocumentStatus,
    SourceScope,
    SourceStatus,
    SourceType,
    UpdateRunType,
)
from app.db.models.generation import GenerationRun
from app.db.models.knowledge import (
    DocumentChunk,
    DocumentDelta,
    DocumentSnapshot,
    KnowledgeBase,
    KnowledgeSource,
    KnowledgeUpdateRun,
    KnowledgeVersion,
    KnowledgeVersionDocument,
    SourceDocument,
)
from app.domain.services.generation_core import GenerationRunService
from app.domain.services.knowledge_bases import EffectiveKnowledgeScope
from app.domain.services.knowledge_core import (
    KnowledgeSourceService,
    KnowledgeUpdateService,
    KnowledgeVersionService,
    ValidationSummary,
)
from app.integrations.knowledge.content_loader import checksum_sha256
from app.schemas.generation import InternalGenerationRunStartRequest


class InMemoryDocumentSnapshotRepo:
    def __init__(self) -> None:
        self.items: list[DocumentSnapshot] = []

    def get_latest_for_document(self, document_id: str, *, knowledge_version_id: str | None = None):
        matches = [
            item
            for item in self.items
            if str(item.document_id) == str(document_id)
            and (
                knowledge_version_id is None
                or str(item.knowledge_version_id) == str(knowledge_version_id)
            )
        ]
        return matches[-1] if matches else None


class InMemoryDocumentChunkRepo:
    def __init__(self) -> None:
        self.items: list[DocumentChunk] = []

    def list_for_snapshot(self, document_snapshot_id: str) -> list[DocumentChunk]:
        return [
            item
            for item in self.items
            if str(item.document_snapshot_id) == str(document_snapshot_id)
        ]


class InMemoryDocumentDeltaRepo:
    def __init__(self) -> None:
        self.items: list[DocumentDelta] = []

    def add(self, delta: DocumentDelta) -> None:
        self.items.append(delta)

    def list_for_run(self, update_run_id: str) -> list[DocumentDelta]:
        return [item for item in self.items if str(item.update_run_id) == str(update_run_id)]

    def summarize_for_run(self, update_run_id: str) -> dict[str, int]:
        counters = {"new": 0, "changed": 0, "deleted": 0, "unchanged": 0}
        for item in self.list_for_run(update_run_id):
            counters[getattr(item.delta_kind, "value", item.delta_kind)] += 1
        return counters


class InMemoryDocumentsRepo:
    def __init__(self, items: list[SourceDocument]) -> None:
        self.items = items

    def list_for_source(
        self, source_id: str, include_archived: bool = True
    ) -> list[SourceDocument]:
        if include_archived:
            return [item for item in self.items if str(item.source_id) == str(source_id)]
        return [
            item
            for item in self.items
            if str(item.source_id) == str(source_id)
            and getattr(item, "status", None) != SourceDocumentStatus.ARCHIVED
        ]

    def add(self, document: SourceDocument) -> None:
        if getattr(document, "document_id", None) is None:
            document.document_id = f"doc-{len(self.items) + 1}"
        if document not in self.items:
            self.items.append(document)

    def get(self, document_id: str):
        for item in self.items:
            if str(item.document_id) == str(document_id):
                return item
        return None


class FakeSession:
    def __init__(
        self, snapshot_repo: InMemoryDocumentSnapshotRepo, chunk_repo: InMemoryDocumentChunkRepo
    ) -> None:
        self.snapshot_repo = snapshot_repo
        self.chunk_repo = chunk_repo
        self.added: list[object] = []
        self.commits = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)
        if isinstance(obj, DocumentSnapshot) and obj not in self.snapshot_repo.items:
            self.snapshot_repo.items.append(obj)
        elif isinstance(obj, DocumentChunk) and obj not in self.chunk_repo.items:
            self.chunk_repo.items.append(obj)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, obj: object) -> None:
        return None

    def expire_all(self) -> None:
        return None

    def scalars(self, *_args, **_kwargs):
        return []


class FakeExtractedItemsRepo:
    def __init__(self, items: list[object] | None = None) -> None:
        self.items = items or []

    def list_for_document(
        self, document_id: str, *, knowledge_version_id: str | None = None
    ) -> list[object]:
        return [
            item
            for item in self.items
            if str(item.document_id) == str(document_id)
            and (
                knowledge_version_id is None
                or str(item.knowledge_version_id) == str(knowledge_version_id)
            )
        ]


class FakeGenerationSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def expire_all(self) -> None:
        return None


class FakeIdempotency:
    def resolve_existing(self, **_kwargs):
        return None

    def register(self, **_kwargs) -> None:
        return None


class FakeEmbeddings:
    def describe(self) -> dict[str, object]:
        return {"provider_name": "stub", "model_id": "stub-embed", "dimensions": 3}

    def encode_texts(self, texts: list[str]):
        return SimpleNamespace(vectors=[[0.1, 0.2, 0.3] for _ in texts])


class FakeOperations:
    def record_step(self, **_kwargs) -> None:
        return None


class FakeRunRepository:
    def get_running_for_task(self, _business_task_id: str):
        return None


def _principal() -> AuthPrincipal:
    return AuthPrincipal(
        user_id="user-1",
        login="architect",
        display_name="Architect",
        account_type=AccountType.HUMAN,
        role_codes=["USER"],
    )


def _service_principal() -> AuthPrincipal:
    return AuthPrincipal(
        user_id="svc-1",
        login="knowledge.worker",
        display_name="Knowledge Worker",
        account_type=AccountType.SERVICE,
        role_codes=["SERVICE"],
    )


def _make_generation_service(
    *, selected_user_version: KnowledgeVersion, mandatory_version: KnowledgeVersion | None = None
) -> GenerationRunService:
    service = GenerationRunService.__new__(GenerationRunService)
    service.session = FakeGenerationSession()
    service.settings = SimpleNamespace(
        generation_execute_inline=True, app_env="dev", llm_model_id="stub-llm"
    )
    service.idempotency = FakeIdempotency()
    service.runs = FakeRunRepository()
    service.audit = Mock()
    service.operations = FakeOperations()
    service.prompt_registry = SimpleNamespace(
        get_generation_template=lambda: SimpleNamespace(
            version_id="prompt-v1",
            template_name="canonical-generation",
            output_contract_name="generation_solution_v1",
        )
    )
    service.retrieval = SimpleNamespace(
        knowledge_query=SimpleNamespace(embeddings=FakeEmbeddings())
    )
    service._record_operation_step = lambda *args, **kwargs: None
    task = SimpleNamespace(
        business_task_id="task-1",
        title="Создать архитектурное решение",
        task_text="Нужно подготовить архитектуру интеграционного решения для CRM и Billing.",
        task_metadata={},
        clarification_requests=[],
        status=BusinessTaskStatus.READY_FOR_GENERATION,
    )
    service._get_task = lambda business_task_id: task
    service.execute_run = lambda run_id: next(
        item for item in reversed(service.session.added) if isinstance(item, GenerationRun)
    )

    effective_scope = EffectiveKnowledgeScope(
        mandatory_base=KnowledgeBase(
            code="mandatory_architecture_baseline",
            name="Mandatory Architecture Baseline",
            kind=KnowledgeBaseKind.SYSTEM_MANDATORY,
            status=KnowledgeBaseStatus.ACTIVE,
        ),
        mandatory_version=mandatory_version,
        selected_user_base=KnowledgeBase(
            code="user-kb",
            name="User KB",
            kind=KnowledgeBaseKind.USER_MANAGED,
            status=KnowledgeBaseStatus.ACTIVE,
        ),
        selected_user_version=selected_user_version,
    )

    import app.domain.services.generation_core as generation_core_module

    original_service = generation_core_module.KnowledgeBaseService
    generation_core_module.KnowledgeBaseService = lambda session: SimpleNamespace(
        get_effective_scope=lambda: effective_scope
    )
    service._restore_base_service = (generation_core_module, original_service)
    return service


def _restore_generation_service(service: GenerationRunService) -> None:
    module, original_service = service._restore_base_service
    module.KnowledgeBaseService = original_service


def _make_update_service(
    *,
    source: KnowledgeSource,
    documents: list[SourceDocument],
    active_version: KnowledgeVersion | None = None,
):
    snapshot_repo = InMemoryDocumentSnapshotRepo()
    chunk_repo = InMemoryDocumentChunkRepo()
    delta_repo = InMemoryDocumentDeltaRepo()
    session = FakeSession(snapshot_repo, chunk_repo)
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    service.session = session
    service.settings = SimpleNamespace(
        app_env="dev",
        knowledge_fetch_timeout_sec=2.0,
        knowledge_max_document_size_bytes=2_000_000,
        knowledge_chunk_max_chars=800,
        knowledge_sync_sla_seconds=3600,
    )
    service.audit = Mock()
    service.operations = FakeOperations()
    service.idempotency = FakeIdempotency()
    service.embeddings = FakeEmbeddings()
    service.documents = InMemoryDocumentsRepo(documents)
    service.versions = SimpleNamespace(get_active=lambda **kwargs: active_version)
    service.document_snapshots = snapshot_repo
    service.document_chunks = chunk_repo
    service.extracted_items = FakeExtractedItemsRepo([])
    service.document_deltas = delta_repo
    service._set_stage = lambda *args, **kwargs: None
    service._upsert_processing_result = lambda *args, **kwargs: None
    service._record_operation_step = lambda *args, **kwargs: None
    service._probe_source_availability = lambda source_type, base_uri: {
        "ok": True,
        "checked_uri": base_uri,
    }
    service._resolve_scope_sources = lambda source_scope, selected_source_ids, knowledge_base_id: [
        source
    ]
    service._resolve_documents_for_source = lambda selected_source, source_documents: documents
    service._build_source_snapshot = lambda selected_sources, run, include_processing=True: {
        "sources": [str(item.source_id) for item in selected_sources],
        "document_count": len(documents),
    }
    service._build_active_diff_summary = lambda candidate: {
        "added_document_count": len(candidate.version_documents)
    }
    service._mark_source_failure = lambda run, source, document, error_code, message, stage="": {
        "source_id": str(getattr(source, "source_id", "")),
        "document_id": str(getattr(document, "document_id", "")) if document is not None else None,
        "stage": stage,
        "error_code": error_code,
        "error_message": message,
    }
    service._validate_candidate_version = lambda *args, **kwargs: ValidationSummary(
        run_status=KnowledgeUpdateStatus.COMPLETED,
        version_status=KnowledgeVersionStatus.VALIDATED,
        details={
            "validation": "passed",
            "missing_required_packages": [],
            "required_source_failures": [],
        },
    )

    def _auto_activate(candidate: KnowledgeVersion, run: KnowledgeUpdateRun) -> KnowledgeVersion:
        candidate.status = KnowledgeVersionStatus.ACTIVE
        candidate.activated_at = datetime.now(UTC)
        candidate.activation_metadata = {"mode": "automatic", "run_id": str(run.update_run_id)}
        return candidate

    service._auto_activate_candidate_version = _auto_activate
    return service, session, snapshot_repo, chunk_repo, delta_repo


def test_e2e_primary_load_by_link_builds_active_version_and_document_memory(monkeypatch) -> None:
    source = KnowledgeSource(
        source_id="src-url-1",
        knowledge_base_id="kb-user",
        source_type=SourceType.URL_LIST,
        name="Architecture Portal",
        base_uri="https://example.com/index.html",
        criticality=Criticality.REQUIRED,
        status=SourceStatus.ACTIVE,
    )
    document = SourceDocument(
        document_id="doc-url-1",
        source_id=source.source_id,
        document_type=DocumentType.NORMATIVE,
        title="Integration Standard",
        uri="https://example.com/integration-standard.md",
        is_latest=True,
        status=SourceDocumentStatus.REGISTERED,
    )
    document.source = source
    service, _session, snapshot_repo, chunk_repo, delta_repo = _make_update_service(
        source=source, documents=[document]
    )
    run = KnowledgeUpdateRun(
        update_run_id="run-url-1",
        knowledge_base_id="kb-user",
        run_type=UpdateRunType.MANUAL,
        status=KnowledgeUpdateStatus.QUEUED,
        current_stage="queued",
        scope={
            "source_scope": SourceScope.ALL.value,
            "selected_source_ids": [str(source.source_id)],
            "requested_by": "architect",
        },
        summary={"stage_history": []},
        started_at=datetime.now(UTC),
    )
    candidate = KnowledgeVersion(
        knowledge_version_id="kv-url-1",
        knowledge_base_id="kb-user",
        update_run_id=run.update_run_id,
        version_no="KB-USER-V1",
        status=KnowledgeVersionStatus.DRAFT,
        knowledge_base=KnowledgeBase(
            code="kb-user",
            name="User Knowledge Base",
            kind=KnowledgeBaseKind.USER_MANAGED,
            status=KnowledgeBaseStatus.ACTIVE,
        ),
    )
    service.get_run = lambda update_run_id: run
    service._get_or_create_candidate_version = lambda _current_run: candidate

    import app.domain.services.knowledge_core as knowledge_core_module

    monkeypatch.setattr(
        knowledge_core_module,
        "fetch_uri",
        lambda uri, timeout_sec, max_size_bytes: (
            (
                b"# Integration Standard\n"
                b"API Gateway must validate JWT tokens.\n"
                b"CRM System -> Billing System over REST API.\n"
                b"Risk: dependency on external IAM provider."
            ),
            uri,
            "text/markdown",
        ),
    )
    monkeypatch.setattr(
        knowledge_core_module,
        "normalize_document_payload",
        lambda uri, blob: SimpleNamespace(
            text=blob.decode("utf-8"),
            content_format="markdown",
            parser_name="markdown-parser",
            sections=[{"title": "Integration Standard"}],
            metadata={"uri": uri},
        ),
    )
    monkeypatch.setattr(
        knowledge_core_module,
        "resolve_basis_assignment",
        lambda document: ("reference_only", False),
    )

    completed_run = service.execute_run(str(run.update_run_id))

    assert completed_run.status == KnowledgeUpdateStatus.COMPLETED
    assert completed_run.summary["activated_knowledge_version_id"] == str(
        candidate.knowledge_version_id
    )
    assert completed_run.summary["quality_summary"]["processed_documents"] == 1
    assert completed_run.summary["quality_summary"]["delta_summary"] == {
        "new": 1,
        "changed": 0,
        "deleted": 0,
        "unchanged": 0,
    }
    assert candidate.status == KnowledgeVersionStatus.ACTIVE
    assert len(snapshot_repo.items) == 1
    assert len(chunk_repo.items) >= 1
    assert len(candidate.extracted_items) >= 2
    item_types = {item.item_type.value for item in candidate.extracted_items}
    assert "summary" in item_types
    assert "normative_rule" in item_types or "constraint" in item_types
    assert delta_repo.summarize_for_run(str(run.update_run_id))["new"] == 1

    memory_service = KnowledgeSourceService.__new__(KnowledgeSourceService)
    memory_service.get_document = lambda document_id: document
    memory_service.extracted_items = FakeExtractedItemsRepo(list(candidate.extracted_items))
    memory_payload = KnowledgeSourceService.get_document_memory_payload(
        memory_service,
        str(document.document_id),
        knowledge_version_id=str(candidate.knowledge_version_id),
    )
    assert memory_payload["summary"]
    assert memory_payload["counters"]["summary"] == 1
    assert memory_payload["items"]


def test_execute_run_preserves_active_documents_outside_selected_scope(monkeypatch) -> None:
    import app.domain.services.knowledge_core as knowledge_core_module

    selected_source = KnowledgeSource(
        source_id="src-selected",
        knowledge_base_id="kb-user",
        source_type=SourceType.REPOSITORY,
        name="Selected Source",
        base_uri="file:///selected",
        criticality=Criticality.REQUIRED,
        status=SourceStatus.ACTIVE,
    )
    untouched_source = KnowledgeSource(
        source_id="src-untouched",
        knowledge_base_id="kb-user",
        source_type=SourceType.REPOSITORY,
        name="Untouched Source",
        base_uri="file:///untouched",
        criticality=Criticality.OPTIONAL,
        status=SourceStatus.ACTIVE,
    )
    selected_document = SourceDocument(
        document_id="doc-selected",
        source_id=selected_source.source_id,
        document_type=DocumentType.NORMATIVE,
        title="Selected Standard",
        uri="file:///selected-standard.md",
        is_latest=True,
        status=SourceDocumentStatus.REGISTERED,
    )
    selected_document.source = selected_source
    untouched_document = SourceDocument(
        document_id="doc-untouched",
        source_id=untouched_source.source_id,
        document_type=DocumentType.OTHER,
        title="Untouched Reference",
        uri="file:///untouched-reference.md",
        is_latest=True,
        status=SourceDocumentStatus.FETCHED,
    )
    untouched_document.source = untouched_source
    active_version = KnowledgeVersion(
        knowledge_version_id="kv-active",
        knowledge_base_id="kb-user",
        update_run_id="run-active",
        version_no="KB-USER-ACTIVE",
        status=KnowledgeVersionStatus.ACTIVE,
        embedding_space_id="space-1",
    )
    selected_binding = KnowledgeVersionDocument(
        knowledge_version_id=active_version.knowledge_version_id,
        document_id=selected_document.document_id,
        role_code="reference_only",
        required_flag=False,
    )
    selected_binding.document = selected_document
    untouched_binding = KnowledgeVersionDocument(
        knowledge_version_id=active_version.knowledge_version_id,
        document_id=untouched_document.document_id,
        role_code="technology_standard",
        required_flag=True,
    )
    untouched_binding.document = untouched_document
    active_version.version_documents = [selected_binding, untouched_binding]

    service, _session, snapshot_repo, _chunk_repo, delta_repo = _make_update_service(
        source=selected_source,
        documents=[selected_document],
        active_version=active_version,
    )
    service._embedding_service_for_profile = lambda profile: service.embeddings
    service.resolve_embedding_space = lambda **kwargs: SimpleNamespace(
        embedding_space_id="space-1", code="statistical_default"
    )
    run = KnowledgeUpdateRun(
        update_run_id="run-selected-scope",
        knowledge_base_id="kb-user",
        run_type=UpdateRunType.MANUAL,
        status=KnowledgeUpdateStatus.QUEUED,
        current_stage="queued",
        scope={
            "source_scope": SourceScope.SELECTED.value,
            "selected_source_ids": [str(selected_source.source_id)],
            "requested_by": "architect",
        },
        summary={"stage_history": []},
        started_at=datetime.now(UTC),
    )
    candidate = KnowledgeVersion(
        knowledge_version_id="kv-candidate",
        knowledge_base_id="kb-user",
        update_run_id=run.update_run_id,
        version_no="KB-USER-CANDIDATE",
        status=KnowledgeVersionStatus.DRAFT,
        knowledge_base=KnowledgeBase(
            code="kb-user",
            name="User Knowledge Base",
            kind=KnowledgeBaseKind.USER_MANAGED,
            status=KnowledgeBaseStatus.ACTIVE,
        ),
    )
    service.get_run = lambda update_run_id: run
    service._get_or_create_candidate_version = lambda _current_run: candidate

    selected_blob = b"# Selected Standard\nPreserved content.\n"
    snapshot_repo.items.extend(
        [
            DocumentSnapshot(
                document_snapshot_id="snap-selected-active",
                knowledge_version_id=active_version.knowledge_version_id,
                document_id=selected_document.document_id,
                checksum=checksum_sha256(selected_blob),
                content_format="markdown",
                parser_name="markdown",
                normalized_text=selected_blob.decode("utf-8"),
                structure_metadata={},
            ),
            DocumentSnapshot(
                document_snapshot_id="snap-untouched-active",
                knowledge_version_id=active_version.knowledge_version_id,
                document_id=untouched_document.document_id,
                checksum="chk-untouched",
                content_format="markdown",
                parser_name="markdown",
                normalized_text="Legacy reference content",
                structure_metadata={},
            ),
        ]
    )

    monkeypatch.setattr(
        knowledge_core_module,
        "fetch_uri",
        lambda uri, timeout_sec, max_size_bytes: (selected_blob, uri, "text/markdown"),
    )
    monkeypatch.setattr(
        knowledge_core_module,
        "normalize_document_payload",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("selected document should be reused from active snapshot")
        ),
    )

    completed_run = service.execute_run(str(run.update_run_id))

    assert completed_run.status == KnowledgeUpdateStatus.COMPLETED
    assert {str(item.document_id) for item in candidate.version_documents} == {
        str(selected_document.document_id),
        str(untouched_document.document_id),
    }
    preserved_binding = next(
        item
        for item in candidate.version_documents
        if str(item.document_id) == str(untouched_document.document_id)
    )
    assert preserved_binding.role_code == "technology_standard"
    assert preserved_binding.required_flag is True
    assert delta_repo.summarize_for_run(str(run.update_run_id)) == {
        "new": 0,
        "changed": 0,
        "deleted": 0,
        "unchanged": 1,
    }


def test_e2e_monthly_update_of_unselected_base_does_not_change_generation_selection() -> None:
    selected_user_version = KnowledgeVersion(
        knowledge_version_id="kv-primary-v2",
        knowledge_base_id="kb-primary",
        update_run_id="run-selected",
        version_no="KB-PRIMARY-V2",
        status=KnowledgeVersionStatus.ACTIVE,
    )
    mandatory_version = KnowledgeVersion(
        knowledge_version_id="kv-mandatory-v3",
        knowledge_base_id="kb-mandatory",
        update_run_id="run-mandatory",
        version_no="MANDATORY-V3",
        status=KnowledgeVersionStatus.ACTIVE,
    )

    update_service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    now = datetime.now(UTC)
    selected_base = SimpleNamespace(
        knowledge_base_id="kb-primary", status=KnowledgeBaseStatus.ACTIVE
    )
    unselected_due_base = SimpleNamespace(
        knowledge_base_id="kb-secondary", status=KnowledgeBaseStatus.ACTIVE
    )
    update_service.settings = SimpleNamespace(knowledge_auto_sync_interval_days=30)
    update_service.sources = SimpleNamespace(list_active=lambda knowledge_base_id=None: [object()])
    update_service.update_runs = SimpleNamespace(
        get_latest_finished=lambda knowledge_base_id=None: (
            SimpleNamespace(finished_at=now - timedelta(days=60))
            if knowledge_base_id == "kb-secondary"
            else SimpleNamespace(finished_at=now - timedelta(days=2))
        )
    )
    update_service._create_run = lambda **kwargs: SimpleNamespace(
        update_run_id=f"run-{kwargs['payload'].knowledge_base_id}",
        knowledge_base_id=kwargs["payload"].knowledge_base_id,
    )
    update_service.session = None

    import app.domain.services.knowledge_core as knowledge_core_module

    original_base_service = knowledge_core_module.KnowledgeBaseService
    knowledge_core_module.KnowledgeBaseService = lambda session: SimpleNamespace(
        bases=SimpleNamespace(list_visible=lambda: [selected_base, unselected_due_base])
    )
    try:
        scheduled_payload = KnowledgeUpdateService.run_due_scheduled_syncs(
            update_service, now=now, execute_inline=False
        )
    finally:
        knowledge_core_module.KnowledgeBaseService = original_base_service

    assert scheduled_payload["started_knowledge_base_ids"] == ["kb-secondary"]
    assert "kb-primary" in scheduled_payload["skipped_knowledge_base_ids"]

    generation_service = _make_generation_service(
        selected_user_version=selected_user_version,
        mandatory_version=mandatory_version,
    )
    try:
        run = generation_service.start_run(
            InternalGenerationRunStartRequest(
                business_task_id="task-1", correlation_id="corr-13-3"
            ),
            _principal(),
        )
    finally:
        _restore_generation_service(generation_service)

    assert isinstance(run, GenerationRun)
    assert run.status == GenerationRunStatus.QUEUED
    assert str(run.knowledge_version_id) == str(selected_user_version.knowledge_version_id)
    snapshot = run.input_snapshot["knowledge_snapshot"]
    assert snapshot["selected_generation_version_id"] == str(
        selected_user_version.knowledge_version_id
    )
    assert snapshot["effective_version_ids"] == [
        str(selected_user_version.knowledge_version_id),
    ]


def test_e2e_manual_rollback_version_changes_generation_scope() -> None:
    now = datetime.now(UTC)
    current_active = KnowledgeVersion(
        knowledge_version_id="kv-user-v3",
        knowledge_base_id="kb-user",
        update_run_id="run-current",
        version_no="KB-USER-V3",
        status=KnowledgeVersionStatus.ACTIVE,
        activated_at=now,
    )
    rolled_back = KnowledgeVersion(
        knowledge_version_id="kv-user-v1",
        knowledge_base_id="kb-user",
        update_run_id="run-old",
        version_no="KB-USER-V1",
        status=KnowledgeVersionStatus.ARCHIVED,
        archived_at=now - timedelta(days=10),
        summary={"validation": "passed"},
        source_snapshot={},
    )

    version_service = KnowledgeVersionService.__new__(KnowledgeVersionService)
    version_service.session = Mock()
    version_service.versions = SimpleNamespace(
        get_for_update=lambda knowledge_version_id: rolled_back,
        get_active_for_update=lambda **kwargs: current_active,
    )
    version_service.operations = Mock()
    version_service.audit = Mock()

    activated = version_service.activate(
        str(rolled_back.knowledge_version_id), _principal(), reason="rollback", auto_commit=False
    )
    assert activated is rolled_back
    assert rolled_back.status == KnowledgeVersionStatus.ACTIVE
    assert current_active.status == KnowledgeVersionStatus.VALIDATED

    mandatory_version = KnowledgeVersion(
        knowledge_version_id="kv-mandatory-v3",
        knowledge_base_id="kb-mandatory",
        update_run_id="run-mandatory",
        version_no="MANDATORY-V2",
        status=KnowledgeVersionStatus.ACTIVE,
    )
    generation_service = _make_generation_service(
        selected_user_version=rolled_back,
        mandatory_version=mandatory_version,
    )
    try:
        run = generation_service.start_run(
            InternalGenerationRunStartRequest(
                business_task_id="task-1", correlation_id="corr-13-4"
            ),
            _principal(),
        )
    finally:
        _restore_generation_service(generation_service)

    assert str(run.knowledge_version_id) == str(rolled_back.knowledge_version_id)
    assert run.input_snapshot["knowledge_snapshot"]["selected_generation_version_id"] == str(
        rolled_back.knowledge_version_id
    )


def test_e2e_remove_and_upload_documents_create_new_versions_and_update_visible_composition() -> (
    None
):
    principal = _principal()
    source = SimpleNamespace(
        source_id="src-1", knowledge_base_id="kb-user", status=SourceStatus.ACTIVE
    )
    old_document = SimpleNamespace(
        document_id="doc-old",
        source_id="src-1",
        title="Legacy Policy",
        uri="file:///legacy-policy.md",
        document_type=DocumentType.NORMATIVE,
        version_label="v1",
        checksum="chk-old",
        status=SourceDocumentStatus.FETCHED,
        is_latest=True,
        registered_at=datetime.now(UTC),
        discovered_at=datetime.now(UTC),
        source=SimpleNamespace(name="Repository", source_type=SourceType.REPOSITORY),
    )

    remove_service = KnowledgeSourceService.__new__(KnowledgeSourceService)
    remove_service.session = Mock()
    remove_service.audit = Mock()
    remove_service._assert_document_mutable = lambda *args, **kwargs: None
    remove_service.get_document = lambda document_id: old_document
    remove_service.get_source = lambda source_id: source

    import app.domain.services.knowledge_core as knowledge_core_module

    class FakeUpdateService:
        def __init__(self, session, settings):
            self.session = session
            self.settings = settings

        def start_run(self, payload, principal):
            return {
                "update_run_id": f"run-{payload.run_type.value}",
                "run_type": payload.run_type.value,
            }

        def start_manual_run(self, **kwargs):
            return SimpleNamespace(
                update_run_id=f"run-{kwargs['run_type'].value}", run_type=kwargs["run_type"]
            )

        def get_run_response(self, update_run_id: str):
            return {"update_run_id": update_run_id, "run_type": update_run_id.replace("run-", "")}

    original_update_service = knowledge_core_module.KnowledgeUpdateService
    knowledge_core_module.KnowledgeUpdateService = FakeUpdateService
    try:
        removed_document, delete_run = KnowledgeSourceService.remove_document_and_start_update(
            remove_service,
            "doc-old",
            principal,
            settings=SimpleNamespace(),
            execute_inline=True,
            reason="remove_legacy_doc",
        )
        upload_run = FakeUpdateService(None, None).start_manual_run(
            knowledge_base_id="kb-user",
            source_scope=SourceScope.SELECTED,
            selected_source_ids=["src-upload"],
            correlation_id="upload-corr",
            reason="upload_new_doc",
            requested_by=principal.login,
            execute_inline=True,
            run_type=UpdateRunType.UPLOAD,
        )
    finally:
        knowledge_core_module.KnowledgeUpdateService = original_update_service

    assert removed_document.status == SourceDocumentStatus.ARCHIVED
    assert delete_run["run_type"] == "delete"
    assert upload_run.run_type == UpdateRunType.UPLOAD

    upload_document = SimpleNamespace(
        document_id="doc-new",
        source_id="src-upload",
        title="New Integration Standard",
        uri="file:///new-standard.md",
        document_type=DocumentType.OTHER,
        version_label=None,
        checksum="chk-new",
        status=SourceDocumentStatus.FETCHED,
        registered_at=datetime.now(UTC),
        discovered_at=datetime.now(UTC),
        source=SimpleNamespace(name="Загруженные файлы", source_type=SourceType.REPOSITORY),
    )
    delete_version = SimpleNamespace(
        knowledge_version_id="kv-delete",
        knowledge_base_id="kb-user",
        update_run_id="run-delete",
        version_documents=[],
    )
    upload_version = SimpleNamespace(
        knowledge_version_id="kv-upload",
        knowledge_base_id="kb-user",
        update_run_id="run-upload",
        version_documents=[
            SimpleNamespace(
                document=upload_document, role_code="reference_only", required_flag=False
            ),
        ],
    )
    delete_delta = DocumentDelta(
        update_run_id="run-delete",
        knowledge_base_id="kb-user",
        knowledge_version_id="kv-delete",
        source_id="src-1",
        document_id="doc-old",
        delta_kind=DocumentDeltaKind.DELETED,
        uri="file:///legacy-policy.md",
        checksum_before="chk-old",
        checksum_after=None,
        details={"title": "Legacy Policy"},
    )
    knowledge_item = SimpleNamespace(
        extracted_item_id="item-1",
        knowledge_version_id="kv-upload",
        document_id="doc-new",
        document_chunk_id=None,
        item_type=SimpleNamespace(value="summary"),
        title="Summary",
        content="Документ описывает новый интеграционный стандарт.",
        normalized_value=None,
        source_location="document:summary",
        confidence_score=0.9,
        quality_status=SimpleNamespace(value="inferred"),
        evidence_quote="API Gateway must expose REST APIs.",
        structured_payload={},
        created_at=datetime.now(UTC),
    )

    list_service = KnowledgeSourceService.__new__(KnowledgeSourceService)
    list_service.session = None
    list_service.versions = SimpleNamespace(
        get_with_documents=lambda knowledge_version_id: delete_version
        if knowledge_version_id == "kv-delete"
        else upload_version,
        get_active=lambda **kwargs: upload_version,
    )
    list_service.document_deltas = InMemoryDocumentDeltaRepo()
    list_service.document_deltas.add(delete_delta)
    list_service.documents = SimpleNamespace(
        get=lambda document_id: old_document if document_id == "doc-old" else upload_document,
    )
    list_service.sources = SimpleNamespace(
        get=lambda source_id: old_document.source
        if source_id == "src-1"
        else upload_document.source
    )
    list_service.extracted_items = FakeExtractedItemsRepo([knowledge_item])
    list_service.get_document = (
        lambda document_id: upload_document if document_id == "doc-new" else old_document
    )

    original_base_service = knowledge_core_module.KnowledgeBaseService
    knowledge_core_module.KnowledgeBaseService = lambda session: SimpleNamespace(
        get_base=lambda knowledge_base_id: SimpleNamespace(knowledge_base_id="kb-user")
    )
    try:
        delete_rows = KnowledgeSourceService.list_base_document_payloads(
            list_service,
            "kb-user",
            knowledge_version_id="kv-delete",
            include_deleted=True,
        )
        upload_rows = KnowledgeSourceService.list_base_document_payloads(
            list_service,
            "kb-user",
            knowledge_version_id="kv-upload",
            include_deleted=True,
        )
    finally:
        knowledge_core_module.KnowledgeBaseService = original_base_service

    deleted_row = delete_rows[0]
    assert deleted_row["present_in_version"] is False
    assert deleted_row["title"] == "Legacy Policy"

    present_row = upload_rows[0]
    assert present_row["present_in_version"] is True
    assert present_row["title"] == "New Integration Standard"

    memory_payload = KnowledgeSourceService.get_document_memory_payload(
        list_service,
        "doc-new",
        knowledge_version_id="kv-upload",
    )
    assert memory_payload["summary"] == "Документ описывает новый интеграционный стандарт."
    assert memory_payload["counters"]["summary"] == 1
