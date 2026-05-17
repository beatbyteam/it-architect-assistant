from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.bootstrap.bundles import _upsert_document
from app.core.exceptions import DependencyUnavailableError
from app.core.security import AuthPrincipal
from app.db.enums import (
    AccountType,
    BusinessTaskStatus,
    CheckResultStatus,
    DocumentType,
    KnowledgeVersionStatus,
    ProtocolSummaryStatus,
    Severity,
    SolutionVersionStatus,
    SourceDocumentStatus,
    VerificationProtocolStatus,
)
from app.db.models.audit import AuditEvent
from app.db.models.knowledge import SourceDocument
from app.domain.services.generation.run_service import GenerationRunService
from app.domain.services.generation.retrieval_service import RetrievalService
from app.domain.services.knowledge_basis import resolve_basis_assignment
from app.domain.services.knowledge_query import KnowledgeQueryService
from app.domain.services.operations import OperationsQueryService
from app.domain.services.verification.query_service import VerificationQueryService
from app.domain.services.verification.run_service import VerificationRunService
from app.integrations.generation.contracts import REQUIRED_SECTION_CODES, GenerationSolutionPayload
from app.integrations.generation.payload_normalization_source_refs import (
    _enrich_critical_section_source_refs,
)
from app.schemas.generation import InternalGenerationRunStartRequest
from app.schemas.verification import InternalVerificationRunStartRequest


class _SessionPages:
    def __init__(self, items: list[object]) -> None:
        self._items = list(items)

    def scalars(self, statement):
        offset = int(getattr(statement._offset_clause, "value", 0) or 0)
        limit = int(getattr(statement._limit_clause, "value", len(self._items)) or len(self._items))
        return list(self._items[offset : offset + limit])


class _CapturingIdempotency:
    def __init__(self) -> None:
        self.resolve_payloads: list[dict[str, object]] = []

    def resolve_existing(self, **kwargs):
        self.resolve_payloads.append(dict(kwargs["request_payload"]))
        return SimpleNamespace(target_id="existing-run")

    def register(self, **kwargs):  # pragma: no cover - must not be called in these tests
        raise AssertionError("register must not be called when an existing run is resolved")


class _EmbeddingsStub:
    def describe(self) -> dict[str, object]:
        return {
            "provider_name": "stub-provider",
            "model_id": "stub-embed-v1",
            "dimensions": 3,
        }


class _SessionGetMap:
    def __init__(self, mapping: dict[tuple[type[object], str], object]) -> None:
        self.mapping = mapping

    def get(self, model, entity_id):
        return self.mapping.get((model, str(entity_id)))


def _principal(user_id: str = "user-1") -> AuthPrincipal:
    return AuthPrincipal(
        user_id=user_id,
        login=user_id,
        display_name=user_id,
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
                    "role_description": "Application Component handles billing orchestration.",
                }
            ],
            "integrations": [],
            "assumptions": [],
            "next_steps": [],
            "risks": [],
        }
    )


def _knowledge_version(version_id: str, base_id: str = "kb-1") -> SimpleNamespace:
    return SimpleNamespace(
        knowledge_version_id=version_id,
        knowledge_base_id=base_id,
        version_no=f"{base_id}:{version_id}",
        status=KnowledgeVersionStatus.ACTIVE,
        created_at=datetime.now(UTC),
        activated_at=datetime.now(UTC),
        activated_by_user_id="user-1",
        version_documents=[],
        source_snapshot={},
        knowledge_base=SimpleNamespace(code=f"base-{base_id}"),
    )


def test_bundle_upsert_document_persists_manifest_metadata() -> None:
    registered = SourceDocument(
        source_id="source-1",
        document_type=DocumentType.TECHNOLOGY,
        title="Selected Technology Standard",
        uri="file:///tmp/selected_technology_standard.md",
        is_latest=True,
        status=SourceDocumentStatus.REGISTERED,
    )
    service = SimpleNamespace(
        list_documents=lambda source_id: [],
        register_document=lambda source_id, payload, principal, auto_commit=False: registered,
        session=SimpleNamespace(add=lambda document: None, flush=lambda: None),
    )

    document = _upsert_document(
        None,
        service,
        _principal(),
        "source-1",
        {
            "uri": "selected_technology_standard.md",
            "title": "Selected Technology Standard",
            "document_type": "technology",
            "version_label": "TechStd-demo-2026.03",
            "is_latest": True,
        },
        "file:///tmp",
    )

    assert document is registered
    assert document.document_metadata["bundle_managed"] is True
    assert document.document_metadata["bundle_title"] == "Selected Technology Standard"
    assert document.document_metadata["bundle_document_type"] == "technology"
    assert document.document_metadata["bundle_version_label"] == "TechStd-demo-2026.03"


