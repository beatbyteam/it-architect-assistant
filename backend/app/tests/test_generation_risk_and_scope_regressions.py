from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from app.core.security import AuthPrincipal
from app.db.enums import (
    AccountType,
    BusinessTaskStatus,
    KnowledgeBaseKind,
    KnowledgeBaseStatus,
    KnowledgeVersionStatus,
    Severity,
)
from app.db.models.knowledge import (
    KnowledgeBase,
    KnowledgeFragment,
    KnowledgeFragmentEmbedding,
    KnowledgeVersion,
)
from app.domain.architecture import validate_archimate_alignment
from app.domain.services.generation.post_validation import GenerationPostValidator
from app.domain.services.generation.run_service import (
    GENERATION_RETRYABLE_TASK_STATUSES,
    GenerationRunService,
)
from app.domain.services.knowledge_bases import EffectiveKnowledgeScope, KnowledgeBaseService
from app.domain.services.knowledge_query import KnowledgeQueryService
from app.domain.services.mvp_canonical import CanonicalTaskService
from app.domain.services.mvp_task_write_service import create_task, list_tasks
from app.domain.services.verification.query_service import VerificationQueryService
from app.integrations.generation.contracts import (
    REQUIRED_SECTION_CODES,
    GenerationRisk,
    GenerationSolutionPayload,
)
from app.integrations.generation.llm_gateway import RetrievedFragment
from app.integrations.generation.payload_normalization_sections import (
    _apply_section_guidance,
    _ensure_allowed_archimate_marker,
    _pick_fragment_for_section,
)
from app.integrations.generation.payload_normalization_source_refs import (
    _canonicalize_source_refs_against_retrieved,
    _enrich_critical_section_source_refs,
)
from app.integrations.generation.payload_normalization_top_level import _normalize_risks_list
from app.integrations.knowledge.retrieval_policies import cosine_similarity


def _service_principal(login: str = "svc.worker") -> AuthPrincipal:
    return AuthPrincipal(
        user_id=None,
        login=login,
        display_name="Service Worker",
        account_type=AccountType.SERVICE,
        role_codes=["SERVICE"],
        is_authenticated=True,
    )


def _minimal_generation_payload() -> GenerationSolutionPayload:
    return GenerationSolutionPayload.model_validate(
        {
            "solution_title": "Architecture",
            "executive_summary": "Достаточно подробное summary для нормализации секций.",
            "sections": [
                {
                    "section_code": code,
                    "title": code.replace("_", " ").title(),
                    "body_markdown": f"Section body for {code} with enough words to be substantive.",
                    "source_refs": [],
                }
                for code in REQUIRED_SECTION_CODES
            ],
            "components": [
                {
                    "component_name": "Workflow Service",
                    "role_description": "Обрабатывает бизнес-поток и координирует исполнение заявки.",
                    "boundary_type": "application_architecture",
                    "external_flag": False,
                }
            ],
            "integrations": [],
            "assumptions": ["Решение работает в существующем корпоративном контуре."],
            "next_steps": ["Уточнить сценарии интеграции и SLA."],
            "risks": [
                {
                    "title": "Integration risk",
                    "description": "Недостаточно согласованы интеграционные контракты между системами.",
                    "mitigation": "Зафиксировать schema contract и прогнать контрактные тесты.",
                    "severity": "major",
                }
            ],
        }
    )


def test_risk_contract_replaces_placeholder_mitigation() -> None:
    risk = GenerationRisk.model_validate(
        {
            "title": "Integration contracts are unclear",
            "severity": "major",
            "description": "Integration contracts between approval service and publication service are not confirmed.",
            "mitigation": "TBD",
        }
    )

    assert "владельца" in risk.mitigation.lower()
    assert "отката" in risk.mitigation.lower()
    assert "архитектурном чекпоинте" in risk.mitigation.lower()


def test_risk_contract_accepts_llm_risk_alias_fields() -> None:
    risk = GenerationRisk.model_validate(
        {
            "risk_id": 1,
            "risk_title": "Delayed integration approval",
            "risk_description": "Integration access approvals may delay architecture validation.",
            "risk_level": "high",
            "mitigation_strategy": "Integration owner confirms approvals, checks access before validation, and falls back to stubbed contract tests.",
        }
    )

    assert risk.title == "Delayed integration approval"
    assert risk.description == "Integration access approvals may delay architecture validation."
    assert risk.severity == Severity.CRITICAL
    assert "Integration owner confirms approvals" in risk.mitigation


