from __future__ import annotations

from app.db.enums import Severity
from app.domain.architecture import REQUIRED_TOGAF_SECTION_CODES

from .payload_normalization_common import (
    GENERATION_ROOT_KEYS,
    GENERATION_WRAPPER_KEYS,
    Any,
    _clean_text_value,
    _extract_list_payload,
    _normalize_text_list,
    _restore_mapping_label,
    _to_snake_case,
    coerce_generation_risk_severity,
    normalize_generation_section_code,
)
from .payload_normalization_components import (
    _normalize_components,
    _recover_missing_components_from_payload,
)
from .payload_normalization_integrations import (
    _ensure_default_integrations,
    _extract_integrations_candidate,
    _normalize_integrations,
)
from .payload_normalization_sections import (
    _normalize_sections,
    _synthesize_missing_required_sections,
)

_LOW_SIGNAL_RISK_MITIGATION_MARKERS = {
    "-",
    "--",
    "n/a",
    "na",
    "none",
    "todo",
    "tbd",
    "define mitigation plan",
    "mitigation plan",
    "review later",
    "определить план",
    "план смягчения",
    "уточнить позже",
    "нужно уточнить",
}


def _specific_risk_mitigation(risk: dict[str, Any]) -> str:
    anchor = (
        _clean_text_value(risk.get("title"))
        or _clean_text_value(risk.get("description"))
        or "выявленный архитектурный риск"
    )
    anchor = anchor[:120].rstrip(" .")
    return (
        f"Назначить владельца риска «{anchor}», зафиксировать конкретное действие, "
        "критерий проверки на архитектурном чекпоинте и условие отката, если мера не сработает."
    )


def _is_low_signal_risk_mitigation(value: Any) -> bool:
    cleaned = _clean_text_value(value)
    if not cleaned:
        return True
    lowered = cleaned.lower()
    if len(cleaned) < 24:
        return True
    if lowered in _LOW_SIGNAL_RISK_MITIGATION_MARKERS:
        return True
    if any(
        marker in lowered
        for marker in (
            "define mitigation plan",
            "review later",
            "определить план",
            "уточнить позже",
        )
    ):
        return True
    return sum(1 for char in cleaned if char.isalpha()) < 12


