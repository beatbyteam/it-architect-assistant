from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.bootstrap.bundles import _manifest_root, import_knowledge_bundle
from app.core.exceptions import ConflictError
from app.core.security import AuthPrincipal
from app.db.enums import (
    AccountType,
    Criticality,
    KnowledgeBaseKind,
    KnowledgeBaseStatus,
    KnowledgeVersionStatus,
    SourceStatus,
    SourceType,
)
from app.db.models.knowledge import EmbeddingSpace, KnowledgeBase, KnowledgeSource, KnowledgeVersion
from app.domain.services import mvp_canonical
from app.domain.services.knowledge.source_service import KnowledgeSourceService
from app.domain.services.knowledge.update_service import KnowledgeUpdateService
from app.domain.services.knowledge_bases import KnowledgeBaseService
from app.domain.services.operations import OperationsQueryService
from app.integrations.knowledge.local_paths import normalize_local_path_reference
from app.integrations.knowledge.source_readers import RepositoryReader, UrlListReader
from app.integrations.knowledge.source_security import validate_document_uri
from app.schemas.knowledge import SourceCreateRequest


def _principal(user_id: str = "user-1") -> AuthPrincipal:
    return AuthPrincipal(
        user_id=user_id,
        login=user_id,
        display_name=user_id,
        account_type=AccountType.HUMAN,
        role_codes=["USER"],
        is_authenticated=True,
    )


def test_source_lifecycle_mutation_rejected_while_base_update_running() -> None:
    service = KnowledgeSourceService.__new__(KnowledgeSourceService)
    source = SimpleNamespace(
        source_id="src-1",
        knowledge_base_id="kb-1",
        status=SourceStatus.ACTIVE,
    )
    service._get_source_compat = lambda source_id, principal=None: source
    service._get_base = lambda knowledge_base_id, principal=None: SimpleNamespace(
        knowledge_base_id=knowledge_base_id,
        kind=KnowledgeBaseKind.USER_MANAGED,
    )
    service.update_runs = SimpleNamespace(
        get_running=lambda knowledge_base_id=None: SimpleNamespace(update_run_id="run-1")
    )

    try:
        service.archive_source("src-1", _principal())
    except ConflictError as exc:
        assert exc.error_code == "KNOWLEDGE_UPDATE_ALREADY_RUNNING"
    else:
        raise AssertionError("Expected source archive to be rejected during knowledge update")


def test_import_bundle_checks_target_base_access(monkeypatch) -> None:
    principal = _principal("owner-1")
    calls: list[tuple[str, object | None]] = []

    class _BaseService:
        def __init__(self, session) -> None:
            self.session = session

        def get_base(self, knowledge_base_id: str, principal=None):
            calls.append((knowledge_base_id, principal))
            return SimpleNamespace(knowledge_base_id=knowledge_base_id)

        def ensure_system_bases(self):
            return None

    monkeypatch.setattr(
        "app.bootstrap.bundles.load_bundle_manifest",
        lambda manifest_uri: (
            {
                "bundle_code": "demo",
                "sources": [
                    {
                        "name": "Source",
                        "source_type": "repository",
                        "criticality": "required",
                        "base_uri": "file:///tmp",
                    }
                ],
            },
            "/tmp",
        ),
    )
    monkeypatch.setattr(
        "app.bootstrap.bundles._validate_manifest_payload", lambda *args, **kwargs: None
    )
    monkeypatch.setattr("app.bootstrap.bundles.KnowledgeBaseService", _BaseService)
    monkeypatch.setattr(
        "app.bootstrap.bundles.KnowledgeSourceService", lambda session: SimpleNamespace()
    )
    monkeypatch.setattr(
        "app.bootstrap.bundles.KnowledgeVersionService", lambda session: SimpleNamespace()
    )
    monkeypatch.setattr(
        "app.bootstrap.bundles._resolve_requested_by",
        lambda principal, requested_by: requested_by or principal.user_id,
    )
    monkeypatch.setattr(
        "app.bootstrap.bundles._upsert_source",
        lambda *args, **kwargs: SimpleNamespace(source_id="src-1", name="Source"),
    )
    monkeypatch.setattr(
        "app.bootstrap.bundles._ensure_update_not_running", lambda *args, **kwargs: None
    )

    result = import_knowledge_bundle(
        SimpleNamespace(),
        manifest_uri="file:///tmp/bundle.json",
        knowledge_base_id="kb-1",
        principal=principal,
        start_update=False,
    )

    assert result.imported_source_ids == ["src-1"]
    assert calls == [("kb-1", principal)]


