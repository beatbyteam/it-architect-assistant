from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError
from app.core.security import AuthPrincipal
from app.db.enums import (
    AccountType,
    BusinessTaskStatus,
    CheckResultStatus,
    KnowledgeBaseKind,
    KnowledgeBaseStatus,
    KnowledgeVersionStatus,
    Severity,
    SolutionVersionStatus,
)
from app.db.models.knowledge import KnowledgeBase, KnowledgeBaseSelection, KnowledgeVersion
from app.domain.services.generation.persistence_service import SolutionPersistenceService
from app.domain.services.knowledge_bases import KnowledgeBaseService
from app.domain.services.mvp_task_write_service import start_generation
from app.domain.services.verification.common import VerificationExecutionContext
from app.domain.services.verification.document_scope import filter_version_documents_for_scope
from app.domain.services.verification.rule_executors import (
    TechnicalRulesExecutor,
    VerificationSupportContext,
)
from app.integrations.verification import VerificationRuleDefinition


class _PersistenceSession:
    def __init__(self, *, fail_first: bool = False, fail_always: bool = False) -> None:
        self.fail_first = fail_first
        self.fail_always = fail_always
        self.flush_calls = 0
        self.rollback_calls = 0
        self.expire_all_calls = 0
        self.added: list[object] = []
        self.refreshed: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        self.flush_calls += 1
        if self.fail_always or (self.fail_first and self.flush_calls == 1):
            raise IntegrityError("insert into solution_versions", {}, Exception("duplicate key"))

    def rollback(self) -> None:
        self.rollback_calls += 1

    def expire_all(self) -> None:
        self.expire_all_calls += 1

    def refresh(self, obj: object) -> None:
        self.refreshed.append(obj)


class _IdempotencyCapture:
    def __init__(self) -> None:
        self.request_payload: dict | None = None

    def resolve_existing(self, **kwargs):
        self.request_payload = kwargs["request_payload"]
        raise RuntimeError("captured")


class _NoopReadService:
    def get_generation_run_payload(self, *_args, **_kwargs):
        raise AssertionError("should not be called")


class _GenerationRunStarter:
    def start_run(self, *_args, **_kwargs):
        raise AssertionError("should not be called")


def _service_principal(login: str = "svc.worker") -> AuthPrincipal:
    return AuthPrincipal(
        user_id=None,
        login=login,
        display_name="Service Worker",
        account_type=AccountType.SERVICE,
        role_codes=["SERVICE"],
        is_authenticated=True,
    )


def test_solution_persistence_retries_after_version_conflict() -> None:
    session = _PersistenceSession(fail_first=True)
    service = SolutionPersistenceService.__new__(SolutionPersistenceService)
    service.session = session
    next_versions = iter([1, 2])
    service.solutions = SimpleNamespace(get_next_version_no=lambda _task_id: next(next_versions))

    payload = SimpleNamespace(
        solution_title="Proposed architecture",
        executive_summary="Summary",
        section_readiness=[],
        structured_model=None,
        sections=[],
        components=[],
        integrations=[],
        assumptions=[],
        next_steps=[],
        risks=[],
    )
    solution = service.persist(
        business_task=SimpleNamespace(business_task_id="task-1"),
        run=SimpleNamespace(generation_run_id="run-1"),
        payload=payload,
    )

    assert solution.version_no == 2
    assert solution.status == SolutionVersionStatus.PUBLISHED
    assert session.rollback_calls == 1
    assert session.expire_all_calls == 1
    assert session.flush_calls >= 2


def test_solution_persistence_translates_repeated_conflict_to_domain_error() -> None:
    session = _PersistenceSession(fail_always=True)
    service = SolutionPersistenceService.__new__(SolutionPersistenceService)
    service.session = session
    service.solutions = SimpleNamespace(get_next_version_no=lambda _task_id: 1)

    payload = SimpleNamespace(
        solution_title="Proposed architecture",
        executive_summary="Summary",
        section_readiness=[],
        structured_model=None,
        sections=[],
        components=[],
        integrations=[],
        assumptions=[],
        next_steps=[],
        risks=[],
    )

    with pytest.raises(ConflictError) as exc_info:
        service.persist(
            business_task=SimpleNamespace(business_task_id="task-1"),
            run=SimpleNamespace(generation_run_id="run-1"),
            payload=payload,
        )

    assert exc_info.value.error_code == "SOLUTION_VERSION_CONFLICT"
    assert session.rollback_calls == 3


