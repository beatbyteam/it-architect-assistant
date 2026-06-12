from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.exceptions import ConflictError
from app.db.enums import (
    BusinessTaskStatus,
    CheckResultStatus,
    DocumentType,
    ProtocolSummaryStatus,
    Severity,
)
from app.domain.services.knowledge_basis import classify_basis_requirement
from app.domain.services.external_architecture_check import ExternalArchitectureCheckService
from app.domain.services.verification.post_validation import VerificationPostValidator
from app.domain.services.verification.run_service import (
    VerificationRunService,
    _infer_selected_document_content_hints,
)
from app.domain.services.verification.runtime import _prepare_verification_context
from app.domain.services.verification.rule_executors import (
    ConsistencyRulesExecutor,
    NormativeRulesExecutor,
    StructureRulesExecutor,
    VerificationSupportContext,
)
from app.integrations.verification import (
    VerificationProtocolPayload,
    VerificationRuleDefinition,
)
from app.schemas.mvp import ExternalArchitectureCheckRequest


class _ScalarSession:
    def __init__(self, task: object | None) -> None:
        self.task = task
        self.statement = None

    def scalar(self, statement):
        self.statement = statement
        return self.task


def _support_with_sections(*section_codes: str) -> VerificationSupportContext:
    section_by_code = {
        section_code: SimpleNamespace(
            section_code=section_code,
            sort_order=index,
            body_markdown=f"{section_code} body",
            source_refs=[],
        )
        for index, section_code in enumerate(section_codes, start=1)
    }
    return VerificationSupportContext(
        section_by_code=section_by_code,
        section_codes=set(section_by_code),
        combined_section_text="External architecture uses corporate application and data layers.",
        assumptions=[],
        next_steps=[],
        components=[],
        integrations=[],
        risks=[],
        basis_inventory=SimpleNamespace(basis_documents=[]),
        required_fragments_by_role={
            "oda": [SimpleNamespace(fragment_id="fragment-oda")],
            "ig1242_oda_component_inventory": [
                SimpleNamespace(fragment_id="fragment-ig1242")
            ],
        },
        support_summary={},
    )


def test_external_architecture_normative_warning_links_existing_togaf_section() -> None:
    support = _support_with_sections("application_architecture", "data_architecture")
    rule = VerificationRuleDefinition(
        "VR-NRM-01",
        "Solution does not contradict ODA / IG1242",
        "normative",
        Severity.MAJOR,
    )

    result = NormativeRulesExecutor().execute(
        rule=rule,
        context=SimpleNamespace(),
        support=support,
    )

    assert result.status == CheckResultStatus.WARNING
    assert result.related_section_ref == "application_architecture"
    VerificationPostValidator().validate(
        VerificationProtocolPayload(
            summary="Synthetic normative warning.",
            check_results=[result],
            final_status=ProtocolSummaryStatus.PASSED_WITH_COMMENTS,
        ),
        expected_rule_codes=["VR-NRM-01"],
    )


def test_selected_document_normative_check_passes_without_section_citations() -> None:
    support = _support_with_sections("it_architecture_content", "application_architecture")
    rule = VerificationRuleDefinition(
        "VR-NRM-01",
        "Solution does not contradict ODA / IG1242",
        "normative",
        Severity.MAJOR,
    )

    result = NormativeRulesExecutor().execute(
        rule=rule,
        context=SimpleNamespace(selected_document_ids=["doc-ig1242"]),
        support=support,
    )

    assert result.status == CheckResultStatus.PASSED
    assert result.finding_text is None
    assert result.diagnostics["selected_document_scope"] is True