def test_bundle_document_metadata_can_override_basis_role_assignment() -> None:
    document = SourceDocument(
        source_id="source-1",
        document_type=DocumentType.ARCHITECTURE,
        title="ArchiMate 3.2 Section Mapping",
        uri="file:///tmp/archimate_section_mapping.md",
        is_latest=True,
        status=SourceDocumentStatus.REGISTERED,
        document_metadata={
            "bundle_role_code": "reference_only",
            "bundle_required_flag": False,
        },
    )

    role_code, required_flag = resolve_basis_assignment(document)

    assert role_code == "reference_only"
    assert required_flag is False


def test_verification_protocol_severity_filter_uses_actual_maximum() -> None:
    run = SimpleNamespace(
        verification_run_id="run-1",
        solution_version_id="sol-1",
        knowledge_version_id="kv-1",
        scope_snapshot={"validation_scope": "full", "rulebook_version": "rb-v1"},
        solution_version=SimpleNamespace(
            business_task=SimpleNamespace(created_by_user_id="user-1")
        ),
    )
    protocol = SimpleNamespace(
        verification_protocol_id="protocol-1",
        verification_run_id="run-1",
        verification_run=run,
        protocol_no="VP-1",
        summary_status=ProtocolSummaryStatus.FAILED,
        status=VerificationProtocolStatus.PUBLISHED,
        issued_at=datetime.now(UTC),
        check_results=[
            SimpleNamespace(status=CheckResultStatus.WARNING, severity=Severity.INFO),
            SimpleNamespace(status=CheckResultStatus.FAILED, severity=Severity.CRITICAL),
        ],
    )
    service = VerificationQueryService.__new__(VerificationQueryService)
    service.session = _SessionPages([protocol])
    service._ensure_solution_access = lambda solution, principal: None

    rows = service.list_protocols(principal=_principal(), severity="critical", limit=10)

    assert [row["verification_protocol_id"] for row in rows] == ["protocol-1"]


def test_required_sections_do_not_receive_fabricated_irrelevant_source_refs() -> None:
    payload = _minimal_generation_payload()
    for section in payload.sections:
        if section.section_code == "business_architecture":
            section.body_markdown = (
                "Workflow orchestration for customer onboarding and approval routing."
            )
            break
    fragment = SimpleNamespace(
        fragment_id="frag-k8s",
        document_id="doc-k8s",
        title="Kubernetes ops",
        content="Cluster autoscaling, node pools, daemonsets and pod disruption budgets.",
        lexical_score=0.2,
        vector_score=0.1,
        score=0.3,
    )

    enriched = _enrich_critical_section_source_refs(payload, retrieved_fragments=[fragment])
    section = next(
        item for item in enriched.sections if item.section_code == "business_architecture"
    )

    assert section.source_refs == []


def test_retrieval_raises_dependency_error_on_empty_embedding_payload() -> None:
    service = KnowledgeQueryService.__new__(KnowledgeQueryService)
    service.session = SimpleNamespace()
    service.settings = SimpleNamespace(reranker_provider="heuristic")
    service.embeddings = SimpleNamespace(encode_query=lambda text: SimpleNamespace(vectors=[]))
    service._get_accessible_version = lambda knowledge_version_id, principal=None: SimpleNamespace(
        knowledge_version_id=knowledge_version_id
    )

    with pytest.raises(DependencyUnavailableError) as exc_info:
        service.search_text(query_text="billing flow", knowledge_version_id="kv-1")

    assert exc_info.value.error_code == "EMBEDDING_RESPONSE_EMPTY"


