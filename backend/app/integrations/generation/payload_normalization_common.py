from __future__ import annotations

import json
import re
from typing import Any

from app.core.exceptions import ValidationError
from app.domain.architecture import (
    TOGAF_SECTION_DEFINITIONS,
    assess_section_readiness,
    build_section_fallback_body,
    derive_structured_architecture_model,
    normalize_architecture_boundary_type,
    should_apply_section_fallback,
)
from app.integrations.generation.contracts import (
    coerce_generation_risk_severity,
    normalize_generation_section_code,
)

JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
CAMEL_CASE_BOUNDARY_RE = re.compile(r"(?<!^)(?=[A-Z])")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")

GENERATION_ROOT_KEYS = {
    "solution_title",
    "executive_summary",
    "sections",
    "components",
    "integrations",
    "assumptions",
    "next_steps",
    "risks",
    "section_readiness",
    "structured_model",
}


def _sanitize_unconfirmed_architecture_terms(value: Any) -> str | None:
    cleaned = _clean_text_value(value)
    if not cleaned:
        return None
    cleaned = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"\s#{1,6}\s*", " ", cleaned)
    cleaned = re.sub(r"[*_`]+", "", cleaned)
    cleaned = re.sub(
        r"\b(?:amazon\s+s3|aws\s+s3|s3)\b",
        "корпоративное хранилище документов",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\b(?:postgres(?:ql)?|redis)\b",
        lambda match: (
            "корпоративное хранилище данных"
            if match.group(0).casefold().startswith("postgres")
            else "служба кэширования или очередей"
        ),
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\bcloud\b",
        "корпоративный контур",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"облачн\w*\s+хранилищ\w*",
        "корпоративное хранилище",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"облачн\w*",
        "корпоративный",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = cleaned.replace("фонтовой", "фоновой").replace("Фонтовой", "Фоновой")
    return re.sub(r"\s+", " ", cleaned).strip() or None
GENERATION_WRAPPER_KEYS = ("architecture", "solution", "result", "payload")
MULTI_VALUE_SPLIT_RE = re.compile(r"[,;\n]+")
INTEGRATION_ARROW_RE = re.compile(
    r"^(?P<from>.+?)\s*(?:->|→|=>|↔|<->|to)\s*(?P<to>.+?)(?:\s*(?:via|over|using)\s+(?P<protocol>[A-Za-z0-9_./+-]+))?(?:\s*[:\-–—]\s*(?P<interaction>.+))?$",
    re.IGNORECASE,
)

SECTION_TITLE_BY_CODE = {item.code: item.title for item in TOGAF_SECTION_DEFINITIONS}
SECTION_FIELD_ALIASES = {
    "general_information": (
        "general_information",
        "general_info",
        "overview",
        "summary",
        "executive_summary",
        "executive",
        "context",
        "scope",
        "business_context",
        "solution_overview",
        "общие_сведения",
        "обзор",
        "резюме",
        "исполнительное_резюме",
        "контекст",
    ),
    "business_tasks_description": (
        "business_tasks_description",
        "business_tasks",
        "business_task",
        "task_description",
        "business_problem",
        "requirements",
        "описание_бизнес_задач",
        "бизнес_задача",
        "бизнес_требования",
    ),
    "it_architecture_content": (
        "it_architecture_content",
        "it_architecture",
        "architecture_content",
        "architecture",
        "solution_architecture",
        "architectural_design",
        "содержание_ит_архитектуры",
        "архитектура",
        "архитектурное_решение",
    ),
    "business_architecture": (
        "business_architecture",
        "business_layer",
        "business_model",
        "business_domain",
        "бизнес_архитектура",
        "бизнес_слой",
    ),
    "data_architecture": (
        "data_architecture",
        "data_layer",
        "data_model",
        "data_flows",
        "integrations",
        "integration_model",
        "архитектура_данных",
        "данные",
        "интеграции",
        "потоки_данных",
    ),
    "application_architecture": (
        "application_architecture",
        "application_layer",
        "application_model",
        "components",
        "component_model",
        "system_components",
        "services",
        "архитектура_приложений",
        "компоненты",
        "компонентная_модель",
        "сервисы",
    ),
    "technology_architecture": (
        "technology_architecture",
        "technology_layer",
        "technical_architecture",
        "deployment_architecture",
        "infrastructure",
        "технологическая_архитектура",
        "техническая_архитектура",
        "инфраструктура",
    ),
    "additional_information": (
        "additional_information",
        "additional",
        "other_information",
        "risks",
        "limitations",
        "assumptions",
        "constraints_and_risks",
        "дополнительные_сведения",
        "дополнительная_информация",
        "необходимая_информация",
        "риски",
        "ограничения",
    ),
}


def _normalize_bool_like(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return bool(value)
    cleaned = _clean_text_value(value)
    if not cleaned:
        return None
    normalized = _to_snake_case(cleaned)
    if normalized in {"true", "yes", "y", "1", "external", "public", "outside", "third_party"}:
        return True
    if normalized in {
        "false",
        "no",
        "n",
        "0",
        "internal",
        "private",
        "inside",
        "inhouse",
        "in_house",
    }:
        return False
    return None


def _normalize_component_name(name: Any) -> str | None:
    cleaned = _sanitize_unconfirmed_architecture_terms(name)
    if not cleaned:
        return None
    cleaned = re.sub(r"^[\-*•\d.)\s]+", "", cleaned).strip()
    role_match = re.search(
        r"\bроль\s+(.+?)(?:[.;:!?]|$)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if role_match:
        role_name = role_match.group(1).strip(" .,:;!?()[]{}")
        if role_name and len(role_name.split()) <= 5:
            cleaned = role_name
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or None


def _component_name_key(name: Any) -> str:
    cleaned = _normalize_component_name(name) or ""
    normalized = re.sub(r"[^\w]+", "", cleaned.casefold(), flags=re.UNICODE)
    return normalized


def _normalize_section_code_value(value: Any, *, title: Any = None) -> str | None:
    normalized = normalize_generation_section_code(value)
    cleaned = _clean_text_value(normalized) if isinstance(normalized, str) else None
    if cleaned:
        return cleaned
    normalized_title = normalize_generation_section_code(title)
    return _clean_text_value(normalized_title) if isinstance(normalized_title, str) else None


def _parse_integration_string(value: Any) -> dict[str, Any] | None:
    cleaned = _clean_text_value(value)
    if not cleaned:
        return None
    match = INTEGRATION_ARROW_RE.match(cleaned)
    if not match:
        return None
    from_component = _normalize_component_name(match.group("from"))
    to_component = _normalize_component_name(match.group("to"))
    protocol = _clean_text_value(match.group("protocol"))
    interaction = _clean_text_value(match.group("interaction"))
    if not from_component or not to_component:
        return None
    parsed: dict[str, Any] = {
        "from_component": from_component,
        "to_component": to_component,
    }
    if protocol:
        parsed["protocol"] = protocol
    if interaction:
        parsed["interaction"] = interaction
    return parsed


def _extract_json_payload(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        raise ValidationError(
            "LLM response must be a JSON object, not an array", error_code="LLM_OUTPUT_INVALID_JSON"
        )
    if not isinstance(content, str):
        raise ValidationError(
            "LLM response payload is not textual JSON", error_code="LLM_OUTPUT_INVALID_JSON"
        )
    raw = content.strip()
    if not raw:
        raise ValidationError("LLM response is empty", error_code="LLM_OUTPUT_EMPTY")
    candidates = [raw]
    fenced = JSON_BLOCK_RE.search(raw)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if not isinstance(parsed, dict):
                raise ValidationError(
                    "LLM response must be a JSON object", error_code="LLM_OUTPUT_INVALID_JSON"
                )
            return parsed
        except json.JSONDecodeError:
            continue
    raise ValidationError("LLM returned invalid JSON", error_code="LLM_OUTPUT_INVALID_JSON")


def _to_snake_case(value: str) -> str:
    normalized = value.replace("-", "_").replace(" ", "_")
    return CAMEL_CASE_BOUNDARY_RE.sub("_", normalized).lower()


def _restore_mapping_label(value: str) -> str:
    tokens = [token for token in value.replace("-", "_").split("_") if token]
    if not tokens:
        return value
    restored: list[str] = []
    acronym: list[str] = []
    for token in tokens:
        if len(token) == 1 and token.isalpha():
            acronym.append(token.upper())
            continue
        if acronym:
            restored.append("".join(acronym))
            acronym = []
        restored.append(token.capitalize() if token.islower() else token)
    if acronym:
        restored.append("".join(acronym))
    return " ".join(restored)


def _extract_list_payload(
    value: Any, *, wrapper_keys: tuple[str, ...] = (), allow_mapping_values: bool = False
) -> list[Any] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        cleaned = _clean_text_value(value)
        if not cleaned:
            return []
        if any(separator in cleaned for separator in (",", ";", "\n")):
            parts = [_clean_text_value(part) for part in MULTI_VALUE_SPLIT_RE.split(cleaned)]
            return [part for part in parts if part]
        return [cleaned]
    if not isinstance(value, dict):
        return None

    for key in wrapper_keys:
        if key not in value:
            continue
        nested_list = _extract_list_payload(
            value.get(key), wrapper_keys=wrapper_keys, allow_mapping_values=allow_mapping_values
        )
        if nested_list is not None:
            return nested_list

    if allow_mapping_values and not set(value).intersection(wrapper_keys):
        coerced: list[Any] = []
        for key, item in value.items():
            if isinstance(item, dict):
                patched = dict(item)
                patched.setdefault(
                    "mapping_key", _restore_mapping_label(_clean_text_value(key) or str(key))
                )
                coerced.append(patched)
            else:
                cleaned = _clean_text_value(item)
                if cleaned:
                    coerced.append(cleaned)
        if coerced:
            return coerced

    if len(value) == 1:
        only_value = next(iter(value.values()))
        nested_list = _extract_list_payload(
            only_value, wrapper_keys=wrapper_keys, allow_mapping_values=allow_mapping_values
        )
        if nested_list is not None:
            return nested_list

    return None


def _normalize_text_list(
    value: Any, *, item_aliases: tuple[str, ...], wrapper_keys: tuple[str, ...] = ()
) -> list[str]:
    items = _extract_list_payload(value, wrapper_keys=wrapper_keys, allow_mapping_values=True)
    if items is None:
        return []

    normalized: list[str] = []
    for item in items:
        if isinstance(item, str):
            cleaned = _clean_text_value(item)
            if cleaned:
                normalized.append(cleaned)
            continue
        if isinstance(item, dict):
            text_value = _extract_first_text(item, item_aliases)
            if text_value:
                timeline = _extract_first_text(
                    item, ("timeline", "due", "due_date", "eta", "term", "deadline")
                )
                owner = _extract_first_text(item, ("owner", "responsible", "assignee", "role"))
                suffix_parts = []
                if timeline:
                    suffix_parts.append(f"timeline: {timeline}")
                if owner:
                    suffix_parts.append(f"owner: {owner}")
                if suffix_parts:
                    text_value = f"{text_value} ({'; '.join(suffix_parts)})"
                normalized.append(text_value)
            continue
        if isinstance(item, list):
            normalized.extend(_normalize_text_list(item, item_aliases=item_aliases))
            continue
        cleaned = _clean_text_value(str(item))
        if cleaned:
            normalized.append(cleaned)
    return _deduplicate_texts(normalized)


def _normalize_interfaces_container(interfaces: Any) -> list[Any]:
    normalized_interfaces = _extract_list_payload(
        interfaces, wrapper_keys=("items", "entries", "interfaces", "ports", "apis")
    )
    if normalized_interfaces is not None:
        return normalized_interfaces
    if isinstance(interfaces, dict):
        patched_interfaces: list[dict[str, Any]] = []
        for key, item in interfaces.items():
            if isinstance(item, dict):
                interface = dict(item)
                interface.setdefault(
                    "interface_name", _restore_mapping_label(_clean_text_value(key) or str(key))
                )
                patched_interfaces.append(interface)
            else:
                interface_name = _restore_mapping_label(_clean_text_value(key) or str(key))
                description = _clean_text_value(item)
                if interface_name:
                    payload: dict[str, Any] = {"interface_name": interface_name}
                    if description:
                        payload["description"] = description
                    patched_interfaces.append(payload)
        return patched_interfaces
    return []


def _clean_text_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned or None


def _split_sentences(value: str) -> list[str]:
    if not value:
        return []
    return [
        item.strip(" -•	")
        for item in SENTENCE_SPLIT_RE.split(value)
        if item and item.strip(" -•	")
    ]


def _deduplicate_texts(items: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = _clean_text_value(item)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _tokenize_for_match(value: str) -> set[str]:
    normalized = value.casefold()
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return {token for token in normalized.split() if len(token) >= 4}


def _build_quote_excerpt(value: str, *, limit: int = 240) -> str | None:
    cleaned = _clean_text_value(value)
    if not cleaned or len(cleaned) < 8:
        return None
    if len(cleaned) <= limit:
        return cleaned
    clipped = cleaned[:limit].rsplit(" ", 1)[0].strip()
    return clipped or cleaned[:limit]


def _normalize_text_for_evidence_match(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.casefold()).strip()
    return normalized


def _extract_first_text(mapping: dict[str, Any], aliases: tuple[str, ...]) -> str | None:
    for alias in aliases:
        cleaned = _clean_text_value(mapping.get(alias))
        if cleaned:
            return cleaned
    return None


__all__ = [
    "CAMEL_CASE_BOUNDARY_RE",
    "GENERATION_ROOT_KEYS",
    "GENERATION_WRAPPER_KEYS",
    "INTEGRATION_ARROW_RE",
    "JSON_BLOCK_RE",
    "MULTI_VALUE_SPLIT_RE",
    "SECTION_FIELD_ALIASES",
    "SECTION_TITLE_BY_CODE",
    "SENTENCE_SPLIT_RE",
    "_build_quote_excerpt",
    "_clean_text_value",
    "_component_name_key",
    "_deduplicate_texts",
    "_extract_first_text",
    "_extract_json_payload",
    "_extract_list_payload",
    "_normalize_bool_like",
    "_normalize_component_name",
    "_normalize_interfaces_container",
    "_normalize_section_code_value",
    "_normalize_text_for_evidence_match",
    "_normalize_text_list",
    "_parse_integration_string",
    "_restore_mapping_label",
    "_split_sentences",
    "_to_snake_case",
    "_tokenize_for_match",
    "Any",
    "assess_section_readiness",
    "build_section_fallback_body",
    "coerce_generation_risk_severity",
    "derive_structured_architecture_model",
    "normalize_architecture_boundary_type",
    "normalize_generation_section_code",
    "should_apply_section_fallback",
]
