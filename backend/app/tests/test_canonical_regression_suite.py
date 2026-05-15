from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.architecture import (
    REQUIRED_TOGAF_SECTION_CODES,
    assess_section_readiness,
    derive_structured_architecture_model,
    validate_archimate_alignment,
)
from app.integrations.generation.contracts import GenerationSolutionPayload
from app.integrations.knowledge.retrieval_policies import RetrievalPolicyRegistry
from app.integrations.verification.rule_registry import VerificationRuleRegistry

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "architecture_regression_cases.json"


def _load_cases() -> list[dict]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return list(payload["cases"])


def _sections_by_code(case: dict) -> dict[str, dict]:
    return {section["section_code"]: section for section in case["payload"]["sections"]}


def test_project_uses_new_version_only_assets() -> None:
    prompt_v2 = Path(__file__).resolve().parents[1] / "templates" / "prompts" / "generation.v2.json"
    assert not prompt_v2.exists()
    assert (
        RetrievalPolicyRegistry.get("generation").policy_id
        == "generation_retrieval_policy_togaf_archimate_v1"
    )
    assert (
        RetrievalPolicyRegistry.get("verification").policy_id
        == "verification_retrieval_policy_togaf_archimate_v1"
    )


@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: case["case_id"])
def test_regression_cases_capture_canonical_or_rejected_structure(case: dict) -> None:
    section_codes = [section["section_code"] for section in case["payload"]["sections"]]
    if case["expect_validation"] == "fail":
        assert section_codes != REQUIRED_TOGAF_SECTION_CODES
        assert any(code not in REQUIRED_TOGAF_SECTION_CODES for code in section_codes)
        return
    assert section_codes == REQUIRED_TOGAF_SECTION_CODES


def test_rulebook_version_is_new_canonical_registry() -> None:
    registry = VerificationRuleRegistry()
    assert registry.version == "mvp-v4-sectioned-togaf-archimate"
    assert {rule.code for rule in registry.list_rules()} >= {"VR-STR-06", "VR-NRM-05", "VR-CNS-06"}


def test_source_code_enforces_canonical_only_section_mode() -> None:
    contracts_source = (
        Path(__file__).resolve().parents[1] / "integrations" / "generation" / "contracts.py"
    ).read_text(encoding="utf-8")
    normalizer_source = (
        Path(__file__).resolve().parents[1]
        / "integrations"
        / "generation"
        / "payload_normalization_sections.py"
    ).read_text(encoding="utf-8")
    validator_source = (
        Path(__file__).resolve().parents[1] / "domain" / "services" / "generation_core.py"
    ).read_text(encoding="utf-8")
    assert "unexpected sections are not allowed in canonical TOGAF mode" in contracts_source
    assert "Unexpected sections are not allowed in canonical TOGAF mode" in validator_source
    assert (
        "final_codes = [code for code in REQUIRED_SECTION_CODES if code in merged_by_code]"
        in normalizer_source
    )


@pytest.mark.parametrize(
    "case",
    [item for item in _load_cases() if item["expect_validation"] == "pass"],
    ids=lambda case: case["case_id"],
)
def test_generation_payload_and_structured_model_are_canonical(case: dict) -> None:
    payload = GenerationSolutionPayload.model_validate(case["payload"])
    structured_model = derive_structured_architecture_model(payload)

    assert [section.section_code for section in payload.sections] == REQUIRED_TOGAF_SECTION_CODES
    assert structured_model["diagnostics"]["component_entity_count"] == len(payload.components)
    assert structured_model["diagnostics"]["section_entity_count"] == 8
    assert structured_model["diagnostics"]["entity_count"] == len(payload.components) + 8
    assert structured_model["diagnostics"]["relation_count"] == len(payload.integrations)
    assert len(structured_model["section_summaries"]) == 8


@pytest.mark.parametrize(
    "case",
    [item for item in _load_cases() if item["expect_validation"] == "pass"],
    ids=lambda case: case["case_id"],
)
def test_archimate_alignment_matches_regression_expectations(case: dict) -> None:
    sections = _sections_by_code(case)
    expected_rule_statuses = case.get("expected_rule_statuses", {})
    for section_code in [
        "business_architecture",
        "data_architecture",
        "application_architecture",
        "technology_architecture",
    ]:
        alignment = validate_archimate_alignment(
            section_code, sections[section_code]["body_markdown"]
        )
        assert alignment["disallowed_element_codes"] == []
        assert alignment["has_allowed_content"] is True
    if expected_rule_statuses.get("VR-CNS-05") == "warning":
        data_text = sections["data_architecture"]["body_markdown"].lower()
        assert "data object" in data_text
        assert "source" not in data_text or "consumer" not in data_text
    if expected_rule_statuses.get("VR-CNS-05") == "passed":
        data_text = sections["data_architecture"]["body_markdown"].lower()
        assert "source" in data_text and "consumer" in data_text


@pytest.mark.parametrize(
    "case",
    [item for item in _load_cases() if item["expect_validation"] == "pass"],
    ids=lambda case: case["case_id"],
)
def test_section_readiness_regression_suite(case: dict) -> None:
    sections = _sections_by_code(case)
    context_items = [
        "Нужны TOGAF-структура, ArchiMate 3.2 и трассируемость до архитектурных решений.",
        "Документ должен быть пригоден для последующей экспертной проверки.",
    ]
    narrative_sections = {
        "general_information",
        "business_tasks_description",
        "it_architecture_content",
    }
    for section_code in REQUIRED_TOGAF_SECTION_CODES:
        readiness = assess_section_readiness(
            section_code,
            task_text=case["task_text"],
            context_items=context_items,
            knowledge_fragments=[],
            section_body=sections[section_code]["body_markdown"],
        )
        if section_code in narrative_sections:
            assert readiness["observed_signal_count"] >= 1
        else:
            assert readiness["status"] in {"ready", "partial"}
            assert readiness["observed_signal_count"] >= 2


def test_noncanonical_sections_are_rejected_by_payload_contract() -> None:
    case = next(
        item for item in _load_cases() if item["case_id"] == "noncanonical_sections_are_rejected"
    )
    with pytest.raises(
        ValueError, match="unexpected sections are not allowed in canonical TOGAF mode"
    ):
        GenerationSolutionPayload.model_validate(case["payload"])
