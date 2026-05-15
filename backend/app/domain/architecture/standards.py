from __future__ import annotations

from dataclasses import dataclass
from typing import Final


def _clean(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned or None


def _token(value: str) -> str:
    normalized = "".join(char if char.isalnum() else "_" for char in value.casefold())
    return "_".join(part for part in normalized.split("_") if part)


@dataclass(frozen=True, slots=True)
class TogafSectionDefinition:
    code: str
    number: str
    title: str
    level: int = 1
    required: bool = True


@dataclass(frozen=True, slots=True)
class ArchiMateElementDefinition:
    code: str
    title: str
    layer: str
    aliases: tuple[str, ...]


TOGAF_SECTION_DEFINITIONS: Final[tuple[TogafSectionDefinition, ...]] = (
    TogafSectionDefinition("general_information", "1", "Общие сведения"),
    TogafSectionDefinition("business_tasks_description", "2", "Описание бизнес-задач"),
    TogafSectionDefinition("it_architecture_content", "3", "Содержание ИТ-архитектуры"),
    TogafSectionDefinition("business_architecture", "3.1", "Бизнес-архитектура", level=2),
    TogafSectionDefinition("data_architecture", "3.2", "Архитектура данных", level=2),
    TogafSectionDefinition("application_architecture", "3.3", "Архитектура приложений", level=2),
    TogafSectionDefinition(
        "technology_architecture", "3.4", "Технологическая архитектура", level=2
    ),
    TogafSectionDefinition("additional_information", "4", "Дополнительные сведения"),
)
TOGAF_SECTION_ORDER: Final[dict[str, int]] = {
    item.code: index for index, item in enumerate(TOGAF_SECTION_DEFINITIONS, start=1)
}
TOGAF_SECTION_LOOKUP: Final[dict[str, TogafSectionDefinition]] = {
    item.code: item for item in TOGAF_SECTION_DEFINITIONS
}
REQUIRED_TOGAF_SECTION_CODES: Final[list[str]] = [
    item.code for item in TOGAF_SECTION_DEFINITIONS if item.required
]


_TOGAF_SECTION_ALIASES: Final[dict[str, str]] = {
    # canonical
    "general_information": "general_information",
    "business_tasks_description": "business_tasks_description",
    "it_architecture_content": "it_architecture_content",
    "business_architecture": "business_architecture",
    "data_architecture": "data_architecture",
    "application_architecture": "application_architecture",
    "technology_architecture": "technology_architecture",
    "additional_information": "additional_information",
    # requested russian titles
    "общие_сведения": "general_information",
    "описание_бизнес_задач": "business_tasks_description",
    "содержание_ит_архитектуры": "it_architecture_content",
    "бизнес_архитектура": "business_architecture",
    "архитектура_данных": "data_architecture",
    "архитектура_приложений": "application_architecture",
    "технологическая_архитектура": "technology_architecture",
    "дополнительные_сведения": "additional_information",
    "необходимая_информация": "additional_information",
    "дополнительная_информация": "additional_information",
    # english variants
    "general_info": "general_information",
    "general": "general_information",
    "common_information": "general_information",
    "overview": "general_information",
    "summary": "general_information",
    "executive_summary": "general_information",
    "context": "general_information",
    "business_tasks": "business_tasks_description",
    "business_task": "business_tasks_description",
    "business_problem": "business_tasks_description",
    "business_requirements": "business_tasks_description",
    "task_description": "business_tasks_description",
    "task_scope": "business_tasks_description",
    "it_architecture": "it_architecture_content",
    "architecture_content": "it_architecture_content",
    "architecture": "it_architecture_content",
    "solution_architecture": "it_architecture_content",
    "architectural_design": "it_architecture_content",
    "business_layer": "business_architecture",
    "business_model": "business_architecture",
    "application_layer": "application_architecture",
    "application_model": "application_architecture",
    "components": "application_architecture",
    "component_model": "application_architecture",
    "system_components": "application_architecture",
    "services": "application_architecture",
    "data_layer": "data_architecture",
    "data_model": "data_architecture",
    "data_flows": "data_architecture",
    "integrations": "data_architecture",
    "integration_model": "data_architecture",
    "technology_layer": "technology_architecture",
    "technical_architecture": "technology_architecture",
    "deployment_architecture": "technology_architecture",
    "infrastructure": "technology_architecture",
    "risks": "additional_information",
    "limitations": "additional_information",
    "assumptions": "additional_information",
    "constraints_and_risks": "additional_information",
    "additional": "additional_information",
    "other_information": "additional_information",
}


ARCHIMATE_ELEMENT_DEFINITIONS: Final[tuple[ArchiMateElementDefinition, ...]] = (
    ArchiMateElementDefinition(
        "business_actor",
        "Business Actor",
        "business",
        ("business actor", "business actors", "бизнес-актор", "бизнес актор", "бизнес-акторы", "бизнес акторы"),
    ),
    ArchiMateElementDefinition(
        "business_role",
        "Business Role",
        "business",
        ("business role", "business roles", "бизнес-роль", "бизнес роль", "бизнес-роли", "бизнес роли"),
    ),
    ArchiMateElementDefinition(
        "business_collaboration",
        "Business Collaboration",
        "business",
        ("business collaboration", "бизнес-коллаборация", "бизнес коллаборация"),
    ),
    ArchiMateElementDefinition(
        "business_interface",
        "Business Interface",
        "business",
        ("business interface", "интерфейс бизнеса", "бизнес-интерфейс", "бизнес интерфейс"),
    ),
    ArchiMateElementDefinition(
        "business_process",
        "Business Process",
        "business",
        (
            "business process",
            "business processes",
            "бизнес-процесс",
            "бизнес процесс",
            "бизнес-процессы",
            "бизнес процессы",
        ),
    ),
    ArchiMateElementDefinition(
        "business_function",
        "Business Function",
        "business",
        ("business function", "бизнес-функция", "бизнес функция"),
    ),
    ArchiMateElementDefinition(
        "business_interaction",
        "Business Interaction",
        "business",
        (
            "business interaction",
            "взаимодействие бизнеса",
            "бизнес-взаимодействие",
            "бизнес взаимодействие",
        ),
    ),
    ArchiMateElementDefinition(
        "business_service",
        "Business Service",
        "business",
        ("business service", "business services", "бизнес-сервис", "бизнес сервис", "бизнес-сервисы", "бизнес сервисы"),
    ),
    ArchiMateElementDefinition(
        "business_event",
        "Business Event",
        "business",
        ("business event", "бизнес-событие", "бизнес событие"),
    ),
    ArchiMateElementDefinition(
        "business_object",
        "Business Object",
        "business",
        ("business object", "бизнес-объект", "бизнес объект"),
    ),
    ArchiMateElementDefinition("contract", "Contract", "business", ("contract", "контракт")),
    ArchiMateElementDefinition(
        "representation", "Representation", "business", ("representation", "представление")
    ),
    ArchiMateElementDefinition(
        "data_object",
        "Data Object",
        "data",
        ("data object", "объект данных", "dataset", "data set"),
    ),
    ArchiMateElementDefinition(
        "application_component",
        "Application Component",
        "application",
        (
            "application component",
            "компонент приложения",
            "прикладной компонент",
            "application component",
        ),
    ),
    ArchiMateElementDefinition(
        "application_collaboration",
        "Application Collaboration",
        "application",
        ("application collaboration", "коллаборация приложений", "прикладная коллаборация"),
    ),
    ArchiMateElementDefinition(
        "application_interface",
        "Application Interface",
        "application",
        ("application interface", "интерфейс приложения", "прикладной интерфейс"),
    ),
    ArchiMateElementDefinition(
        "application_function",
        "Application Function",
        "application",
        ("application function", "функция приложения", "прикладная функция"),
    ),
    ArchiMateElementDefinition(
        "application_interaction",
        "Application Interaction",
        "application",
        ("application interaction", "взаимодействие приложений", "прикладное взаимодействие"),
    ),
    ArchiMateElementDefinition(
        "application_service",
        "Application Service",
        "application",
        ("application service", "сервис приложения", "прикладной сервис"),
    ),
    ArchiMateElementDefinition(
        "application_process",
        "Application Process",
        "application",
        ("application process", "процесс приложения", "прикладной процесс"),
    ),
    ArchiMateElementDefinition(
        "application_event",
        "Application Event",
        "application",
        ("application event", "событие приложения", "прикладное событие"),
    ),
    ArchiMateElementDefinition("node", "Node", "technology", ("node", "узел")),
    ArchiMateElementDefinition("device", "Device", "technology", ("device", "устройство")),
    ArchiMateElementDefinition(
        "system_software",
        "System Software",
        "technology",
        ("system software", "системное по", "системное программное обеспечение"),
    ),
    ArchiMateElementDefinition("network", "Network", "technology", ("network", "сеть")),
    ArchiMateElementDefinition(
        "technology_interface",
        "Technology Interface",
        "technology",
        ("technology interface", "технологический интерфейс"),
    ),
    ArchiMateElementDefinition(
        "technology_function",
        "Technology Function",
        "technology",
        ("technology function", "технологическая функция"),
    ),
    ArchiMateElementDefinition(
        "technology_process",
        "Technology Process",
        "technology",
        ("technology process", "технологический процесс"),
    ),
    ArchiMateElementDefinition(
        "technology_interaction",
        "Technology Interaction",
        "technology",
        ("technology interaction", "технологическое взаимодействие"),
    ),
    ArchiMateElementDefinition(
        "technology_service",
        "Technology Service",
        "technology",
        ("technology service", "технологический сервис"),
    ),
    ArchiMateElementDefinition(
        "technology_event",
        "Technology Event",
        "technology",
        ("technology event", "технологическое событие"),
    ),
    ArchiMateElementDefinition("artifact", "Artifact", "technology", ("artifact", "артефакт")),
)
ARCHIMATE_LOOKUP: Final[dict[str, ArchiMateElementDefinition]] = {
    item.code: item for item in ARCHIMATE_ELEMENT_DEFINITIONS
}

SECTION_ARCHIMATE_WHITELIST: Final[dict[str, tuple[str, ...]]] = {
    "general_information": (),
    "business_tasks_description": (),
    "it_architecture_content": (),
    "business_architecture": (
        "business_actor",
        "business_role",
        "business_collaboration",
        "business_interface",
        "business_process",
        "business_function",
        "business_interaction",
        "business_service",
        "business_event",
        "business_object",
        "contract",
        "representation",
    ),
    "data_architecture": (
        "business_object",
        "representation",
        "data_object",
        "application_component",
        "application_interface",
        "application_service",
        "artifact",
    ),
    "application_architecture": (
        "application_component",
        "application_collaboration",
        "application_interface",
        "application_function",
        "application_interaction",
        "application_service",
        "application_process",
        "application_event",
        "data_object",
    ),
    "technology_architecture": (
        "node",
        "device",
        "system_software",
        "network",
        "technology_interface",
        "technology_function",
        "technology_process",
        "technology_interaction",
        "technology_service",
        "technology_event",
        "artifact",
    ),
    "additional_information": (),
}

_BOUNDARY_TYPE_ALIASES: Final[dict[str, str]] = {
    "business": "business_architecture",
    "business_architecture": "business_architecture",
    "business_layer": "business_architecture",
    "data": "data_architecture",
    "data_architecture": "data_architecture",
    "data_layer": "data_architecture",
    "application": "application_architecture",
    "application_architecture": "application_architecture",
    "application_layer": "application_architecture",
    "components": "application_architecture",
    "technology": "technology_architecture",
    "technology_architecture": "technology_architecture",
    "technology_layer": "technology_architecture",
    "technical": "technology_architecture",
    "technical_architecture": "technology_architecture",
    "infrastructure": "technology_architecture",
}


def get_section_definition(code: str) -> TogafSectionDefinition | None:
    return TOGAF_SECTION_LOOKUP.get(code)


def section_number(code: str) -> str | None:
    section = get_section_definition(code)
    return section.number if section is not None else None


def render_togaf_heading(code: str) -> str:
    section = get_section_definition(code)
    if section is None:
        return code.replace("_", " ").title()
    return (
        f"{section.number}. {section.title}"
        if section.level == 1
        else f"{section.number} {section.title}"
    )


def normalize_togaf_section_code(value: object) -> str | object:
    cleaned = _clean(value)
    if not cleaned:
        return value
    normalized = _token(cleaned)
    if normalized in _TOGAF_SECTION_ALIASES:
        return _TOGAF_SECTION_ALIASES[normalized]
    if normalized.endswith("_section"):
        normalized = normalized.removesuffix("_section")
    return _TOGAF_SECTION_ALIASES.get(normalized, normalized)


def normalize_architecture_boundary_type(value: object) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    normalized = _token(cleaned)
    if normalized in _BOUNDARY_TYPE_ALIASES:
        return _BOUNDARY_TYPE_ALIASES[normalized]
    normalized_section = normalize_togaf_section_code(cleaned)
    if isinstance(normalized_section, str) and normalized_section in SECTION_ARCHIMATE_WHITELIST:
        return normalized_section
    return None


def get_archimate_element(code: str) -> ArchiMateElementDefinition | None:
    return ARCHIMATE_LOOKUP.get(code)


def section_allowed_archimate_elements(section_code: str) -> tuple[ArchiMateElementDefinition, ...]:
    return tuple(
        ARCHIMATE_LOOKUP[code]
        for code in SECTION_ARCHIMATE_WHITELIST.get(section_code, ())
        if code in ARCHIMATE_LOOKUP
    )


def _normalize_text_for_match(text: str) -> str:
    lowered = text.casefold()
    translation = str.maketrans(
        {
            "-": " ",
            "/": " ",
            ".": " ",
            ",": " ",
            ":": " ",
            ";": " ",
            "(": " ",
            ")": " ",
            "[": " ",
            "]": " ",
            "{": " ",
            "}": " ",
        }
    )
    return " ".join(lowered.translate(translation).split())


def extract_archimate_elements(text: str | None) -> set[str]:
    if not text:
        return set()
    normalized = f" {_normalize_text_for_match(text)} "
    detected: set[str] = set()
    for element in ARCHIMATE_ELEMENT_DEFINITIONS:
        for alias in element.aliases:
            alias_token = _normalize_text_for_match(alias)
            if f" {alias_token} " in normalized:
                detected.add(element.code)
                break
    return detected


def validate_archimate_alignment(section_code: str, text: str | None) -> dict[str, object]:
    allowed_codes = set(SECTION_ARCHIMATE_WHITELIST.get(section_code, ()))
    detected_codes = extract_archimate_elements(text)
    disallowed_codes = detected_codes - allowed_codes if allowed_codes else set()
    return {
        "section_code": section_code,
        "allowed_element_codes": sorted(allowed_codes),
        "allowed_element_titles": [
            ARCHIMATE_LOOKUP[code].title
            for code in sorted(allowed_codes)
            if code in ARCHIMATE_LOOKUP
        ],
        "detected_element_codes": sorted(detected_codes),
        "detected_element_titles": [
            ARCHIMATE_LOOKUP[code].title
            for code in sorted(detected_codes)
            if code in ARCHIMATE_LOOKUP
        ],
        "disallowed_element_codes": sorted(disallowed_codes),
        "disallowed_element_titles": [
            ARCHIMATE_LOOKUP[code].title
            for code in sorted(disallowed_codes)
            if code in ARCHIMATE_LOOKUP
        ],
        "has_allowed_content": bool(detected_codes & allowed_codes)
        if allowed_codes
        else bool(text and _clean(text)),
    }
