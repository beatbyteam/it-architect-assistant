from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.api.v1.routes import knowledge_documents_routes, knowledge_evaluation_routes
from app.core.exceptions import NotFoundError
from app.core.security import AuthPrincipal
from app.db.enums import (
    AccountType,
    Criticality,
    DocumentType,
    GenerationRunStatus,
    SourceDocumentStatus,
    SourceProcessingStatus,
    SourceStatus,
    SourceType,
)
from app.db.models.audit import AuditEvent
from app.db.models.knowledge import KnowledgeSource, SourceDocument
from app.domain.services.generation.retrieval_service import RetrievalService
from app.domain.services.generation.runtime import _build_run_principal
from app.domain.services.knowledge.source_service import KnowledgeSourceService
from app.domain.services.operations import OperationsQueryService
from app.integrations.generation.contracts import REQUIRED_SECTION_CODES, GenerationSolutionPayload
from app.integrations.generation.payload_normalization_common import _parse_integration_string
from app.integrations.generation.payload_normalization_integrations import _normalize_integrations
from app.integrations.generation.payload_normalization_source_refs import (
    _enrich_critical_section_source_refs,
)
from app.schemas.knowledge import RetrievalEvaluationRequest


def _principal(user_id: str = "user-1") -> AuthPrincipal:
    return AuthPrincipal(
        user_id=user_id,
        login=user_id,
        display_name="Architect",
        account_type=AccountType.HUMAN,
        role_codes=["USER"],
        is_authenticated=True,
    )


def _minimal_generation_payload() -> GenerationSolutionPayload:
    return GenerationSolutionPayload.model_validate(
        {
            "solution_title": "Architecture",
            "executive_summary": "Summary",
            "sections": [
                {
                    "section_code": code,
                    "title": code.replace("_", " ").title(),
                    "body_markdown": f"Body for {code}",
                    "source_refs": [],
                }
                for code in REQUIRED_SECTION_CODES
            ],
            "components": [
                {
                    "component_name": "Billing API",
                    "role_description": "Handles billing orchestration.",
                }
            ],
            "integrations": [],
            "assumptions": [],
            "next_steps": [],
            "risks": [],
        }
    )


def test_parse_integration_string_returns_mapping_and_normalization_keeps_string_integrations() -> (
    None
):
    parsed = _parse_integration_string("Billing API -> Kafka via HTTPS: sends payment events")

    assert parsed == {
        "from_component": "Billing API",
        "to_component": "Kafka",
        "protocol": "HTTPS",
        "interaction": "sends payment events",
    }
    assert _normalize_integrations(["Billing API -> Kafka via HTTPS: sends payment events"]) == [
        parsed
    ]


def test_enrich_critical_section_source_refs_no_longer_raises_name_error() -> None:
    payload = _minimal_generation_payload()
    fragment = SimpleNamespace(
        fragment_id="frag-1",
        document_id="doc-1",
        title="Business context",
        content="Body for general information with useful evidence.",
        lexical_score=0.8,
        vector_score=0.7,
        score=0.9,
    )

    enriched = _enrich_critical_section_source_refs(payload, retrieved_fragments=[fragment])

    first_section = enriched.sections[0]
    assert first_section.source_refs
    assert first_section.source_refs[0].fragment_id == "frag-1"
    assert first_section.source_refs[0].document_id == "doc-1"


def test_list_source_payloads_uses_owner_scope_and_batch_loading() -> None:
    service = KnowledgeSourceService.__new__(KnowledgeSourceService)
    principal = _principal("owner-1")
    source = KnowledgeSource(
        source_id="src-1",
        knowledge_base_id="kb-1",
        source_type=SourceType.URL_LIST,
        name="Portal",
        base_uri="https://example.com/source",
        criticality=Criticality.REQUIRED,
        status=SourceStatus.ACTIVE,
        refresh_policy="manual",
        created_at=datetime.now(UTC),
    )
    document = SourceDocument(
        document_id="doc-1",
        source_id=source.source_id,
        document_type=DocumentType.NORMATIVE,
        title="Spec",
        uri="https://example.com/spec.md",
        status=SourceDocumentStatus.REGISTERED,
        registered_at=datetime.now(UTC),
    )

    observed: dict[str, object] = {}

    class _SourcesRepo:
        def list_visible(
            self, *, knowledge_base_id=None, owner_user_id=None, include_archived=False
        ):
            observed["knowledge_base_id"] = knowledge_base_id
            observed["owner_user_id"] = owner_user_id
            observed["include_archived"] = include_archived
            return [source]

    class _DocumentsRepo:
        def list_for_sources(self, source_ids, *, include_archived=False):
            observed["batch_source_ids"] = [str(item) for item in source_ids]
            observed["batch_include_archived"] = include_archived
            return {str(source.source_id): [document]}

        def list_for_source(self, *_args, **_kwargs):  # pragma: no cover - should not be used
            raise AssertionError("single-source document loading should not be used")

    class _ProcessingRepo:
        def get_latest_for_sources(self, source_ids):
            observed["latest_batch_ids"] = [str(item) for item in source_ids]
            return {
                str(source.source_id): SimpleNamespace(
                    processed_at=datetime.now(UTC),
                    status=SourceProcessingStatus.PARSED,
                    error_code=None,
                    error_message=None,
                )
            }

        def get_latest_success_for_sources(self, source_ids):
            observed["latest_success_batch_ids"] = [str(item) for item in source_ids]
            return {
                str(source.source_id): SimpleNamespace(
                    processed_at=datetime.now(UTC),
                    status=SourceProcessingStatus.PARSED,
                    error_code=None,
                    error_message=None,
                )
            }

        def get_latest_for_source(self, *_args, **_kwargs):  # pragma: no cover - should not be used
            raise AssertionError("single-source processing lookup should not be used")

        def get_latest_success_for_source(
            self, *_args, **_kwargs
        ):  # pragma: no cover - should not be used
            raise AssertionError("single-source success lookup should not be used")

    service.sources = _SourcesRepo()
    service.documents = _DocumentsRepo()
    service.processing_results = _ProcessingRepo()
    service.settings = SimpleNamespace(knowledge_auto_sync_interval_days=30)
    service._get_base = lambda knowledge_base_id, principal=None: SimpleNamespace(
        knowledge_base_id=knowledge_base_id
    )

    payloads = KnowledgeSourceService.list_source_payloads(service, principal=principal)

    assert observed["owner_user_id"] == "owner-1"
    assert observed["batch_source_ids"] == ["src-1"]
    assert observed["latest_batch_ids"] == ["src-1"]
    assert payloads[0]["document_count"] == 1