def test_risk_contract_synthesizes_description_from_risk_title() -> None:
    risk = GenerationRisk.model_validate(
        {
            "risk_title": "Incomplete acceptance criteria",
            "severity": "major",
            "mitigation_actions": "Architecture owner reviews criteria before approval and rolls back publication if criteria remain incomplete.",
        }
    )

    assert risk.title == "Incomplete acceptance criteria"
    assert "Incomplete acceptance criteria" in risk.description
    assert "может повлиять" in risk.description


def test_normalize_risks_replaces_low_signal_mitigation() -> None:
    risks = _normalize_risks_list(
        [
            {
                "title": "Integration contracts are unclear",
                "severity": "major",
                "description": "Integration contracts between approval service and publication service are not confirmed.",
                "mitigation": "Define mitigation plan during architecture review.",
            }
        ]
    )

    assert risks[0]["mitigation"] != "Define mitigation plan during architecture review."
    assert "владельца" in risks[0]["mitigation"].lower()
    assert "отката" in risks[0]["mitigation"].lower()


def test_normalize_risks_accepts_llm_alias_fields() -> None:
    risks = _normalize_risks_list(
        [
            {
                "risk_id": 1,
                "risk_title": "Delayed integration approval",
                "risk_description": "Integration access approvals may delay architecture validation.",
                "risk_level": "high",
                "risk_mitigation": "Integration owner confirms approvals, checks access before validation, and falls back to stubbed contract tests.",
            }
        ]
    )

    assert risks[0]["title"] == "Delayed integration approval"
    assert risks[0]["description"] == "Integration access approvals may delay architecture validation."
    assert risks[0]["severity"] == "critical"
    assert "Integration owner confirms approvals" in risks[0]["mitigation"]


def test_failed_generation_task_can_be_retried() -> None:
    assert BusinessTaskStatus.FAILED in GENERATION_RETRYABLE_TASK_STATUSES
    assert BusinessTaskStatus.READY_FOR_GENERATION in GENERATION_RETRYABLE_TASK_STATUSES


def test_archimate_marker_is_added_when_business_section_omits_allowed_terms() -> None:
    body, applied = _ensure_allowed_archimate_marker(
        "business_architecture",
        "The section explains approval routing, stakeholder responsibilities, and target operating model.",
    )

    assert applied is True
    assert "Business Process" in body
    alignment = validate_archimate_alignment("business_architecture", body)
    assert alignment["has_allowed_content"] is True


def test_archimate_marker_is_not_added_when_business_section_has_allowed_terms() -> None:
    original = "Business Process coordinates approval routing for the target operating model."

    body, applied = _ensure_allowed_archimate_marker("business_architecture", original)

    assert applied is False
    assert body == original


def test_section_guidance_applies_archimate_marker_before_validation() -> None:
    payload = _minimal_generation_payload()
    patched_sections = []
    for section in payload.sections:
        if section.section_code == "business_architecture":
            patched_sections.append(
                section.model_copy(
                    update={
                        "body_markdown": (
                            "The section explains approval routing, stakeholder responsibilities, "
                            "operating model, ownership, scenario, service expectation, coordination, "
                            "process governance, and business capability for request handling."
                        )
                    }
                )
            )
        else:
            patched_sections.append(section)
    payload = payload.model_copy(update={"sections": patched_sections})

    patched_payload, diagnostics = _apply_section_guidance(
        payload,
        task_title="Approval service architecture",
        task_text="Need approval routing architecture",
        context_items=[],
        retrieved_fragments=[],
    )
    section = next(
        item
        for item in patched_payload.sections
        if item.section_code == "business_architecture"
    )

    assert diagnostics["archimate_alignment_sections"] == ["business_architecture"]
    assert "Business Process" in section.body_markdown
    assert validate_archimate_alignment("business_architecture", section.body_markdown)[
        "has_allowed_content"
    ]


