from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.architecture import (
    REQUIRED_TOGAF_SECTION_CODES,
    assess_section_readiness,
    build_section_fallback_body,
    derive_structured_architecture_model,
    infer_knowledge_guidance,
    normalize_architecture_boundary_type,
    normalize_togaf_section_code,
    render_togaf_heading,
    section_allowed_archimate_elements,
    section_generation_plan_records,
    summarize_guidance_by_section,
    validate_archimate_alignment,
)


def test_required_togaf_sections_are_canonical_and_ordered() -> None:
    assert REQUIRED_TOGAF_SECTION_CODES == [
        "general_information",
        "business_tasks_description",
        "it_architecture_content",
        "business_architecture",
        "data_architecture",
        "application_architecture",
        "technology_architecture",
        "additional_information",
    ]


def test_normalize_togaf_section_code_maps_legacy_aliases_to_canonical_codes() -> None:
    assert normalize_togaf_section_code("overview") == "general_information"
    assert normalize_togaf_section_code("components") == "application_architecture"
    assert normalize_togaf_section_code("integrations") == "data_architecture"
    assert normalize_togaf_section_code("технологическая архитектура") == "technology_architecture"


def test_normalize_architecture_boundary_type_maps_layer_aliases() -> None:
    assert normalize_architecture_boundary_type("business") == "business_architecture"
    assert normalize_architecture_boundary_type("components") == "application_architecture"
    assert normalize_architecture_boundary_type("technical") == "technology_architecture"
    assert normalize_architecture_boundary_type("unknown_layer") is None


def test_render_togaf_heading_and_section_whitelist() -> None:
    assert render_togaf_heading("general_information") == "1. Общие сведения"
    assert render_togaf_heading("business_architecture") == "3.1 Бизнес-архитектура"
    application_titles = {
        item.title for item in section_allowed_archimate_elements("application_architecture")
    }
    assert "Application Component" in application_titles
    assert "Data Object" in application_titles


@pytest.mark.parametrize(
    ("section_code", "text", "expected_disallowed"),
    [
        (
            "business_architecture",
            "Business Actor инициирует Business Process и Business Service.",
            [],
        ),
        (
            "business_architecture",
            "Business Actor использует Application Component.",
            ["application_component"],
        ),
        ("technology_architecture", "Node размещает Artifact и Technology Service.", []),
        ("technology_architecture", "Node хранит Data Object.", ["data_object"]),
    ],
)
def test_validate_archimate_alignment_detects_cross_layer_elements(
    section_code: str,
    text: str,
    expected_disallowed: list[str],
) -> None:
    result = validate_archimate_alignment(section_code, text)
    assert result["disallowed_element_codes"] == expected_disallowed
    assert result["has_allowed_content"] is True


def test_validate_archimate_alignment_accepts_plural_business_terms() -> None:
    result = validate_archimate_alignment(
        "business_architecture",
        "The section describes business processes, business roles, and business services.",
    )

    assert result["has_allowed_content"] is True
    assert result["disallowed_element_codes"] == []


def test_section_generation_plan_and_readiness_cover_all_sections() -> None:
    plan = section_generation_plan_records()
    assert [item["section_code"] for item in plan] == REQUIRED_TOGAF_SECTION_CODES
    readiness = assess_section_readiness(
        "application_architecture",
        task_text="Нужно реализовать сервис с API и backend компонентами для обмена данными.",
        context_items=[
            "Есть действующий REST API и backend service",
            "Нужно выделить application components",
        ],
        knowledge_fragments=[],
        section_body="Application Component публикует Application Service через Application Interface.",
    )
    assert readiness["status"] in {"ready", "partial"}
    assert isinstance(readiness["allowed_archimate_elements"], list)
    assert readiness["observed_signal_count"] >= 1


def test_fallback_body_mentions_allowed_archimate_objects() -> None:
    body = build_section_fallback_body(
        "technology_architecture",
        task_title="Платформа обработки заявок",
        task_text="Нужно описать инфраструктурный контур и эксплуатационные ограничения.",
        context_items=["Используются контейнеры и managed database"],
        knowledge_fragments=[],
    )
    assert "Node" in body
    assert "Technology Service" in body or "System Software" in body
    assert len(body) > 120


