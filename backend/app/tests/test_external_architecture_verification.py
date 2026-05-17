from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.exceptions import ConflictError
from app.db.enums import BusinessTaskStatus, CheckResultStatus, ProtocolSummaryStatus, Severity
from app.domain.services.external_architecture_check import ExternalArchitectureCheckService
from app.domain.services.verification.post_validation import VerificationPostValidator
from app.domain.services.verification.run_service import VerificationRunService
from app.domain.services.verification.runtime import _prepare_verification_context
from app.domain.services.verification.rule_executors import (
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