def test_section_guidance_repairs_data_architecture_disallowed_archimate_terms() -> None:
    payload = _minimal_generation_payload()
    patched_sections = []
    for section in payload.sections:
        if section.section_code == "data_architecture":
            patched_sections.append(
                section.model_copy(
                    update={
                        "body_markdown": (
                            "Data Object stores approval metadata, ownership signals, producer, "
                            "consumer, exchange details, message flow, and retention rules."
                        )
                    }
                )
            )
        else:
            patched_sections.append(section)
    payload = GenerationSolutionPayload.model_validate(
        {
            **payload.model_dump(mode="python"),
            "sections": [section.model_dump(mode="python") for section in patched_sections],
            "components": [
                *[
                    component.model_dump(mode="python")
                    for component in payload.components
                ],
                {
                    "component_name": "Approval Metadata Store",
                    "role_description": "Node stores data objects for the approval workflow.",
                    "boundary_type": "data_architecture",
                    "external_flag": False,
                },
            ],
        }
    )

    patched_payload, diagnostics = _apply_section_guidance(
        payload,
        task_title="Approval service architecture",
        task_text="Need approval routing architecture with metadata exchange",
        context_items=[],
        retrieved_fragments=[],
    )
    data_section = next(
        item for item in patched_payload.sections if item.section_code == "data_architecture"
    )
    alignment = validate_archimate_alignment("data_architecture", data_section.body_markdown)

    assert "data_architecture" in diagnostics["archimate_alignment_sections"]
    assert alignment["disallowed_element_codes"] == []
    assert alignment["has_allowed_content"] is True


def test_canonicalize_source_refs_drops_refs_when_retrieval_is_empty() -> None:
    refs = _canonicalize_source_refs_against_retrieved(
        [
            {
                "fragment_id": "invented-frag",
                "document_id": "invented-doc",
                "quote_text": "Invented evidence quote",
            }
        ],
        retrieved_fragments=[],
    )

    assert refs == []


def test_pick_fragment_for_section_requires_real_relevance_signal() -> None:
    fragment = RetrievedFragment(
        fragment_id="frag-k8s",
        document_id="doc-k8s",
        title="Kubernetes operations",
        content="Cluster autoscaling, node pool rotation and ingress controller operations.",
        score=0.9,
        lexical_score=0.7,
        vector_score=0.8,
    )

    chosen = _pick_fragment_for_section(
        section_code="business_architecture",
        section_title="Business Architecture",
        body_markdown="Workflow orchestration, approval routing and business actor responsibilities for request handling.",
        retrieved_fragments=[fragment],
    )

    assert chosen is None


def test_enrich_critical_section_source_refs_does_not_attach_unrelated_fragment() -> None:
    payload = _minimal_generation_payload()
    fragment = RetrievedFragment(
        fragment_id="frag-k8s",
        document_id="doc-k8s",
        title="Kubernetes operations",
        content="Cluster autoscaling, node pool rotation and ingress controller operations.",
        score=0.9,
        lexical_score=0.7,
        vector_score=0.8,
    )

    enriched = _enrich_critical_section_source_refs(payload, retrieved_fragments=[fragment])
    business_section = next(
        item for item in enriched.sections if item.section_code == "business_architecture"
    )

    assert business_section.source_refs == []


def test_enrich_critical_section_source_refs_uses_section_metadata_tags() -> None:
    payload = _minimal_generation_payload()
    fragment = RetrievedFragment(
        fragment_id="frag-data",
        document_id="doc-data",
        title="Reference data handling",
        content="Canonical guidance for records, payloads, metadata and traceability.",
        score=0.4,
        lexical_score=0.1,
        vector_score=0.2,
        metadata={"section_tags": ["data_architecture"]},
    )

    enriched = _enrich_critical_section_source_refs(payload, retrieved_fragments=[fragment])
    data_section = next(
        item for item in enriched.sections if item.section_code == "data_architecture"
    )
    business_section = next(
        item for item in enriched.sections if item.section_code == "business_architecture"
    )

    assert data_section.source_refs
    assert data_section.source_refs[0].fragment_id == "frag-data"
    assert business_section.source_refs == []


def test_validator_does_not_require_refs_without_section_evidence() -> None:
    section = SimpleNamespace(
        section_code="business_architecture",
        body_markdown="Workflow orchestration for customer onboarding and approval routing.",
    )
    fragment = RetrievedFragment(
        fragment_id="frag-k8s",
        document_id="doc-k8s",
        title="Kubernetes operations",
        content="Cluster autoscaling, node pool rotation and ingress controller operations.",
        score=0.9,
        lexical_score=0.7,
        vector_score=0.8,
    )

    assert GenerationPostValidator._has_section_evidence(section, [fragment]) is False