def test_full_document_scope_selects_only_rules_supported_by_documents() -> None:
    service = VerificationRunService.__new__(VerificationRunService)
    service.registry = SimpleNamespace(
        list_rules=lambda: [
            VerificationRuleDefinition(
                "VR-TEC-01", "Knowledge base has indexed documents", "technical", Severity.MAJOR
            ),
            VerificationRuleDefinition(
                "VR-STR-01", "TOGAF goal and context are captured", "structure", Severity.MAJOR
            ),
            VerificationRuleDefinition(
                "VR-NRM-02", "ArchiMate semantics are present", "normative", Severity.MAJOR
            ),
        ]
    )
    document_scope = {
        "mode": "full",
        "effective_document_ids": ["doc-1"],
        "effective_documents": [
            {
                "document_id": "doc-1",
                "title": "Описание интеграционного решения",
                "role_code": "reference_only",
                "document_type": "other",
            }
        ],
    }

    rules = VerificationRunService._select_rules(
        service,
        "full",
        document_scope=document_scope,
    )

    assert [rule.code for rule in rules] == ["VR-TEC-01"]


def test_imported_architecture_without_section_source_refs_uses_selected_knowledge_evidence() -> None:
    support = VerificationSupportContext(
        section_by_code={
            "general_information": SimpleNamespace(
                section_code="general_information",
                sort_order=1,
                body_markdown="Imported architecture section.",
                source_refs=[],
            )
        },
        section_codes={"general_information"},
        combined_section_text="Imported architecture section.",
        assumptions=[],
        next_steps=[],
        components=[],
        integrations=[],
        risks=[],
        basis_inventory=SimpleNamespace(
            basis_documents=[SimpleNamespace(document_id="doc-1", role_code="reference_only")],
            required_packages=[],
            missing_required_packages=[],
        ),
        required_fragments_by_role={},
        support_summary={
            "scoped_document_count": 1,
            "selected_document_count": 1,
            "basis_requirement_mode": "scoped_documents",
            "rule_rag": {"rules_with_evidence": 1},
        },
    )
    context = SimpleNamespace(
        selected_document_ids=["doc-1"],
        solution=SimpleNamespace(
            generation_run=SimpleNamespace(diagnostics={"source": "external_architecture"}),
            business_task=SimpleNamespace(
                task_metadata={"source": "external_architecture", "verification_only": True}
            ),
        ),
    )
    rule = VerificationRuleDefinition(
        "VR-CNS-02",
        "Source references are available",
        "consistency",
        Severity.MAJOR,
    )

    result = ConsistencyRulesExecutor().execute(rule=rule, context=context, support=support)

    assert result.status == CheckResultStatus.PASSED
    assert result.finding_text is None
    assert result.diagnostics["evidence_mode"] == "knowledge_scope"


def test_normative_missing_basis_fragments_warns_when_materials_exist() -> None:
    support = _support_with_sections("application_architecture")
    support.required_fragments_by_role = {}
    support.basis_inventory = SimpleNamespace(
        basis_documents=[SimpleNamespace(document_id="doc-archimate")]
    )
    support.support_summary = {"scoped_document_count": 1}
    rule = VerificationRuleDefinition(
        "VR-NRM-02",
        "Solution follows ArchiMate 3.2 semantics",
        "normative",
        Severity.MAJOR,
    )

    result = NormativeRulesExecutor().execute(
        rule=rule,
        context=SimpleNamespace(),
        support=support,
    )

    assert result.status == CheckResultStatus.WARNING
    assert result.diagnostics["missing_basis_fragments"] is True
    VerificationPostValidator().validate(
        VerificationProtocolPayload(
            summary="Synthetic normative warning.",
            check_results=[result],
            final_status=ProtocolSummaryStatus.PASSED_WITH_COMMENTS,
        ),
        expected_rule_codes=["VR-NRM-02"],
    )


def test_operating_system_standard_document_is_technology_basis() -> None:
    requirement = classify_basis_requirement(
        SimpleNamespace(
            title="Стандарт по операционным системам",
            uri="file:///standards/os.pdf",
            version_label=None,
            document_type=DocumentType.NORMATIVE,
        )
    )

    assert requirement is not None
    assert requirement.role_code == "technology_standard"


