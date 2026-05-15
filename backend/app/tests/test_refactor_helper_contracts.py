from __future__ import annotations

from types import SimpleNamespace

from app.db.enums import CheckResultStatus, ProtocolSummaryStatus, Severity
from app.domain.services.canonical_read_helpers import (
    extract_knowledge_scope,
    group_verification_findings,
)
from app.domain.services.knowledge.update_diffing import (
    build_version_diff_summary,
    classify_document_error_code,
)
from app.domain.services.verification.common import VerificationExecutionContext
from app.domain.services.verification.rule_engine import VerificationRuleEngine
from app.integrations.generation.payload_normalization import _validate_generation_solution_payload
from app.integrations.verification import VerificationCheckResultPayload, VerificationRuleDefinition


class _PassingExecutor:
    def execute(self, *, rule, context, support):
        return VerificationCheckResultPayload(
            rule_code=rule.code,
            check_name=rule.name,
            rule_group=rule.group,
            status=CheckResultStatus.PASSED,
            severity=rule.default_severity,
            evidence_ref="evidence:ok",
            diagnostics={"support_sections": sorted(support.section_codes)},
            is_technical_check=rule.technical,
        )


def test_generation_payload_normalization_still_synthesizes_required_sections() -> None:
    payload = _validate_generation_solution_payload(
        {
            "solution_title": "Approval service",
            "executive_summary": "Need an architecture solution for approval workflow.",
            "components": ["Approval API"],
            "integrations": [
                {
                    "from_component": "Approval API",
                    "to_component": "ERP",
                    "interaction": "submits approval event",
                    "protocol": "REST",
                }
            ],
            "assumptions": ["ERP API already exists"],
            "risks": ["Manual reconciliation may remain"],
        }
    )

    section_codes = {section.section_code for section in payload.sections}
    assert "general_information" in section_codes
    assert "application_architecture" in section_codes
    assert "additional_information" in section_codes
    assert payload.components[0].component_name == "Approval API"
    assert payload.integrations[0].protocol == "REST"


def test_update_diff_summary_tracks_added_removed_and_changed_documents() -> None:
    active = SimpleNamespace(
        knowledge_version_id="kv-active",
        version_no="KV-ACTIVE",
        summary={
            "validation": {"score": 0.8},
            "missing_required_packages": ["oda"],
            "required_source_failures": [],
        },
        version_documents=[
            SimpleNamespace(
                document=SimpleNamespace(document_id="doc-1", checksum="a"),
                role_code="oda",
                required_flag=True,
            ),
            SimpleNamespace(
                document=SimpleNamespace(document_id="doc-2", checksum="b"),
                role_code="archimate",
                required_flag=False,
            ),
        ],
    )
    candidate = SimpleNamespace(
        knowledge_version_id="kv-candidate",
        version_no="KV-CANDIDATE",
        summary={
            "validation": {"score": 0.95},
            "missing_required_packages": [],
            "required_source_failures": ["source-1"],
        },
        version_documents=[
            SimpleNamespace(
                document=SimpleNamespace(document_id="doc-1", checksum="changed"),
                role_code="oda",
                required_flag=True,
            ),
            SimpleNamespace(
                document=SimpleNamespace(document_id="doc-3", checksum="c"),
                role_code="technology_standard",
                required_flag=False,
            ),
        ],
    )

    summary = build_version_diff_summary(candidate, active)

    assert summary is not None
    assert summary["added_document_ids"] == ["doc-3"]
    assert summary["removed_document_ids"] == ["doc-2"]
    assert summary["changed_document_ids"] == ["doc-1"]
    assert (
        classify_document_error_code("Document size exceeds allowed limit", default="GENERIC")
        == "DOCUMENT_SIZE_LIMIT_EXCEEDED"
    )


def test_canonical_helpers_preserve_knowledge_scope_and_group_findings() -> None:
    scope = extract_knowledge_scope(
        {"knowledge_version_id": "kv-1", "knowledge_version_ids": ["kv-1", "kv-2"]}
    )
    grouped = group_verification_findings(
        [
            {"rule_group": "structure", "id": 1},
            {"rule_group": "structure", "id": 2},
            {"rule_group": "normative", "id": 3},
        ]
    )

    assert scope == {
        "selected_generation_version_id": "kv-1",
        "effective_version_ids": ["kv-1", "kv-2"],
    }
    assert [item["id"] for item in grouped["structure"]] == [1, 2]
    assert [item["id"] for item in grouped["normative"]] == [3]


def test_verification_rule_engine_accepts_injected_executors() -> None:
    engine = VerificationRuleEngine(executors={"technical": _PassingExecutor()})
    context = VerificationExecutionContext(
        solution=SimpleNamespace(
            sections=[],
            list_items=[],
            components=[],
            integrations=[],
            risks=[],
            executive_summary="Summary",
            generation_run=None,
        ),
        run=SimpleNamespace(knowledge_version=SimpleNamespace(version_documents=[])),
        rules=[
            VerificationRuleDefinition(
                "VR-TEC-01", "Synthetic rule", "technical", Severity.CRITICAL, technical=True
            )
        ],
        rule_lookup={},
    )

    payload = engine.execute(context)

    assert payload.final_status == ProtocolSummaryStatus.PASSED
    assert payload.check_results[0].status == CheckResultStatus.PASSED