def test_validator_detects_section_evidence_from_metadata_tags() -> None:
    section = SimpleNamespace(
        section_code="data_architecture",
        body_markdown="The section describes data ownership and canonical payloads.",
    )
    fragment = RetrievedFragment(
        fragment_id="frag-data",
        document_id="doc-data",
        title="Reference data handling",
        content="Canonical guidance for records, payloads, metadata and traceability.",
        metadata={"architecture_layers": ["data_architecture"]},
    )

    assert GenerationPostValidator._has_section_evidence(section, [fragment]) is True


def test_validate_source_refs_marks_refs_as_hallucinated_without_retrieval_context() -> None:
    section = SimpleNamespace(
        section_code="business_architecture",
        source_refs=[
            SimpleNamespace(
                fragment_id="invented-frag",
                document_id="invented-doc",
                quote_text="Long enough quote text",
            )
        ],
    )
    hallucinated: list[str] = []

    GenerationPostValidator._validate_source_refs(
        section=section,
        retrieved_fragment_ids=set(),
        retrieved_document_ids=set(),
        hallucinated_refs=hallucinated,
    )

    assert "business_architecture:fragment:invented-frag" in hallucinated
    assert "business_architecture:document:invented-doc" in hallucinated


def test_embedding_row_for_fragment_requires_selected_embedding_space() -> None:
    fragment = KnowledgeFragment(
        fragment_id="frag-1",
        knowledge_version_id="kv-1",
        document_id="doc-1",
        title="Fragment",
        content="Content",
        source_location=None,
        fragment_metadata=None,
        embedding_key=None,
        embedding=None,
        status="active",
    )
    fragment.fragment_embeddings = [
        KnowledgeFragmentEmbedding(
            fragment_embedding_id="emb-a",
            fragment_id="frag-1",
            embedding_space_id="space-a",
            embedding_key="a",
            embedding=[0.1, 0.2],
        ),
        KnowledgeFragmentEmbedding(
            fragment_embedding_id="emb-b",
            fragment_id="frag-1",
            embedding_space_id="space-b",
            embedding_key="b",
            embedding=[0.3, 0.4],
        ),
    ]

    row = KnowledgeQueryService._embedding_row_for_fragment(
        KnowledgeQueryService.__new__(KnowledgeQueryService),
        fragment,
        embedding_space_id="space-c",
    )

    assert row is None


def test_cosine_similarity_returns_zero_for_dimension_mismatch() -> None:
    assert cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0]) == 0.0


def test_effective_scope_rejects_selected_version_from_other_base() -> None:
    mandatory = KnowledgeBase(
        knowledge_base_id="kb-mandatory",
        code="mandatory_architecture_baseline",
        name="Mandatory",
        kind=KnowledgeBaseKind.SYSTEM_MANDATORY,
        status=KnowledgeBaseStatus.ACTIVE,
        owner_user_id=None,
    )
    default_user = KnowledgeBase(
        knowledge_base_id="kb-default",
        code="default_user_knowledge_base__svc_worker",
        name="Default",
        kind=KnowledgeBaseKind.USER_MANAGED,
        status=KnowledgeBaseStatus.ACTIVE,
        owner_user_id="svc.worker",
    )
    mismatched_version = KnowledgeVersion(
        knowledge_version_id="kv-foreign",
        knowledge_base_id="kb-foreign",
        version_no="KV-foreign",
        update_run_id="run-foreign",
        status=KnowledgeVersionStatus.ACTIVE,
    )
    default_active = KnowledgeVersion(
        knowledge_version_id="kv-default",
        knowledge_base_id="kb-default",
        version_no="KV-default",
        update_run_id="run-default",
        status=KnowledgeVersionStatus.ACTIVE,
    )
    mandatory_active = KnowledgeVersion(
        knowledge_version_id="kv-mandatory",
        knowledge_base_id="kb-mandatory",
        version_no="KV-mandatory",
        update_run_id="run-mandatory",
        status=KnowledgeVersionStatus.ACTIVE,
    )
    selection = SimpleNamespace(
        selected_knowledge_base=default_user,
        selected_knowledge_version_id="kv-foreign",
    )

    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.session = SimpleNamespace()
    service.ensure_system_bases = lambda principal=None: (mandatory, default_user)
    service._is_base_accessible = lambda base, principal=None: True
    service.bases = SimpleNamespace(
        get_by_code=lambda code, owner_user_id=None: mandatory
        if code == "mandatory_architecture_baseline"
        else default_user,
    )
    service.selections = SimpleNamespace(get_for_scope=lambda scope: selection)

    def _get_active(*, knowledge_base_id, eager=True):
        if knowledge_base_id == "kb-mandatory":
            return mandatory_active
        if knowledge_base_id == "kb-default":
            return default_active
        return None

    service.versions = SimpleNamespace(
        get_with_documents=lambda knowledge_version_id: mismatched_version,
        get_active=_get_active,
    )

    scope = KnowledgeBaseService._resolve_effective_scope(
        service, _service_principal(), ensure_defaults=False
    )

    assert isinstance(scope, EffectiveKnowledgeScope)
    assert str(scope.selected_user_base.knowledge_base_id) == "kb-default"
    assert str(scope.selected_user_version.knowledge_version_id) == "kv-default"