def test_technology_standard_forbidden_ubuntu_version_fails_verification() -> None:
    support = VerificationSupportContext(
        section_by_code={
            "technology_architecture": SimpleNamespace(
                body_markdown="Для всех серверов требуется установка Ubuntu 20.04 LTS.",
                source_refs=[],
            )
        },
        section_codes={"technology_architecture"},
        combined_section_text="Для всех серверов требуется установка Ubuntu 20.04 LTS.",
        assumptions=[],
        next_steps=[],
        components=[],
        integrations=[],
        risks=[],
        basis_inventory=SimpleNamespace(basis_documents=[]),
        required_fragments_by_role={
            "technology_standard": [
                SimpleNamespace(
                    fragment_id="fragment-os-standard",
                    title="Стандарт по операционным системам",
                    content="Ubuntu 20.04 LTS Запрещено\nUbuntu 22.04 LTS Разрешено",
                )
            ]
        },
        support_summary={},
    )
    rule = VerificationRuleDefinition(
        "VR-NRM-03",
        "Technology choice follows selected technology standard",
        "normative",
        Severity.CRITICAL,
    )

    result = NormativeRulesExecutor().execute(
        rule=rule,
        context=SimpleNamespace(),
        support=support,
    )

    assert result.status == CheckResultStatus.FAILED
    assert "ubuntu 20.04 lts < 22.04" in result.diagnostics["prohibited_hits"]


def test_technology_standard_forbidden_ubuntu_from_rule_rag_fails_verification() -> None:
    support = VerificationSupportContext(
        section_by_code={
            "technology_architecture": SimpleNamespace(
                body_markdown="Для всех серверов требуется установка Ubuntu 20.04 LTS.",
                source_refs=[],
            )
        },
        section_codes={"technology_architecture"},
        combined_section_text="Для всех серверов требуется установка Ubuntu 20.04 LTS.",
        assumptions=[],
        next_steps=[],
        components=[],
        integrations=[],
        risks=[],
        basis_inventory=SimpleNamespace(basis_documents=[]),
        required_fragments_by_role={},
        rule_evidence_by_code={
            "VR-NRM-03": [
                {
                    "fragment_id": "fragment-rag-os-standard",
                    "document_title": "1003161951_6c9ab113595e4f9bb68b447c0c469010.pdf",
                    "content_preview": "Стандарт по операционным системам. Ubuntu 20.04 LTS Запрещено.",
                }
            ]
        },
        support_summary={},
    )
    rule = VerificationRuleDefinition(
        "VR-NRM-03",
        "Technology choice follows selected technology standard",
        "normative",
        Severity.CRITICAL,
    )

    result = NormativeRulesExecutor().execute(
        rule=rule,
        context=SimpleNamespace(),
        support=support,
    )

    assert result.status == CheckResultStatus.FAILED
    assert "ubuntu 20.04 lts" in result.diagnostics["prohibited_hits"]


def test_technology_standard_rejects_ubuntu_below_forbidden_range() -> None:
    support = VerificationSupportContext(
        section_by_code={
            "technology_architecture": SimpleNamespace(
                body_markdown="Для всех серверов требуется установка Ubuntu 20.04 LTS.",
                source_refs=[],
            )
        },
        section_codes={"technology_architecture"},
        combined_section_text="Для всех серверов требуется установка Ubuntu 20.04 LTS.",
        assumptions=[],
        next_steps=[],
        components=[],
        integrations=[],
        risks=[],
        basis_inventory=SimpleNamespace(basis_documents=[]),
        required_fragments_by_role={
            "technology_standard": [
                SimpleNamespace(
                    fragment_id="fragment-os-standard",
                    title="Стандарт по операционным системам",
                    content="Ubuntu все версии ниже 22.04 Запрещено\nUbuntu 22.04 LTS Разрешено",
                )
            ]
        },
        support_summary={},
    )
    rule = VerificationRuleDefinition(
        "VR-NRM-03",
        "Technology choice follows selected technology standard",
        "normative",
        Severity.CRITICAL,
    )

    result = NormativeRulesExecutor().execute(
        rule=rule,
        context=SimpleNamespace(),
        support=support,
    )

    assert result.status == CheckResultStatus.FAILED
    assert "ubuntu 20.04 lts < 22.04" in result.diagnostics["prohibited_hits"]