def test_verification_support_context_builds_basis_inventory_from_full_scope() -> None:
    def _version_doc(document_id: str, title: str, document_type: str) -> SimpleNamespace:
        return SimpleNamespace(
            role_code=None,
            required_flag=None,
            document=SimpleNamespace(
                document_id=document_id,
                title=title,
                version_label="v1",
                uri=f"kb://{document_id}",
                document_type=document_type,
                source=SimpleNamespace(criticality=None),
            ),
        )

    context = VerificationExecutionContext(
        solution=SimpleNamespace(
            executive_summary="summary",
            sections=[],
            list_items=[],
            components=[],
            integrations=[],
            risks=[],
        ),
        run=SimpleNamespace(knowledge_version=None),
        rules=[],
        rule_lookup={},
        knowledge_versions=[
            SimpleNamespace(
                version_documents=[
                    _version_doc("doc-1", "IG1242 ODA Component Inventory", "normative"),
                    _version_doc("doc-2", "ODA Core Principles", "normative"),
                ]
            ),
            SimpleNamespace(
                version_documents=[
                    _version_doc("doc-3", "ArchiMate 3.2 Modelling Rules", "architecture"),
                    _version_doc("doc-4", "Selected Technology Standard", "technology"),
                ]
            ),
        ],
    )

    support = VerificationSupportContext.build(context)
    rule = VerificationRuleDefinition(
        code="VR-TEC-03",
        name="Required basis packages available",
        group="technical",
        default_severity=Severity.CRITICAL,
        technical=True,
    )
    result = TechnicalRulesExecutor().execute(rule=rule, context=context, support=support)

    assert result.status == CheckResultStatus.PASSED
    assert support.basis_inventory.missing_required_packages == []


def test_user_managed_verification_scope_does_not_require_system_basis_packages() -> None:
    version_document = SimpleNamespace(
        document_id="doc-reference",
        role_code="reference_only",
        required_flag=False,
        document=SimpleNamespace(
            document_id="doc-reference",
            title="Проектный регламент интеграции",
            version_label="v1",
            uri="kb://doc-reference",
            document_type="other",
            source=SimpleNamespace(criticality=None),
        ),
    )
    context = VerificationExecutionContext(
        solution=SimpleNamespace(
            executive_summary="summary",
            sections=[],
            list_items=[],
            components=[],
            integrations=[],
            risks=[],
        ),
        run=SimpleNamespace(knowledge_version=None),
        rules=[],
        rule_lookup={},
        knowledge_versions=[
            SimpleNamespace(
                knowledge_base=SimpleNamespace(kind=KnowledgeBaseKind.USER_MANAGED),
                version_documents=[version_document],
            )
        ],
    )

    support = VerificationSupportContext.build(context)
    rule = VerificationRuleDefinition(
        code="VR-TEC-03",
        name="Required basis packages available",
        group="technical",
        default_severity=Severity.CRITICAL,
        technical=True,
    )
    result = TechnicalRulesExecutor().execute(rule=rule, context=context, support=support)

    assert result.status == CheckResultStatus.PASSED
    assert support.basis_inventory.missing_required_packages == []
    assert support.support_summary["basis_requirement_mode"] == "scoped_documents"


def test_full_document_scope_preserves_effective_document_ids_across_versions() -> None:
    def _version_doc(document_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            document_id=document_id,
            document=SimpleNamespace(title=f"Document {document_id}"),
        )

    version_documents = [
        _version_doc("doc-b"),
        _version_doc("doc-a"),
        _version_doc("doc-c"),
        _version_doc("doc-a"),
    ]
    scope_snapshot = {
        "document_scope": {
            "mode": "full",
            "effective_document_ids": ["doc-c", "doc-a"],
        }
    }

    scoped_documents = filter_version_documents_for_scope(version_documents, scope_snapshot)

    assert [item.document_id for item in scoped_documents] == ["doc-c", "doc-a"]


def test_technical_basis_gap_is_warning_when_verification_materials_exist() -> None:
    rule = VerificationRuleDefinition(
        code="VR-TEC-03",
        name="Expected basis packages are available",
        group="technical",
        default_severity=Severity.CRITICAL,
        technical=True,
    )
    support = VerificationSupportContext(
        section_by_code={},
        section_codes=set(),
        combined_section_text="",
        assumptions=[],
        next_steps=[],
        components=[],
        integrations=[],
        risks=[],
        basis_inventory=SimpleNamespace(
            basis_documents=[SimpleNamespace(document_id="doc-1")],
            required_packages=[{"role_code": "oda"}],
            missing_required_packages=["oda"],
        ),
        required_fragments_by_role={},
        support_summary={},
    )

    result = TechnicalRulesExecutor().execute(
        rule=rule,
        context=SimpleNamespace(solution=SimpleNamespace(), run=SimpleNamespace()),
        support=support,
    )

    assert result.status == CheckResultStatus.WARNING
    assert result.diagnostics["missing_required_packages"] == ["oda"]