def test_windows_file_uri_normalization_strips_fake_leading_slash() -> None:
    normalized = normalize_local_path_reference("file:///C:/workspace/bundles/demo.json")

    assert normalized == "C:/workspace/bundles/demo.json"
    assert not normalized.startswith("/C:/")


def test_manifest_root_uses_normalized_windows_file_uri() -> None:
    manifest_root = _manifest_root("file:///C:/workspace/bundles/demo.json")

    assert str(manifest_root).endswith("C:/workspace/bundles")


def test_file_uri_document_validation_and_local_discovery_keep_working(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    doc = docs_dir / "baseline.md"
    doc.write_text("# Baseline", encoding="utf-8")
    index = tmp_path / "index.html"
    index.write_text('<a href="docs/baseline.md">Baseline</a>', encoding="utf-8")

    validate_document_uri(doc.as_uri(), allowed_local_roots=[str(tmp_path)])

    repo_source = KnowledgeSource(
        source_type=SourceType.REPOSITORY,
        name="repo",
        base_uri=docs_dir.as_uri(),
        criticality=Criticality.REQUIRED,
        status=SourceStatus.ACTIVE,
    )
    repo_docs = RepositoryReader().resolve_documents(repo_source, [])
    assert [item.title for item in repo_docs] == ["baseline.md"]

    seed_source = KnowledgeSource(
        source_type=SourceType.URL_LIST,
        name="seed",
        base_uri=index.as_uri(),
        criticality=Criticality.REQUIRED,
        status=SourceStatus.ACTIVE,
    )
    seed_docs = UrlListReader().resolve_documents(seed_source, [])
    assert [item.title for item in seed_docs] == ["Baseline"]


def test_run_due_scheduled_syncs_filters_visible_bases_by_principal() -> None:
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    captured: list[object | None] = []
    principal = _principal("tenant-a")
    service._list_visible_bases = lambda incoming=None: captured.append(incoming) or []

    payload = KnowledgeUpdateService.run_due_scheduled_syncs(
        service, execute_inline=False, principal=principal
    )

    assert payload["started_runs"] == []
    assert captured == [principal]


def test_mandatory_baseline_payload_is_not_selected_by_default() -> None:
    principal = _principal("svc.worker")
    mandatory_base = KnowledgeBase(
        knowledge_base_id="kb-mab",
        code="mandatory_architecture_baseline",
        name="Mandatory Architecture Baseline",
        kind=KnowledgeBaseKind.SYSTEM_MANDATORY,
        status=KnowledgeBaseStatus.ACTIVE,
        owner_user_id=None,
    )
    default_base = KnowledgeBase(
        knowledge_base_id="kb-default",
        code="default_user_knowledge_base__svc.worker",
        name="Default",
        kind=KnowledgeBaseKind.USER_MANAGED,
        status=KnowledgeBaseStatus.ACTIVE,
        owner_user_id="svc.worker",
    )
    mandatory_version = KnowledgeVersion(
        knowledge_version_id="kv-mab",
        knowledge_base_id="kb-mab",
        version_no="MAB-1",
        update_run_id="run-mab",
        status=KnowledgeVersionStatus.ACTIVE,
    )

    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.session = SimpleNamespace()
    service._assert_base_access = lambda _base_obj, principal=None: None
    service._base_stats = lambda _base_obj: {}
    service.bases = SimpleNamespace(
        list_visible=lambda owner_user_id=None: [mandatory_base, default_base],
        get=lambda knowledge_base_id: mandatory_base
        if knowledge_base_id == "kb-mab"
        else default_base
        if knowledge_base_id == "kb-default"
        else None,
        get_by_code=lambda code, owner_user_id=None: mandatory_base
        if code == "mandatory_architecture_baseline"
        else default_base
        if code == "default_user_knowledge_base__svc.worker"
        else None,
    )
    service.selections = SimpleNamespace(get_for_scope=lambda scope: None)
    service.versions = SimpleNamespace(
        get=lambda knowledge_version_id: mandatory_version
        if knowledge_version_id == "kv-mab"
        else None,
        get_with_documents=lambda knowledge_version_id: mandatory_version
        if knowledge_version_id == "kv-mab"
        else None,
        get_active=lambda knowledge_base_id, eager=False: mandatory_version
        if knowledge_base_id == "kb-mab"
        else None,
        list_visible=lambda knowledge_base_id: [mandatory_version]
        if knowledge_base_id == "kb-mab"
        else [],
    )
    service.sources = SimpleNamespace(list_for_base=lambda knowledge_base_id: [])
    service.documents = SimpleNamespace(
        list_for_source=lambda source_id, include_archived=False: []
    )
    service.update_runs = SimpleNamespace(
        get_latest_finished=lambda knowledge_base_id: None,
        list_recent=lambda limit, knowledge_base_id: [],
    )

    items = service.list_payloads(principal)
    payload = service.get_base_payload("kb-mab", principal)
    scope = service.get_existing_effective_scope(principal)

    mandatory_payload = next(item for item in items if item["knowledge_base_id"] == "kb-mab")
    default_payload = next(item for item in items if item["knowledge_base_id"] == "kb-default")
    assert scope is not None
    assert scope.mandatory_version is None
    assert scope.selected_generation_version() is None
    assert mandatory_payload["selected_for_generation"] is False
    assert mandatory_payload["selected_knowledge_version_id"] is None
    assert default_payload["selected_for_generation"] is True
    assert default_payload["selected_knowledge_version_id"] is None
    assert payload["selected_for_generation"] is False
    assert payload["selected_knowledge_version_id"] is None


def test_selecting_mandatory_baseline_uses_only_mandatory_generation_scope() -> None:
    principal = _principal("svc.worker")
    mandatory_base = KnowledgeBase(
        knowledge_base_id="kb-mab",
        code="mandatory_architecture_baseline",
        name="Mandatory Architecture Baseline",
        kind=KnowledgeBaseKind.SYSTEM_MANDATORY,
        status=KnowledgeBaseStatus.ACTIVE,
        owner_user_id=None,
    )
    default_base = KnowledgeBase(
        knowledge_base_id="kb-default",
        code="default_user_knowledge_base__svc.worker",
        name="Default",
        kind=KnowledgeBaseKind.USER_MANAGED,
        status=KnowledgeBaseStatus.ACTIVE,
        owner_user_id="svc.worker",
    )
    mandatory_version = KnowledgeVersion(
        knowledge_version_id="kv-mab",
        knowledge_base_id="kb-mab",
        version_no="MAB-1",
        update_run_id="run-mab",
        status=KnowledgeVersionStatus.ACTIVE,
    )
    default_version = KnowledgeVersion(
        knowledge_version_id="kv-default",
        knowledge_base_id="kb-default",
        version_no="USER-1",
        update_run_id="run-default",
        status=KnowledgeVersionStatus.ACTIVE,
    )
    selection = SimpleNamespace(
        selected_knowledge_base=mandatory_base,
        selected_knowledge_version_id=None,
    )

    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.bases = SimpleNamespace(
        get_by_code=lambda code, owner_user_id=None: mandatory_base
        if code == "mandatory_architecture_baseline"
        else default_base
        if code == "default_user_knowledge_base__svc.worker"
        else None,
    )
    service.selections = SimpleNamespace(get_for_scope=lambda scope: selection)
    service.versions = SimpleNamespace(
        get_active=lambda knowledge_base_id, eager=False: mandatory_version
        if knowledge_base_id == "kb-mab"
        else default_version
        if knowledge_base_id == "kb-default"
        else None,
        get_with_documents=lambda knowledge_version_id: default_version
        if knowledge_version_id == "kv-default"
        else None,
    )

    scope = service.get_existing_effective_scope(principal)

    assert scope is not None
    assert scope.selected_user_base is mandatory_base
    assert scope.mandatory_version is mandatory_version
    assert scope.selected_user_version is None
    assert scope.selected_generation_version() is mandatory_version


def test_create_source_activates_when_preflight_succeeds() -> None:
    principal = _principal("owner-1")
    base_id = str(uuid4())
    created: list[KnowledgeSource] = []
    audit = Mock()
    service = KnowledgeSourceService.__new__(KnowledgeSourceService)
    service.settings = SimpleNamespace()
    service._validate_source = lambda source_type, base_uri: None
    service._get_base = lambda knowledge_base_id, principal=None: SimpleNamespace(
        knowledge_base_id=base_id
    )
    service._assert_base_mutable = lambda base, principal, operation: None
    service._probe_source_availability = lambda source_type, base_uri: {"ok": True}
    service.sources = SimpleNamespace(add=lambda source: created.append(source))
    service.session = SimpleNamespace(
        flush=lambda: None,
        commit=lambda: None,
        refresh=lambda source: None,
    )
    service.audit = audit

    source = service.create_source(
        SourceCreateRequest(
            knowledge_base_id=base_id,
            source_type=SourceType.URL,
            name="Docs",
            base_uri="https://example.com/docs",
            criticality=Criticality.OPTIONAL,
        ),
        principal,
    )

    assert source.status == SourceStatus.ACTIVE
    assert created == [source]
    assert "active state" in audit.record.call_args.kwargs["message"]


def test_resolve_embedding_space_recovers_existing_space_after_duplicate_code() -> None:
    existing = EmbeddingSpace(
        embedding_space_id=str(uuid4()),
        code="bge_m3_default",
        provider_name="ollama",
        model_id="bge-m3",
        dimensions=1024,
        distance_metric="cosine",
        is_active=False,
    )

    class _Nested:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, exc, _tb):
            return False

    class _Session:
        def __init__(self) -> None:
            self.flush_count = 0

        def begin_nested(self):
            return _Nested()

        def flush(self):
            self.flush_count += 1
            raise IntegrityError("insert", {}, Exception("duplicate code"))

    class _Spaces:
        def __init__(self) -> None:
            self.calls = 0

        def get_by_code(self, code: str):
            self.calls += 1
            return None if self.calls == 1 else existing

        def get_active(self):
            return None

        def add(self, space):
            return space

    embedding_service = SimpleNamespace(
        provider_name="ollama",
        profile=SimpleNamespace(model_id="bge-m3", dimensions=1024),
        describe=lambda: {
            "profile_code": "bge_m3_default",
            "provider_name": "ollama",
            "model_id": "bge-m3",
            "dimensions": 1024,
            "normalize_l2": True,
        },
    )
    service = KnowledgeUpdateService.__new__(KnowledgeUpdateService)
    service.session = _Session()
    service.embedding_spaces = _Spaces()

    resolved = service.resolve_embedding_space(
        activate=False,
        embedding_service=embedding_service,
    )

    assert resolved is existing