def test_audit_visibility_supports_source_document_target_type() -> None:
    from app.db.models.knowledge import KnowledgeSource, SourceDocument

    source = SimpleNamespace(source_id="src-1", knowledge_base_id="kb-1")
    document = SimpleNamespace(document_id="doc-1", source_id="src-1", source=source)
    service = OperationsQueryService.__new__(OperationsQueryService)
    service.session = _SessionGetMap(
        {
            (SourceDocument, "doc-1"): document,
            (KnowledgeSource, "src-1"): source,
        }
    )
    service.knowledge_runs = SimpleNamespace(get=lambda _id: None)
    service.generation_runs = SimpleNamespace(get=lambda _id: None)
    service.verification_runs = SimpleNamespace(get=lambda _id: None)
    service._can_access_knowledge_base = (
        lambda knowledge_base_id, principal=None: knowledge_base_id == "kb-1"
    )
    event = AuditEvent(
        audit_event_id="00000000-0000-0000-0000-000000000101",
        event_type="knowledge.document.registered",
        actor_user_id=None,
        target_type="source_document",
        target_id="doc-1",
        severity="info",
        message="document",
    )

    assert service._audit_event_visible(event, _principal()) is True


def test_generation_run_visibility_allows_task_owner_when_started_by_service_account() -> None:
    from app.db.models.generation import BusinessTask

    task = SimpleNamespace(business_task_id="task-1", created_by_user_id="user-1")
    run = SimpleNamespace(
        generation_run_id="run-1", started_by_user_id="svc-worker", business_task_id="task-1"
    )
    service = OperationsQueryService.__new__(OperationsQueryService)
    service.session = _SessionGetMap({(BusinessTask, "task-1"): task})

    assert service._is_visible_generation_run(run, _principal("user-1")) is True


def test_retrieval_coverage_allows_user_base_without_required_roles() -> None:
    service = RetrievalService.__new__(RetrievalService)

    assert service.is_coverage_sufficient(
        {
            "required_roles": [],
            "retrieved_fragment_count": 2,
            "retrieved_required_fragment_count": 0,
            "required_role_coverage": 0.0,
        }
    ) is True


def test_retrieval_coverage_does_not_require_missing_basis_packages() -> None:
    service = RetrievalService.__new__(RetrievalService)
    service.knowledge_query = SimpleNamespace(_build_query_profile=lambda **kwargs: {})

    coverage = service._build_coverage_summary(
        versions=[SimpleNamespace(version_documents=[])],
        fragments=[
            SimpleNamespace(
                document_id="doc-1",
                metadata={"role_code": "reference_only"},
            ),
            SimpleNamespace(
                document_id="doc-2",
                metadata={"role_code": "reference_only"},
            ),
        ],
        query_text="target architecture",
    )

    assert coverage["required_roles"] == []
    assert coverage["missing_required_roles"] == []
    assert service.is_coverage_sufficient(coverage) is True


def test_generation_start_run_idempotency_payload_tracks_scope_and_task_snapshot() -> None:
    selected_version = _knowledge_version("kv-user")
    mandatory_version = _knowledge_version("kv-mandatory", base_id="kb-mandatory")
    task = SimpleNamespace(
        business_task_id="task-1",
        title="Design billing integration",
        task_text="Need an architecture for CRM to Billing integration with auditability.",
        task_metadata={
            "clarification_answers": {"scope": "include audit"},
            "clarification_assessment": {"missing_inputs": []},
        },
        clarification_requests=[
            SimpleNamespace(
                clarification_id="clar-1",
                state=BusinessTaskStatus.CLARIFIED,
                question_items=[{"question_code": "scope", "question_text": "What scope?"}],
                answers=[
                    SimpleNamespace(
                        question_code="scope",
                        question_text="What scope?",
                        answer_text="include audit",
                        sort_order=1,
                    )
                ],
                created_at=datetime.now(UTC),
            )
        ],
        status=BusinessTaskStatus.READY_FOR_GENERATION,
    )
    effective_scope = SimpleNamespace(
        mandatory_version=mandatory_version,
        selected_user_version=selected_version,
        selected_generation_version=lambda: selected_version,
    )
    service = GenerationRunService.__new__(GenerationRunService)
    service.session = SimpleNamespace()
    service.settings = SimpleNamespace(llm_model_id="stub-llm", reranker_provider="heuristic")
    service.idempotency = _CapturingIdempotency()
    service._get_task = lambda business_task_id: task
    service._make_base_service = lambda: SimpleNamespace(
        get_effective_scope=lambda principal=None: effective_scope
    )
    service.prompt_registry = SimpleNamespace(
        get_generation_template=lambda: SimpleNamespace(
            version_id="prompt-v1",
            template_name="canonical-generation",
            output_contract_name="generation_solution_v1",
        )
    )
    service.retrieval = SimpleNamespace(
        knowledge_query=SimpleNamespace(embeddings=_EmbeddingsStub())
    )
    service.get_run = lambda run_id, principal=None: SimpleNamespace(generation_run_id=run_id)

    result = service.start_run(
        InternalGenerationRunStartRequest(
            business_task_id="task-1", correlation_id="corr-1", idempotency_key="idem-1"
        ),
        _principal(),
    )

    payload = service.idempotency.resolve_payloads[0]
    assert result.generation_run_id == "existing-run"
    assert payload["knowledge_version_id"] == "kv-user"
    assert payload["knowledge_version_ids"] == ["kv-mandatory", "kv-user"]
    assert payload["prompt_version"] == "prompt-v1"
    assert payload["knowledge_scope_hash"]
    assert payload["task_input_hash"]