def test_technology_standard_allows_debian_above_forbidden_range() -> None:
    support = VerificationSupportContext(
        section_by_code={
            "technology_architecture": SimpleNamespace(
                body_markdown="Целевой сервер использует Debian 13.",
                source_refs=[],
            )
        },
        section_codes={"technology_architecture"},
        combined_section_text="Целевой сервер использует Debian 13.",
        assumptions=[],
        next_steps=[],
        components=[],
        integrations=[],
        risks=[],
        basis_inventory=SimpleNamespace(basis_documents=[]),
        required_fragments_by_role={
            "technology_standard": [
                SimpleNamespace(
                    fragment_id="fragment-debian-standard",
                    title="Стандарт по операционным системам",
                    content="Debian все версии ниже 11 Запрещено\nDebian 13 Разрешено",
                )
            ]
        },
        support_summary={},
    )
    rule = VerificationRuleDefinition(
        "VR-NRM-03",
        "Technology choice follows selected technology standard",
        "normative",
        Severity.CRITICAL,
    )

    result = NormativeRulesExecutor().execute(
        rule=rule,
        context=SimpleNamespace(),
        support=support,
    )

    assert result.status == CheckResultStatus.PASSED
    assert result.diagnostics["prohibited_hits"] == []


def test_technology_standard_rejects_debian_below_forbidden_range() -> None:
    support = VerificationSupportContext(
        section_by_code={
            "technology_architecture": SimpleNamespace(
                body_markdown="Целевой сервер использует Debian 10.",
                source_refs=[],
            )
        },
        section_codes={"technology_architecture"},
        combined_section_text="Целевой сервер использует Debian 10.",
        assumptions=[],
        next_steps=[],
        components=[],
        integrations=[],
        risks=[],
        basis_inventory=SimpleNamespace(basis_documents=[]),
        required_fragments_by_role={
            "technology_standard": [
                SimpleNamespace(
                    fragment_id="fragment-debian-standard",
                    title="Стандарт по операционным системам",
                    content="Debian все версии ниже 11 Запрещено\nDebian 13 Разрешено",
                )
            ]
        },
        support_summary={},
    )
    rule = VerificationRuleDefinition(
        "VR-NRM-03",
        "Technology choice follows selected technology standard",
        "normative",
        Severity.CRITICAL,
    )

    result = NormativeRulesExecutor().execute(
        rule=rule,
        context=SimpleNamespace(),
        support=support,
    )

    assert result.status == CheckResultStatus.FAILED
    assert "debian 10 < 11" in result.diagnostics["prohibited_hits"]


def test_structural_warnings_fallback_to_existing_solution_section() -> None:
    support = _support_with_sections("general_information")
    support.combined_section_text = "Solution exposes API integration points."
    context = SimpleNamespace(solution=SimpleNamespace(business_task=None))
    executor = StructureRulesExecutor()
    rules = [
        VerificationRuleDefinition(
            "VR-STR-01", "Goal and task context are captured", "structure", Severity.MAJOR
        ),
        VerificationRuleDefinition(
            "VR-STR-02", "Constraints and assumptions are captured", "structure", Severity.MAJOR
        ),
        VerificationRuleDefinition(
            "VR-STR-03",
            "TOGAF architecture subsections describe the component composition",
            "structure",
            Severity.MAJOR,
        ),
        VerificationRuleDefinition(
            "VR-STR-04",
            "Data/Application architecture disclose integrations and APIs",
            "structure",
            Severity.MAJOR,
        ),
        VerificationRuleDefinition(
            "VR-STR-05",
            "Additional information records risks and open questions",
            "structure",
            Severity.MAJOR,
        ),
    ]

    results = [executor.execute(rule=rule, context=context, support=support) for rule in rules]

    assert all(result.related_section_ref == "general_information" for result in results)
    VerificationPostValidator().validate(
        VerificationProtocolPayload(
            summary="Synthetic structural findings.",
            check_results=results,
            final_status=ProtocolSummaryStatus.FAILED,
        ),
        expected_rule_codes=[rule.code for rule in rules],
    )