def test_system_knowledge_update_run_is_visible_when_base_is_accessible(monkeypatch) -> None:
    class _BaseService:
        def __init__(self, session) -> None:
            self.session = session

        def get_base(self, knowledge_base_id: str, principal=None):
            return SimpleNamespace(knowledge_base_id=knowledge_base_id, owner_user_id=None)

    monkeypatch.setattr("app.domain.services.operations.KnowledgeBaseService", _BaseService)
    service = OperationsQueryService.__new__(OperationsQueryService)
    service.session = SimpleNamespace()
    run = SimpleNamespace(
        initiator_user_id="system.bootstrap",
        knowledge_base_id="kb-mab",
    )

    assert service._is_visible_knowledge_run(run, _principal("local.user")) is True


def test_canonical_generation_start_forwards_execute_inline(monkeypatch) -> None:
    captured: dict[str, object | None] = {}

    def _start_generation_impl(service, task_id, **kwargs):
        captured.update(kwargs)
        return {"dispatch_type": "generation_run", "task_id": task_id}

    monkeypatch.setattr(mvp_canonical, "start_generation_impl", _start_generation_impl)

    service = mvp_canonical.CanonicalTaskService.__new__(
        mvp_canonical.CanonicalTaskService
    )

    result = service.start_generation(
        "task-1",
        correlation_id=None,
        principal=_principal("local.user"),
        idempotency_key="generation-smoke",
        execute_inline=False,
    )

    assert result["dispatch_type"] == "generation_run"
    assert captured["execute_inline"] is False
