from __future__ import annotations

from typing import Any

from .standards import REQUIRED_TOGAF_SECTION_CODES, normalize_architecture_boundary_type

_SECTION_HINTS: dict[str, tuple[str, ...]] = {
    "general_information": (
        "overview",
        "context",
        "scope",
        "общие сведения",
        "контекст",
        "границы",
    ),
    "business_tasks_description": (
        "business task",
        "goal",
        "requirements",
        "описание бизнес-задач",
        "цель",
        "требован",
    ),
    "it_architecture_content": (
        "architecture",
        "solution structure",
        "traceability",
        "архитектура",
        "структура решения",
    ),
    "business_architecture": (
        "business architecture",
        "business layer",
        "business process",
        "бизнес-архитектура",
        "бизнес процесс",
    ),
    "data_architecture": (
        "data architecture",
        "data object",
        "integration",
        "архитектура данных",
        "данн",
        "интеграц",
    ),
    "application_architecture": (
        "application architecture",
        "application service",
        "component",
        "архитектура приложений",
        "компонент",
        "api",
    ),
    "technology_architecture": (
        "technology architecture",
        "technology service",
        "node",
        "deployment",
        "технологическая архитектура",
        "инфраструктур",
    ),
    "additional_information": (
        "risk",
        "constraint",
        "assumption",
        "roadmap",
        "огранич",
        "риск",
        "допущен",
    ),
}

_METHODOLOGY_MARKERS = (
    "togaf",
    "archimate",
    "metamodel",
    "метамодел",
    "architecture principle",
    "framework",
    "template",
    "шаблон",
    "traceability",
    "solution structure",
)

_TECHNOLOGY_MARKERS = (
    "postgres",
    "redis",
    "kubernetes",
    "docker",
    "fastapi",
    "runtime",
    "infrastructure",
)


def _normalize_text(*values: object) -> str:
    parts: list[str] = []
    for value in values:
        if value is None:
            continue
        cleaned = " ".join(str(value).strip().split())
        if cleaned:
            parts.append(cleaned.casefold())
    return " \n".join(parts)


def infer_knowledge_guidance(
    *,
    title: str | None,
    uri: str | None,
    document_type: str | None,
    text: str | None,
    role_code: str | None = None,
) -> dict[str, Any]:
    normalized = _normalize_text(title, uri, document_type, text, role_code)
    section_tags: list[str] = []
    for section_code in REQUIRED_TOGAF_SECTION_CODES:
        if any(marker in normalized for marker in _SECTION_HINTS.get(section_code, ())):
            section_tags.append(section_code)

    methodology_flag = any(marker in normalized for marker in _METHODOLOGY_MARKERS)
    technology_flag = any(marker in normalized for marker in _TECHNOLOGY_MARKERS)
    if document_type == "technology":
        technology_flag = True
    if document_type == "normative":
        methodology_flag = True

    knowledge_kind = "domain"
    if methodology_flag:
        knowledge_kind = "methodology"
    elif technology_flag:
        knowledge_kind = "technology"
    elif document_type == "api":
        knowledge_kind = "integration_reference"
    elif document_type == "architecture":
        knowledge_kind = "architecture_reference"

    architecture_layers = sorted(
        {
            boundary
            for boundary in (normalize_architecture_boundary_type(tag) for tag in section_tags)
            if boundary is not None
        }
    )

    return {
        "section_tags": section_tags,
        "architecture_layers": architecture_layers,
        "knowledge_kind": knowledge_kind,
        "methodology_flag": methodology_flag,
        "technology_flag": technology_flag,
    }


def summarize_guidance_by_section(fragments: list[Any]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {
        code: {
            "fragment_count": 0,
            "methodology_fragment_count": 0,
            "document_titles": [],
            "knowledge_kinds": {},
        }
        for code in REQUIRED_TOGAF_SECTION_CODES
    }
    for item in fragments:
        metadata = (
            dict(getattr(item, "metadata", {}) or {})
            if not isinstance(item, dict)
            else dict(item.get("metadata") or {})
        )
        tags = list(metadata.get("section_tags") or [])
        knowledge_kind = str(metadata.get("knowledge_kind") or "domain")
        title = str(
            metadata.get("document_title")
            or metadata.get("title")
            or getattr(item, "title", "")
            or ""
        ).strip()
        for section_code in tags:
            if section_code not in summary:
                continue
            bucket = summary[section_code]
            bucket["fragment_count"] += 1
            if metadata.get("methodology_flag"):
                bucket["methodology_fragment_count"] += 1
            kinds = dict(bucket["knowledge_kinds"])
            kinds[knowledge_kind] = int(kinds.get(knowledge_kind, 0)) + 1
            bucket["knowledge_kinds"] = dict(sorted(kinds.items()))
            titles = list(bucket["document_titles"])
            if title and title not in titles:
                titles.append(title)
            bucket["document_titles"] = titles[:5]
    return summary