def test_ensure_upload_source_recovers_from_manual_upload_race(monkeypatch, tmp_path) -> None:
    principal = _principal()
    existing_source = SimpleNamespace(
        source_id="src-existing",
        base_uri=tmp_path.as_uri(),
        name="Загруженные файлы",
        refresh_policy="manual",
        status=SimpleNamespace(value="active"),
    )
    state = {"calls": 0}

    def _find_existing(service, *, knowledge_base_id, principal=None):
        state["calls"] += 1
        return None if state["calls"] == 1 else existing_source

    rollback_calls: list[str] = []

    service = SimpleNamespace(
        session=SimpleNamespace(rollback=lambda: rollback_calls.append("rollback")),
        create_source=lambda *args, **kwargs: (_ for _ in ()).throw(
            IntegrityError("insert", {}, Exception("dup"))
        ),
        update_source=lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(knowledge_documents_routes, "_find_manual_upload_source", _find_existing)

    resolved = knowledge_documents_routes._ensure_upload_source(
        service=service,
        principal=principal,
        knowledge_base_id="kb-1",
        upload_dir=tmp_path,
        auto_commit=False,
    )

    assert resolved is existing_source
    assert rollback_calls == ["rollback"]


def test_operations_list_and_detail_hide_foreign_runs() -> None:
    service = OperationsQueryService.__new__(OperationsQueryService)
    service.session = SimpleNamespace()
    service.settings = SimpleNamespace()
    service.operation_steps = SimpleNamespace(list_for_operation=lambda **kwargs: [])
    service.audit = SimpleNamespace(list_filtered=lambda **kwargs: [])
    service.knowledge_runs = SimpleNamespace(list_recent=lambda **kwargs: [], get=lambda _id: None)
    own_run = SimpleNamespace(
        generation_run_id="gen-own",
        status=SimpleNamespace(value=GenerationRunStatus.COMPLETED.value),
        current_stage="completed",
        correlation_id="corr-own",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        started_by_user_id="user-1",
        business_task_id="task-1",
        knowledge_version_id="kv-1",
        solution_version=SimpleNamespace(solution_version_id="sol-1"),
        diagnostics={},
    )
    foreign_run = SimpleNamespace(
        generation_run_id="gen-foreign",
        status=SimpleNamespace(value=GenerationRunStatus.COMPLETED.value),
        current_stage="completed",
        correlation_id="corr-foreign",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        started_by_user_id="user-2",
        business_task_id="task-2",
        knowledge_version_id="kv-2",
        solution_version=SimpleNamespace(solution_version_id="sol-2"),
        diagnostics={},
    )
    service.generation_runs = SimpleNamespace(
        list_recent=lambda **kwargs: [own_run, foreign_run],
        get=lambda operation_id: own_run
        if operation_id == "gen-own"
        else foreign_run
        if operation_id == "gen-foreign"
        else None,
    )
    service.verification_runs = SimpleNamespace(
        list_recent=lambda **kwargs: [], get=lambda _id: None
    )

    rows = service.list_operations(limit=10, principal=_principal("user-1"))

    assert [item["operation_id"] for item in rows] == ["gen-own"]
    with pytest.raises(NotFoundError):
        service.get_operation_detail("gen-foreign", principal=_principal("user-1"))


def test_audit_events_are_filtered_to_visible_operations() -> None:
    service = OperationsQueryService.__new__(OperationsQueryService)
    service.session = SimpleNamespace()
    service.settings = SimpleNamespace()
    service.operation_steps = SimpleNamespace(list_for_operation=lambda **kwargs: [])
    own_run = SimpleNamespace(started_by_user_id="user-1")
    foreign_run = SimpleNamespace(started_by_user_id="user-2")
    own_target_id = "00000000-0000-0000-0000-000000000011"
    foreign_target_id = "00000000-0000-0000-0000-000000000022"
    service.knowledge_runs = SimpleNamespace(get=lambda _id: None)
    service.generation_runs = SimpleNamespace(
        get=lambda target_id: own_run
        if target_id == own_target_id
        else foreign_run
        if target_id == foreign_target_id
        else None
    )
    service.verification_runs = SimpleNamespace(get=lambda _id: None)
    own_event = AuditEvent(
        audit_event_id="00000000-0000-0000-0000-000000000001",
        event_type="generation.completed",
        actor_user_id=None,
        target_type="generation_run",
        target_id=own_target_id,
        severity="info",
        message="own",
        correlation_id="corr-own",
    )
    foreign_event = AuditEvent(
        audit_event_id="00000000-0000-0000-0000-000000000002",
        event_type="generation.completed",
        actor_user_id=None,
        target_type="generation_run",
        target_id=foreign_target_id,
        severity="info",
        message="foreign",
        correlation_id="corr-foreign",
    )
    service.audit = SimpleNamespace(
        list_filtered=lambda **kwargs: [own_event, foreign_event],
        get=lambda audit_event_id: own_event
        if str(audit_event_id) == "00000000-0000-0000-0000-000000000001"
        else foreign_event,
    )

    items = service.list_audit_events(target_type="generation_run", principal=_principal("user-1"))

    assert [item.message for item in items] == ["own"]
    with pytest.raises(NotFoundError):
        service.get_audit_event(
            "00000000-0000-0000-0000-000000000002", principal=_principal("user-1")
        )


def test_retrieval_evaluation_route_forwards_principal(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeService:
        def __init__(self, session, settings) -> None:
            return None

        def search_text(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(fragments=[], diagnostics={})

    monkeypatch.setattr(knowledge_evaluation_routes, "KnowledgeQueryService", _FakeService)
    monkeypatch.setattr(
        knowledge_evaluation_routes,
        "parse_eval_case",
        lambda payload: SimpleNamespace(
            query_text=payload["query_text"],
            top_k=payload.get("top_k"),
            use_case="generation",
            section_code=None,
        ),
    )
    monkeypatch.setattr(
        knowledge_evaluation_routes,
        "evaluate_retrieval_case",
        lambda case, fragments, diagnostics=None: {"query_text": case.query_text},
    )
    monkeypatch.setattr(
        knowledge_evaluation_routes,
        "aggregate_retrieval_eval",
        lambda case_results, dataset_name, knowledge_version_id: SimpleNamespace(
            as_dict=lambda: {
                "dataset_name": dataset_name,
                "knowledge_version_id": knowledge_version_id,
                "case_results": case_results,
            }
        ),
    )
    monkeypatch.setattr(
        knowledge_evaluation_routes,
        "RetrievalEvaluationResponse",
        SimpleNamespace(model_validate=lambda payload: payload),
    )

    payload = RetrievalEvaluationRequest.model_validate(
        {
            "dataset_name": "smoke",
            "knowledge_version_id": "00000000-0000-0000-0000-000000000001",
            "cases": [
                {
                    "query_text": "Where is billing described?",
                    "expected_document_ids": ["00000000-0000-0000-0000-000000000111"],
                }
            ],
        }
    )

    knowledge_evaluation_routes.run_retrieval_evaluation(
        payload=payload,
        session=SimpleNamespace(),
        settings=SimpleNamespace(),
        _principal=_principal("user-1"),
    )

    assert captured["principal"].user_id == "user-1"


def test_generation_retrieval_forwards_run_principal_to_knowledge_query() -> None:
    captured: dict[str, object] = {}
    service = RetrievalService.__new__(RetrievalService)
    service.versions = SimpleNamespace(
        get_with_documents=lambda version_id: SimpleNamespace(
            knowledge_version_id=version_id, version_documents=[]
        )
    )
    service.knowledge_query = SimpleNamespace(
        search_text=lambda **kwargs: captured.update(kwargs)
        or SimpleNamespace(fragments=[], diagnostics={}),
        _build_query_profile=lambda **kwargs: {},
    )
    principal = _principal("local.user")
    task = SimpleNamespace(
        title="Catalog", task_text="Prepare target architecture", task_metadata=None
    )

    service.retrieve_for_task(task=task, knowledge_version_ids=["kv-user"], principal=principal)

    assert captured["knowledge_version_id"] == "kv-user"
    assert captured["principal"] is principal


def test_generation_runtime_restores_principal_from_started_by_user_id() -> None:
    principal = _build_run_principal(SimpleNamespace(started_by_user_id="local.user"))

    assert principal is not None
    assert principal.user_id == "local.user"
    assert principal.login == "local.user"