def test_external_architecture_check_consumes_external_architecture_draft() -> None:
    task = SimpleNamespace(
        created_by_user_id="user-1",
        task_metadata={"source": "external_architecture", "verification_only": True},
        status=BusinessTaskStatus.DRAFT,
        generation_runs=[],
    )
    service = ExternalArchitectureCheckService.__new__(ExternalArchitectureCheckService)
    service.session = _ScalarSession(task)

    consumed = service._consume_draft_task(
        ExternalArchitectureCheckRequest(
            title="External architecture",
            architecture_text="Architecture text",
            draft_task_id="draft-1",
        ),
        owner_key="user-1",
    )

    assert consumed is task


def test_external_architecture_check_rejects_regular_task_draft() -> None:
    task = SimpleNamespace(
        created_by_user_id="user-1",
        task_metadata={},
        status=BusinessTaskStatus.DRAFT,
        generation_runs=[],
    )
    service = ExternalArchitectureCheckService.__new__(ExternalArchitectureCheckService)
    service.session = _ScalarSession(task)

    with pytest.raises(ConflictError) as error:
        service._consume_draft_task(
            ExternalArchitectureCheckRequest(
                title="External architecture",
                architecture_text="Architecture text",
                draft_task_id="draft-1",
            ),
            owner_key="user-1",
        )

    assert error.value.error_code == "EXTERNAL_ARCHITECTURE_DRAFT_SCOPE_ERROR"


def test_selected_document_scope_limits_rulebook_to_selected_document_roles() -> None:
    service = VerificationRunService.__new__(VerificationRunService)
    service.registry = SimpleNamespace(
        list_rules=lambda: [
            VerificationRuleDefinition(
                "VR-TEC-01", "Solution exists", "technical", Severity.CRITICAL, technical=True
            ),
            VerificationRuleDefinition(
                "VR-TEC-02",
                "Knowledge version exists",
                "technical",
                Severity.CRITICAL,
                technical=True,
            ),
            VerificationRuleDefinition(
                "VR-TEC-03", "Full basis package exists", "technical", Severity.CRITICAL, technical=True
            ),
            VerificationRuleDefinition(
                "VR-TEC-04", "Protocol contains basis documents", "technical", Severity.CRITICAL, technical=True
            ),
            VerificationRuleDefinition(
                "VR-NRM-01", "Solution does not contradict ODA / IG1242", "normative", Severity.MAJOR
            ),
            VerificationRuleDefinition(
                "VR-NRM-02", "ArchiMate alignment", "normative", Severity.MAJOR
            ),
            VerificationRuleDefinition(
                "VR-NRM-03", "Technology standard alignment", "normative", Severity.MAJOR
            ),
        ]
    )

    rules = service._select_rules(
        "full",
        document_scope={
            "mode": "selected",
            "selected_documents": [
                {
                    "document_id": "doc-ig1242",
                    "title": "IG1242 / ODA Component Inventory",
                    "role_code": "ig1242_oda_component_inventory",
                }
            ],
        },
    )

    assert [rule.code for rule in rules] == ["VR-TEC-01", "VR-TEC-02", "VR-TEC-04", "VR-NRM-01"]


def test_selected_operating_system_standard_keeps_technology_rule() -> None:
    rule_codes = VerificationRunService._selected_document_rule_codes(
        {
            "mode": "selected",
            "selected_documents": [
                {
                    "document_id": "doc-os",
                    "title": "Стандарт по операционным системам",
                    "role_code": "reference_only",
                    "document_type": "normative",
                }
            ],
        }
    )

    assert "VR-NRM-03" in rule_codes


def test_full_document_scope_filters_normative_rules_by_effective_documents() -> None:
    service = VerificationRunService.__new__(VerificationRunService)
    service.registry = SimpleNamespace(
        list_rules=lambda: [
            VerificationRuleDefinition(
                "VR-STR-01", "Goal is reflected", "structure", Severity.MAJOR
            ),
            VerificationRuleDefinition(
                "VR-NRM-01", "ODA alignment", "normative", Severity.MAJOR
            ),
            VerificationRuleDefinition(
                "VR-NRM-02", "ArchiMate alignment", "normative", Severity.MAJOR
            ),
            VerificationRuleDefinition(
                "VR-NRM-03", "Technology radar alignment", "normative", Severity.MAJOR
            ),
            VerificationRuleDefinition(
                "VR-NRM-05", "Allowed ArchiMate elements", "normative", Severity.CRITICAL
            ),
        ]
    )

    rules = service._select_rules(
        "full",
        document_scope={
            "mode": "full",
            "effective_documents": [
                {
                    "document_id": "doc-radar",
                    "title": "Технологический радар",
                    "role_code": "technology_standard",
                    "document_type": "technology",
                }
            ],
        },
    )

    assert [rule.code for rule in rules] == ["VR-NRM-03"]