def test_structured_model_is_derived_from_payload() -> None:
    payload = SimpleNamespace(
        sections=[
            SimpleNamespace(
                section_code="general_information",
                title="Общие сведения",
                body_markdown="Контекст решения и границы.",
            ),
            SimpleNamespace(
                section_code="business_tasks_description",
                title="Описание бизнес-задач",
                body_markdown="Цель и ожидаемый эффект.",
            ),
            SimpleNamespace(
                section_code="it_architecture_content",
                title="Содержание ИТ-архитектуры",
                body_markdown="Сводная архитектурная картина.",
            ),
            SimpleNamespace(
                section_code="business_architecture",
                title="Бизнес-архитектура",
                body_markdown="Business Actor выполняет Business Process и предоставляет Business Service.",
            ),
            SimpleNamespace(
                section_code="data_architecture",
                title="Архитектура данных",
                body_markdown="Data Object поступает от source и используется consumer.",
            ),
            SimpleNamespace(
                section_code="application_architecture",
                title="Архитектура приложений",
                body_markdown="Application Component предоставляет Application Service через Application Interface.",
            ),
            SimpleNamespace(
                section_code="technology_architecture",
                title="Технологическая архитектура",
                body_markdown="Node размещает System Software и предоставляет Technology Service.",
            ),
            SimpleNamespace(
                section_code="additional_information",
                title="Дополнительные сведения",
                body_markdown="Риски, ограничения и дальнейшие шаги.",
            ),
        ],
        components=[
            SimpleNamespace(
                component_name="Workflow Service",
                role_description="Application Component реализует прикладную логику сервиса.",
                boundary_type="application_architecture",
                external_flag=False,
                technology_stack="Python, FastAPI",
            ),
            SimpleNamespace(
                component_name="Runtime Cluster",
                role_description="Node предоставляет среду исполнения и Technology Service.",
                boundary_type="technology_architecture",
                external_flag=False,
                technology_stack="Kubernetes",
            ),
        ],
        integrations=[
            SimpleNamespace(
                from_component="Workflow Service",
                to_component="Runtime Cluster",
                interaction="Развёртывание и управление выполнением",
                protocol="HTTPS",
                rationale="Сервис использует платформу исполнения",
            ),
        ],
    )
    model = derive_structured_architecture_model(payload)
    assert model["diagnostics"]["component_entity_count"] == 2
    assert model["diagnostics"]["relation_count"] == 1
    assert any(
        entity["archimate_element_code"] == "application_component" for entity in model["entities"]
    )


def test_verification_rule_registry_source_contains_epic4_rules() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "integrations" / "verification" / "rule_registry.py"
    )
    content = source.read_text(encoding="utf-8")
    for code in {
        "VR-STR-06",
        "VR-STR-07",
        "VR-NRM-05",
        "VR-NRM-06",
        "VR-CNS-03",
        "VR-CNS-04",
        "VR-CNS-05",
        "VR-CNS-06",
    }:
        assert code in content


def test_knowledge_guidance_tags_methodology_and_sections() -> None:
    guidance = infer_knowledge_guidance(
        title="TOGAF and ArchiMate section mapping",
        uri="repository://guides/togaf-archimate.md",
        document_type="normative",
        text="Business architecture and application architecture must follow the ArchiMate metamodel.",
        role_code="methodology",
    )
    assert guidance["knowledge_kind"] == "methodology"
    assert guidance["methodology_flag"] is True
    assert "business_architecture" in guidance["section_tags"]
    assert "application_architecture" in guidance["section_tags"]


def test_guidance_summary_aggregates_titles_by_section() -> None:
    fragments = [
        {
            "metadata": {
                "section_tags": ["business_architecture"],
                "knowledge_kind": "methodology",
                "methodology_flag": True,
                "document_title": "TOGAF Structure Guide",
            }
        },
        {
            "metadata": {
                "section_tags": ["business_architecture", "application_architecture"],
                "knowledge_kind": "architecture_reference",
                "document_title": "Architecture Baseline",
            }
        },
    ]
    summary = summarize_guidance_by_section(fragments)
    assert summary["business_architecture"]["fragment_count"] == 2
    assert summary["business_architecture"]["methodology_fragment_count"] == 1
    assert "TOGAF Structure Guide" in summary["business_architecture"]["document_titles"]
    assert summary["application_architecture"]["fragment_count"] == 1