def _normalize_generation_payload_shape(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = payload
    if not GENERATION_ROOT_KEYS.intersection(candidate.keys()):
        for wrapper_key in GENERATION_WRAPPER_KEYS:
            nested = candidate.get(wrapper_key)
            if isinstance(nested, dict):
                candidate = nested
                break
    normalized = _normalize_mapping_keys(candidate)
    normalized = _normalize_generation_top_level_aliases(normalized)
    normalized = _normalize_generation_field_values(normalized)
    return normalized


def _normalize_mapping_keys(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_mapping_keys(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        raw_key = str(key)
        normalized_key = (
            raw_key
            if any(marker in raw_key for marker in ("->", "→", "=>", "↔", "<->"))
            else _to_snake_case(raw_key)
        )
        normalized[normalized_key] = _normalize_mapping_keys(item)
    return normalized


def _merge_root_alias_value(existing: Any, incoming: Any) -> Any:
    if existing is None:
        return incoming
    if isinstance(existing, str) and not _clean_text_value(existing):
        return incoming
    if isinstance(existing, list) and not existing:
        return incoming
    if isinstance(existing, dict) and not existing:
        return incoming
    if isinstance(existing, list) and isinstance(incoming, list):
        return existing + incoming
    if isinstance(existing, dict) and isinstance(incoming, dict):
        merged = dict(existing)
        for key, value in incoming.items():
            if key not in merged:
                merged[key] = value
        return merged
    if isinstance(existing, str) and isinstance(incoming, str) and len(incoming) > len(existing):
        return incoming
    return existing


def _normalize_generation_top_level_aliases(payload: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for raw_key, value in payload.items():
        key = _clean_text_value(raw_key) or str(raw_key)
        snake_key = _to_snake_case(key)
        canonical_section_key = normalize_generation_section_code(key)
        target_key = snake_key

        if snake_key in {"solution_title", "title", "name", "solution_name"}:
            target_key = "solution_title"
        elif snake_key in {"executive_summary", "summary", "executive", "abstract"}:
            target_key = "executive_summary"
        elif snake_key in {"sections", "section_list"}:
            target_key = "sections"
        elif snake_key in {"assumptions", "assumption_list", "constraints"}:
            target_key = "assumptions"
        elif snake_key in {"next_steps", "steps", "actions", "plan"}:
            target_key = "next_steps"
        elif snake_key in {
            "components",
            "component",
            "component_model",
            "component_list",
            "system_components",
            "architecture_components",
            "service_components",
            "services",
            "service_model",
            "modules",
            "subsystems",
        }:
            target_key = "components"
        elif snake_key in {
            "integrations",
            "integration",
            "integration_list",
            "interaction_model",
            "interfaces",
            "connections",
            "data_flows",
            "flows",
            "integrations_topology",
        }:
            target_key = "integrations"
        elif snake_key in {
            "risks",
            "risk",
            "risk_assessment",
            "limitations",
            "issues",
            "constraints_and_risks",
            "risks_and_constraints",
        }:
            target_key = "risks"
        elif isinstance(canonical_section_key, str) and canonical_section_key in set(
            REQUIRED_TOGAF_SECTION_CODES
        ):
            target_key = canonical_section_key
            if (
                canonical_section_key == "general_information"
                and "executive_summary" not in payload
                and isinstance(value, str)
            ):
                normalized["executive_summary"] = _merge_root_alias_value(
                    normalized.get("executive_summary"), value
                )

        normalized[target_key] = _merge_root_alias_value(normalized.get(target_key), value)

    return normalized


def _extract_components_candidate(payload: dict[str, Any]) -> list[Any] | None:
    component_aliases = (
        "components",
        "component_list",
        "component_model",
        "system_components",
        "architecture_components",
        "service_components",
    )

    def _coerce_component_value(value: Any) -> list[Any] | None:
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for wrapper_key in (
                "items",
                "entries",
                "components",
                "component_list",
                "component_model",
                "nodes",
            ):
                nested = value.get(wrapper_key)
                if isinstance(nested, list):
                    return nested
            coerced: list[dict[str, Any] | Any] = []
            for key, item in value.items():
                if isinstance(item, dict):
                    patched = dict(item)
                    patched.setdefault(
                        "component_name", _restore_mapping_label(_clean_text_value(key) or str(key))
                    )
                    coerced.append(patched)
                else:
                    component_name = _restore_mapping_label(_clean_text_value(key) or str(key))
                    role_description = _clean_text_value(item)
                    if component_name and role_description:
                        coerced.append(
                            {"component_name": component_name, "role_description": role_description}
                        )
            if coerced:
                return coerced
        return None

    for key in component_aliases:
        value = _coerce_component_value(payload.get(key))
        if value:
            return value

    for wrapper_key in GENERATION_WRAPPER_KEYS:
        nested = payload.get(wrapper_key)
        if isinstance(nested, dict):
            for key in component_aliases:
                value = _coerce_component_value(nested.get(key))
                if value:
                    return value

    return None


def _normalize_sections_container(sections: Any) -> list[Any] | Any:
    if isinstance(sections, list):
        return sections
    if isinstance(sections, dict):
        wrapped = _extract_list_payload(
            sections, wrapper_keys=("items", "entries", "sections", "section_list")
        )
        if wrapped is not None and wrapped != []:
            return wrapped
        normalized_sections: list[dict[str, Any] | Any] = []
        for key, item in sections.items():
            if isinstance(item, dict):
                section = dict(item)
                section.setdefault("section_code", _clean_text_value(key) or str(key))
                normalized_sections.append(section)
            else:
                body_value = _clean_text_value(item)
                if body_value:
                    section_code = _clean_text_value(key) or str(key)
                    normalized_sections.append(
                        {
                            "section_code": section_code,
                            "title": section_code.replace("_", " ").title(),
                            "body_markdown": body_value,
                            "source_refs": [],
                        }
                    )
        return normalized_sections
    return sections


def _extract_normalized_risk_severity(risk: dict[str, Any]) -> str | None:
    severity_aliases = (
        "severity",
        "severity_level",
        "risk_severity",
        "risk_level",
        "criticality",
        "priority",
        "impact_level",
        "impact",
        "level",
    )
    for alias in severity_aliases:
        if alias not in risk:
            continue
        normalized = coerce_generation_risk_severity(risk.get(alias))
        if isinstance(normalized, Severity):
            return normalized.value
        if isinstance(normalized, str) and normalized in Severity._value2member_map_:
            return normalized
    return None


def _normalize_risks_list(risks: Any) -> list[Any]:
    items = _extract_list_payload(
        risks,
        wrapper_keys=("items", "entries", "risks", "risk_list", "open_questions"),
        allow_mapping_values=True,
    )
    if items is None:
        return []
    patched_risks: list[dict[str, Any] | Any] = []
    for item in items:
        if isinstance(item, str):
            description = _clean_text_value(item)
            if description:
                patched_risks.append(
                    {
                        "title": description[:80],
                        "severity": "major",
                        "description": description,
                        "mitigation": _specific_risk_mitigation(
                            {"title": description[:80], "description": description}
                        ),
                    }
                )
            continue
        if isinstance(item, dict):
            risk = dict(item)
            if "description" not in risk:
                for alias in (
                    "risk",
                    "risk_description",
                    "risk_details",
                    "risk_summary",
                    "description_text",
                    "text",
                    "limitation",
                    "constraint",
                    "issue",
                    "problem",
                    "open_question",
                    "details",
                    "summary",
                    "body",
                    "mapping_key",
                ):
                    alias_value = _clean_text_value(risk.get(alias))
                    if alias_value:
                        risk["description"] = alias_value
                        break
            if "title" not in risk:
                for alias in (
                    "title",
                    "name",
                    "label",
                    "risk_title",
                    "risk_name",
                    "risk_label",
                    "limitation",
                    "constraint",
                    "issue",
                    "mapping_key",
                ):
                    alias_value = _clean_text_value(risk.get(alias))
                    if alias_value:
                        risk["title"] = alias_value
                        break
            normalized_severity = _extract_normalized_risk_severity(risk)
            if normalized_severity:
                risk["severity"] = normalized_severity
            elif "severity" not in risk or not _clean_text_value(risk.get("severity")):
                risk["severity"] = "major"
            if "mitigation" not in risk:
                for alias in (
                    "action",
                    "response",
                    "plan",
                    "mitigate",
                    "mitigation_plan",
                    "mitigation_strategy",
                    "mitigation_steps",
                    "mitigation_actions",
                    "risk_mitigation",
                    "risk_response",
                    "response_plan",
                    "control",
                    "controls",
                ):
                    alias_value = _clean_text_value(risk.get(alias))
                    if alias_value:
                        risk["mitigation"] = alias_value
                        break
            if risk.get("description") and not risk.get("title"):
                risk["title"] = str(risk["description"])[:80]
            if risk.get("title") and not risk.get("description"):
                risk["description"] = (
                    f"Архитектурный риск «{risk['title']}» может повлиять на объём, "
                    "сроки, качество или проектные решения, если им не управлять явно."
                )
            if _is_low_signal_risk_mitigation(risk.get("mitigation")):
                risk["mitigation"] = _specific_risk_mitigation(risk)
            patched_risks.append(risk)
            continue
        patched_risks.append(item)
    return patched_risks


def _normalize_generation_field_values(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)

    integration_candidate = _extract_integrations_candidate(normalized)
    if integration_candidate is not None:
        normalized["integrations"] = integration_candidate
    normalized["integrations"] = _normalize_integrations(
        normalized.get("integrations"), components=[]
    )

    normalized["sections"] = _normalize_sections_container(normalized.get("sections", []))
    if isinstance(normalized.get("sections"), list):
        normalized["sections"] = _normalize_sections(normalized["sections"], normalized)

    components_value = normalized.get("components")
    if not isinstance(components_value, list) or not components_value:
        extracted_components = _extract_components_candidate(normalized)
        if isinstance(extracted_components, list) and extracted_components:
            normalized["components"] = extracted_components

    components_value = normalized.get("components")
    if not isinstance(components_value, list) or not components_value:
        normalized["components"] = _recover_missing_components_from_payload(normalized)

    if isinstance(normalized.get("components"), list):
        normalized["components"] = _normalize_components(normalized["components"])

    normalized["integrations"] = _normalize_integrations(
        normalized.get("integrations"),
        components=normalized.get("components")
        if isinstance(normalized.get("components"), list)
        else [],
    )
    normalized["integrations"] = _ensure_default_integrations(
        normalized["integrations"],
        components=normalized.get("components")
        if isinstance(normalized.get("components"), list)
        else [],
    )

    normalized["assumptions"] = _normalize_text_list(
        normalized.get("assumptions"),
        item_aliases=(
            "assumption_text",
            "assumption",
            "description",
            "text",
            "details",
            "summary",
            "body",
            "value",
            "mapping_key",
        ),
        wrapper_keys=("items", "entries", "assumptions", "assumption_list", "constraints"),
    )
    normalized["next_steps"] = _normalize_text_list(
        normalized.get("next_steps"),
        item_aliases=(
            "step_text",
            "step",
            "action",
            "description",
            "text",
            "details",
            "summary",
            "body",
            "title",
            "value",
            "mapping_key",
        ),
        wrapper_keys=("items", "entries", "next_steps", "steps", "actions", "plan"),
    )
    normalized["risks"] = _normalize_risks_list(normalized.get("risks"))
    normalized["sections"] = _synthesize_missing_required_sections(normalized)

    for alias_key in (
        "component_list",
        "component_model",
        "system_components",
        "architecture_components",
        "service_components",
        "integration_list",
        "interaction_model",
        "connections",
        "data_flows",
        "flows",
    ):
        normalized.pop(alias_key, None)

    normalized = {key: value for key, value in normalized.items() if key in GENERATION_ROOT_KEYS}
    return normalized