def test_prepare_verification_context_adds_technology_rule_from_selected_content() -> None:
    selected_scope = {
        "mode": "selected",
        "selected_document_ids": ["doc-os"],
        "selected_documents": [
            {
                "document_id": "doc-os",
                "title": "1003161951_6c9ab113595e4f9bb68b447c0c469010-280526-1616-142.pdf",
                "role_code": "reference_only",
                "document_type": "other",
            }
        ],
    }
    technical_rule = VerificationRuleDefinition(
        "VR-TEC-01",
        "Solution is published and ready for verification",
        "technical",
        Severity.CRITICAL,
    )
    technology_rule = VerificationRuleDefinition(
        "VR-NRM-03",
        "Technology choice follows selected technology standard",
        "normative",
        Severity.MAJOR,
    )
    captured: dict[str, object] = {}
    service = VerificationRunService.__new__(VerificationRunService)
    service.registry = SimpleNamespace(
        list_rules=lambda: [technical_rule, technology_rule]
    )
    service._get_knowledge_version = lambda version_id: SimpleNamespace(
        knowledge_version_id=version_id,
        version_documents=[],
    )
    service._get_rule_lookup = lambda version_ids: {}
    service._select_rules = lambda validation_scope, *, document_scope=None: (
        captured.update(
            {
                "validation_scope": validation_scope,
                "document_scope": document_scope,
            }
        )
        or [technical_rule]
    )
    service._build_rule_support_context = lambda **kwargs: {
        "required_fragments_by_role": {
            "technology_standard": [
                SimpleNamespace(
                    fragment_id="fragment-os-standard",
                    content="Ubuntu 20.04 LTS Запрещено",
                )
            ]
        },
        "support_summary": {"document_scope": "selected"},
    }
    run = SimpleNamespace(
        scope_snapshot={
            "validation_scope": "full",
            "knowledge_version_ids": ["kv-1"],
            "document_scope": selected_scope,
        },
        knowledge_version_id="kv-1",
    )
    solution = SimpleNamespace(generation_run=SimpleNamespace(knowledge_version=None))

    _, _, _, rules, rule_groups, _, selected_document_ids = _prepare_verification_context(
        service,
        run=run,
        solution=solution,
    )

    assert captured["document_scope"] == selected_scope
    assert selected_document_ids == ["doc-os"]
    assert [rule.code for rule in rules] == ["VR-TEC-01", "VR-NRM-03"]
    assert rule_groups == ["normative", "technical"]


def test_selected_document_content_hints_cover_bad_metadata() -> None:
    fragments = [
        SimpleNamespace(
            fragment_id="fragment-archimate",
            title="Файл без нормального названия",
            content="ArchiMate 3.2 metamodel. Разрешенные элементы ArchiMate для разделов архитектуры.",
        ),
        SimpleNamespace(
            fragment_id="fragment-nfr",
            title="another-random-file.pdf",
            content=(
                "TOGAF technology architecture: integration API traceability, "
                "security, availability, performance, monitoring, backup."
            ),
        ),
    ]

    rule_codes, role_fragments_by_role = _infer_selected_document_content_hints(fragments)

    assert {"VR-NRM-02", "VR-NRM-05", "VR-NRM-06"}.issubset(rule_codes)
    assert {"VR-STR-06", "VR-CNS-01", "VR-CNS-02", "VR-NFR-01", "VR-NFR-05"}.issubset(
        rule_codes
    )
    assert role_fragments_by_role["archimate_3_2"] == [fragments[0]]