def test_canonical_task_access_allows_service_account_owner_key() -> None:
    service = CanonicalTaskService.__new__(CanonicalTaskService)
    service._has_global_scope = lambda principal: False

    service._ensure_task_access(
        SimpleNamespace(created_by_user_id="svc.worker"), _service_principal()
    )


def test_generation_and_verification_access_use_service_owner_key() -> None:
    task = SimpleNamespace(created_by_user_id="svc.worker")
    generation_service = GenerationRunService.__new__(GenerationRunService)
    generation_service._has_global_scope = lambda principal: False
    generation_service._ensure_task_access(task, _service_principal())

    verification_service = VerificationQueryService.__new__(VerificationQueryService)
    verification_service._has_global_scope = lambda principal: False
    verification_service._ensure_solution_access(
        SimpleNamespace(business_task=SimpleNamespace(created_by_user_id="svc.worker")),
        _service_principal(),
    )


def test_list_tasks_filters_by_service_login_when_user_id_missing() -> None:
    captured = {}

    class _Session:
        def scalars(self, statement):
            captured["sql"] = str(statement.compile(compile_kwargs={"literal_binds": True}))
            return []

    service = SimpleNamespace(session=_Session(), _has_global_scope=lambda principal: False)

    assert list_tasks(service, _service_principal()) == []
    assert "created_by_user_id = 'svc.worker'" in captured["sql"]


def test_create_task_uses_service_login_for_owner_and_idempotency_scope() -> None:
    seen = {}
    task_holder = {}

    class _Session:
        def add(self, obj):
            task_holder.setdefault("task", obj)

        def flush(self):
            task = task_holder["task"]
            task.business_task_id = "task-1"

        def commit(self):
            return None

    class _Idempotency:
        def resolve_existing(self, **kwargs):
            seen["resolve"] = kwargs
            return None

        def register(self, **kwargs):
            seen["register"] = kwargs
            return None

    service = SimpleNamespace(
        session=_Session(),
        idempotency=_Idempotency(),
        audit=Mock(),
        _reassess_task=lambda task, principal, reopen=True: None,
        _canonical_task_state=lambda task: "draft",
        _get_task=lambda task_id, principal=None: task_holder["task"],
    )

    raw_text = (
        "  Нужно подготовить достаточно подробное описание сервисной задачи\n"
        "    1. Сохранить пользовательские отступы\n"
        "    2. Не схлопывать переносы при хранении  "
    )
    task = create_task(
        service,
        title="Service task",
        raw_text=raw_text,
        metadata={"channel": "automation"},
        save_as_draft=True,
        principal=_service_principal(),
        idempotency_key="idem-1",
    )

    assert task.created_by_user_id == "svc.worker"
    assert task.task_text == raw_text
    assert seen["resolve"]["actor_user_id"] == "svc.worker"
    assert seen["resolve"]["request_payload"]["raw_text"] == raw_text
    assert seen["register"]["actor_user_id"] == "svc.worker"