def test_technical_basis_gap_stays_failed_without_verification_materials() -> None:
    rule = VerificationRuleDefinition(
        code="VR-TEC-03",
        name="Expected basis packages are available",
        group="technical",
        default_severity=Severity.CRITICAL,
        technical=True,
    )
    support = VerificationSupportContext(
        section_by_code={},
        section_codes=set(),
        combined_section_text="",
        assumptions=[],
        next_steps=[],
        components=[],
        integrations=[],
        risks=[],
        basis_inventory=SimpleNamespace(
            basis_documents=[],
            required_packages=[{"role_code": "oda"}],
            missing_required_packages=["oda"],
        ),
        required_fragments_by_role={},
        support_summary={},
    )

    result = TechnicalRulesExecutor().execute(
        rule=rule,
        context=SimpleNamespace(solution=SimpleNamespace(), run=SimpleNamespace()),
        support=support,
    )

    assert result.status == CheckResultStatus.FAILED


def test_knowledge_base_payloads_mark_effective_default_base_when_selection_is_stale() -> None:
    principal = _service_principal()
    mandatory_base = KnowledgeBase(
        knowledge_base_id="kb-mandatory",
        code="mandatory_architecture_baseline",
        name="Mandatory",
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
    selected_base = KnowledgeBase(
        knowledge_base_id="kb-archived",
        code="archived_base",
        name="Archived",
        kind=KnowledgeBaseKind.USER_MANAGED,
        status=KnowledgeBaseStatus.ARCHIVED,
        owner_user_id="svc.worker",
    )
    default_version = KnowledgeVersion(
        knowledge_version_id="kv-default",
        knowledge_base_id="kb-default",
        version_no="KV-default",
        update_run_id="run-default",
        status=KnowledgeVersionStatus.ACTIVE,
    )
    archived_version = KnowledgeVersion(
        knowledge_version_id="kv-archived",
        knowledge_base_id="kb-archived",
        version_no="KV-archived",
        update_run_id="run-archived",
        status=KnowledgeVersionStatus.ACTIVE,
    )
    selection = KnowledgeBaseSelection(
        knowledge_base_selection_id="sel-1",
        selection_scope="generation:svc.worker",
        selected_knowledge_base_id="kb-archived",
        selected_knowledge_version_id="kv-archived",
    )
    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.session = SimpleNamespace()
    service._assert_base_access = lambda _base_obj, principal=None: None
    service._base_stats = lambda _base_obj: {}
    service.bases = SimpleNamespace(
        list_visible=lambda owner_user_id=None: [default_base],
        get=lambda knowledge_base_id: default_base
        if knowledge_base_id == "kb-default"
        else selected_base
        if knowledge_base_id == "kb-archived"
        else None,
        get_by_code=lambda code, owner_user_id=None: mandatory_base
        if code == "mandatory_architecture_baseline"
        else default_base
        if code == "default_user_knowledge_base__svc.worker"
        else None,
    )
    service.selections = SimpleNamespace(get_for_scope=lambda scope: selection)
    service.versions = SimpleNamespace(
        get=lambda knowledge_version_id: archived_version
        if knowledge_version_id == "kv-archived"
        else None,
        get_with_documents=lambda knowledge_version_id: archived_version
        if knowledge_version_id == "kv-archived"
        else None,
        get_active=lambda knowledge_base_id, eager=False: default_version
        if knowledge_base_id == "kb-default"
        else archived_version
        if knowledge_base_id == "kb-archived"
        else None,
        list_visible=lambda knowledge_base_id: [default_version]
        if knowledge_base_id == "kb-default"
        else [archived_version],
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
    payload = service.get_base_payload("kb-default", principal)
    scope = service.get_existing_effective_scope(principal)

    assert scope is not None
    assert str(scope.selected_user_base.knowledge_base_id) == "kb-default"
    assert items[0]["selected_for_generation"] is True
    assert items[0]["selected_knowledge_version_id"] == "kv-default"
    assert payload["selected_for_generation"] is True
    assert payload["selected_knowledge_version_id"] == "kv-default"


def test_mvp_generation_idempotency_payload_ignores_correlation_id() -> None:
    capture = _IdempotencyCapture()
    service = SimpleNamespace(
        _get_task=lambda task_id, principal: SimpleNamespace(
            business_task_id=task_id,
            status=BusinessTaskStatus.READY_FOR_GENERATION,
            clarification_requests=[],
        ),
        idempotency=capture,
        _canonical_task_state=lambda task: BusinessTaskStatus.READY_FOR_GENERATION.value,
        _assess_task_readiness=lambda task: {"missing_inputs": []},
        _latest_open_clarification=lambda task: None,
        _reassess_task=lambda task, principal, reopen=False: None,
    )

    with pytest.raises(RuntimeError, match="captured"):
        start_generation(
            service,
            "task-1",
            correlation_id="corr-1",
            principal=_service_principal(),
            idempotency_key="idem-1",
            generation_run_service_factory=lambda *_args, **_kwargs: _GenerationRunStarter(),
            read_service_factory=lambda *_args, **_kwargs: _NoopReadService(),
        )

    assert capture.request_payload == {"task_id": "task-1"}