def test_prepare_verification_context_adds_rules_from_selected_content_hints() -> None:
    selected_scope = {
        "mode": "selected",
        "selected_document_ids": ["doc-random"],
        "selected_documents": [
            {
                "document_id": "doc-random",
                "title": "random-upload.pdf",
                "role_code": "reference_only",
                "document_type": "other",
            }
        ],
    }
    technical_rule = VerificationRuleDefinition(
        "VR-TEC-01",
        "Solution is published and ready for verification",
        "technical",
        Severity.CRITICAL,
    )
    archimate_rule = VerificationRuleDefinition(
        "VR-NRM-02",
        "ArchiMate alignment",
        "normative",
        Severity.MAJOR,
    )
    nfr_rule = VerificationRuleDefinition(
        "VR-NFR-04",
        "Monitoring is reflected in the solution",
        "nfr",
        Severity.MAJOR,
    )
    service = VerificationRunService.__new__(VerificationRunService)
    service.registry = SimpleNamespace(
        list_rules=lambda: [technical_rule, archimate_rule, nfr_rule]
    )
    service._get_knowledge_version = lambda version_id: SimpleNamespace(
        knowledge_version_id=version_id,
        version_documents=[],
    )
    service._get_rule_lookup = lambda version_ids: {}
    service._select_rules = lambda validation_scope, *, document_scope=None: [technical_rule]
    service._build_rule_support_context = lambda **kwargs: {
        "required_fragments_by_role": {},
        "content_rule_codes": ["VR-NRM-02", "VR-NFR-04"],
        "support_summary": {"document_scope": "selected"},
    }
    run = SimpleNamespace(
        scope_snapshot={
            "validation_scope": "full",
            "knowledge_version_ids": ["kv-1"],
            "document_scope": selected_scope,
        },
        knowledge_version_id="kv-1",
    )
    solution = SimpleNamespace(generation_run=SimpleNamespace(knowledge_version=None))

    _, _, _, rules, rule_groups, _, selected_document_ids = _prepare_verification_context(
        service,
        run=run,
        solution=solution,
    )

    assert selected_document_ids == ["doc-random"]
    assert [rule.code for rule in rules] == ["VR-TEC-01", "VR-NRM-02", "VR-NFR-04"]
    assert rule_groups == ["nfr", "normative", "technical"]


def test_prepare_verification_context_applies_selected_document_scope_to_rules() -> None:
    selected_scope = {
        "mode": "selected",
        "selected_document_ids": ["doc-ig1242"],
        "selected_documents": [
            {
                "document_id": "doc-ig1242",
                "title": "IG1242 / ODA Component Inventory",
                "role_code": "ig1242_oda_component_inventory",
            }
        ],
    }
    captured: dict[str, object] = {}
    service = VerificationRunService.__new__(VerificationRunService)
    service._get_knowledge_version = lambda version_id: SimpleNamespace(
        knowledge_version_id=version_id,
        version_documents=[],
    )
    service._get_rule_lookup = lambda version_ids: {}
    service._select_rules = lambda validation_scope, *, document_scope=None: (
        captured.update(
            {
                "validation_scope": validation_scope,
                "document_scope": document_scope,
            }
        )
        or [
            VerificationRuleDefinition(
                "VR-NRM-01",
                "Solution does not contradict ODA / IG1242",
                "normative",
                Severity.MAJOR,
            )
        ]
    )
    service._build_rule_support_context = lambda **kwargs: {
        "support_summary": {
            "document_scope": "selected",
            "selected_document_count": len(kwargs["selected_document_ids"]),
        }
    }
    run = SimpleNamespace(
        scope_snapshot={
            "validation_scope": "full",
            "knowledge_version_ids": ["kv-1"],
            "document_scope": selected_scope,
        },
        knowledge_version_id="kv-1",
    )
    solution = SimpleNamespace(generation_run=SimpleNamespace(knowledge_version=None))

    _, _, _, rules, _, _, selected_document_ids = _prepare_verification_context(
        service,
        run=run,
        solution=solution,
    )

    assert captured["validation_scope"] == "full"
    assert captured["document_scope"] == selected_scope
    assert [rule.code for rule in rules] == ["VR-NRM-01"]
    assert selected_document_ids == ["doc-ig1242"]