def test_verification_start_run_idempotency_payload_tracks_rulebook_and_publication_revision() -> (
    None
):
    selected_version = _knowledge_version("kv-user")
    mandatory_version = _knowledge_version("kv-mandatory", base_id="kb-mandatory")
    solution = SimpleNamespace(
        solution_version_id="sol-1",
        generation_run_id="gen-1",
        solution_title="Billing integration",
        status=SolutionVersionStatus.PUBLISHED,
        sections=[SimpleNamespace()],
        components=[SimpleNamespace()],
        integrations=[SimpleNamespace()],
        risks=[SimpleNamespace()],
    )
    effective_scope = SimpleNamespace(
        mandatory_version=mandatory_version,
        selected_user_version=selected_version,
        selected_generation_version=lambda: selected_version,
    )
    publication_artifact = SimpleNamespace(
        published_artifact_id="pub-1",
        revision_no=7,
        version_hash="artifact-hash-v7",
        published_at=datetime.now(UTC),
    )
    service = VerificationRunService.__new__(VerificationRunService)
    service.session = SimpleNamespace()
    service.settings = SimpleNamespace(reranker_provider="heuristic")
    service.idempotency = _CapturingIdempotency()
    service._get_solution = lambda solution_version_id: solution
    service._select_rules = lambda validation_scope, **_kwargs: [
        SimpleNamespace(code="VR-1"),
        SimpleNamespace(code="VR-2"),
    ]
    service.registry = SimpleNamespace(version="rulebook-v5")
    service.publication_artifacts = SimpleNamespace(
        get_current=lambda **kwargs: publication_artifact
    )
    service.knowledge_query = SimpleNamespace(embeddings=_EmbeddingsStub())
    service.get_run = lambda run_id, principal=None: SimpleNamespace(verification_run_id=run_id)

    import app.domain.services.verification.run_service as verification_run_module

    original_base_service = verification_run_module.KnowledgeBaseService
    verification_run_module.KnowledgeBaseService = lambda session: SimpleNamespace(
        get_effective_scope=lambda principal=None: effective_scope
    )
    try:
        result = service.start_run(
            InternalVerificationRunStartRequest(
                solution_version_id="sol-1",
                validation_scope="full",
                correlation_id="corr-2",
                idempotency_key="idem-2",
            ),
            _principal(),
        )
    finally:
        verification_run_module.KnowledgeBaseService = original_base_service

    payload = service.idempotency.resolve_payloads[0]
    assert result.verification_run_id == "existing-run"
    assert payload["knowledge_version_id"] == "kv-user"
    assert payload["knowledge_version_ids"] == ["kv-mandatory", "kv-user"]
    assert payload["rulebook_version"] == "rulebook-v5"
    assert payload["rule_codes"] == ["VR-1", "VR-2"]
    assert payload["publication_revision_no"] == 7
    assert payload["publication_version_hash"] == "artifact-hash-v7"
    assert payload["scope_snapshot_hash"]
