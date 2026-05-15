# ruff: noqa: E501
from __future__ import annotations

from typing import Any

from .payload_normalization_common import (
    GENERATION_WRAPPER_KEYS,
    MULTI_VALUE_SPLIT_RE,
    _clean_text_value,
    _component_name_key,
    _extract_list_payload,
    _normalize_component_name,
    _parse_integration_string,
    _restore_mapping_label,
)

ARCHITECTURE_FLOW_ORDER = (
    "business_architecture",
    "application_architecture",
    "data_architecture",
    "technology_architecture",
)


def _extract_integrations_candidate(payload: dict[str, Any]) -> list[Any] | None:
    integration_aliases = (
        "integrations",
        "integration_list",
        "interaction_model",
        "interfaces",
        "connections",
        "data_flows",
        "flows",
    )

    def _coerce_integration_value(value: Any) -> list[Any] | None:
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, str):
            cleaned = _clean_text_value(value)
            if not cleaned:
                return []
            return [
                part
                for part in (
                    _clean_text_value(part) for part in MULTI_VALUE_SPLIT_RE.split(cleaned)
                )
                if part
            ]
        if isinstance(value, dict):
            for wrapper_key in (
                "items",
                "entries",
                "integrations",
                "integration_list",
                "connections",
                "flows",
            ):
                nested = value.get(wrapper_key)
                if isinstance(nested, list):
                    return nested
            coerced: list[dict[str, Any] | Any] = []
            for key, item in value.items():
                if isinstance(item, dict):
                    patched = dict(item)
                    parsed_key = _parse_integration_string(key)
                    if parsed_key:
                        patched = {**parsed_key, **patched}
                    else:
                        patched.setdefault(
                            "mapping_key",
                            _restore_mapping_label(_clean_text_value(key) or str(key)),
                        )
                    coerced.append(patched)
                else:
                    parsed = _parse_integration_string(key)
                    if parsed is not None:
                        interaction_text = _clean_text_value(item)
                        if interaction_text and not _clean_text_value(parsed.get("interaction")):
                            parsed["interaction"] = interaction_text
                        coerced.append(parsed)
                    else:
                        cleaned = _clean_text_value(item)
                        if cleaned:
                            coerced.append(cleaned)
            if coerced:
                return coerced
        return None

    for key in integration_aliases:
        value = _coerce_integration_value(payload.get(key))
        if value is not None and value != []:
            return value

    for wrapper_key in GENERATION_WRAPPER_KEYS:
        nested = payload.get(wrapper_key)
        if isinstance(nested, dict):
            for key in integration_aliases:
                value = _coerce_integration_value(nested.get(key))
                if value is not None and value != []:
                    return value

    return None


def _canonicalize_component_reference(
    reference: Any, component_names: dict[str, str]
) -> str | None:
    normalized_reference = _normalize_component_name(reference)
    if not normalized_reference:
        return None
    return component_names.get(_component_name_key(normalized_reference), normalized_reference)


def _normalize_integrations(integrations: Any, *, components: list[Any] | None = None) -> list[Any]:
    items = (
        integrations
        if isinstance(integrations, list)
        else _extract_list_payload(
            integrations,
            wrapper_keys=(
                "items",
                "entries",
                "integrations",
                "integration_list",
                "connections",
                "flows",
            ),
            allow_mapping_values=True,
        )
    )
    if items is None:
        return []

    component_name_map: dict[str, str] = {}
    for item in components or []:
        if not isinstance(item, dict):
            continue
        component_name = _clean_text_value(item.get("component_name"))
        if not component_name:
            continue
        component_name_map[_component_name_key(component_name)] = component_name

    patched_integrations: list[dict[str, Any] | Any] = []
    for item in items:
        if isinstance(item, str):
            parsed = _parse_integration_string(item)
            if parsed is not None:
                patched_integrations.append(parsed)
            continue
        if isinstance(item, dict):
            integration = dict(item)
            if not _clean_text_value(integration.get("from_component")):
                for alias in ("source", "from", "producer", "caller", "client", "mapping_key"):
                    alias_value = _normalize_component_name(integration.get(alias))
                    if alias_value:
                        integration["from_component"] = alias_value
                        break
            if not _clean_text_value(integration.get("to_component")):
                for alias in ("target", "to", "consumer", "callee", "server", "destination"):
                    alias_value = _normalize_component_name(integration.get(alias))
                    if alias_value:
                        integration["to_component"] = alias_value
                        break
            if not _clean_text_value(integration.get("interaction")):
                for alias in (
                    "interaction",
                    "description",
                    "flow",
                    "purpose",
                    "details",
                    "summary",
                ):
                    alias_value = _clean_text_value(integration.get(alias))
                    if alias_value:
                        integration["interaction"] = alias_value
                        break
            if not _clean_text_value(integration.get("protocol")):
                for alias in ("transport", "type"):
                    alias_value = _clean_text_value(integration.get(alias))
                    if alias_value:
                        integration["protocol"] = alias_value
                        break
            if not _clean_text_value(integration.get("rationale")):
                for alias in ("reason", "justification", "why"):
                    alias_value = _clean_text_value(integration.get(alias))
                    if alias_value:
                        integration["rationale"] = alias_value
                        break
            if _clean_text_value(integration.get("from_component")):
                integration["from_component"] = _canonicalize_component_reference(
                    integration.get("from_component"), component_name_map
                )
            if _clean_text_value(integration.get("to_component")):
                integration["to_component"] = _canonicalize_component_reference(
                    integration.get("to_component"), component_name_map
                )
            if (
                not _clean_text_value(integration.get("rationale"))
                and _clean_text_value(integration.get("interaction"))
                and _clean_text_value(integration.get("from_component"))
                and _clean_text_value(integration.get("to_component"))
            ):
                integration["rationale"] = (
                    f"Supports {integration['interaction']} between {integration['from_component']} and {integration['to_component']} within the target architecture scope."
                )
            if (
                _clean_text_value(integration.get("from_component"))
                and _clean_text_value(integration.get("to_component"))
                and _clean_text_value(integration.get("interaction"))
            ):
                patched_integrations.append(integration)
            continue
        patched_integrations.append(item)

    deduped_integrations: list[dict[str, Any] | Any] = []
    seen_integrations: set[tuple[str, str, str]] = set()
    for item in patched_integrations:
        if not isinstance(item, dict):
            deduped_integrations.append(item)
            continue
        key = (
            _component_name_key(item.get("from_component")),
            _component_name_key(item.get("to_component")),
            (_clean_text_value(item.get("interaction")) or "").casefold(),
        )
        if key in seen_integrations:
            continue
        seen_integrations.add(key)
        deduped_integrations.append(item)
    return deduped_integrations


def _ensure_default_integrations(
    integrations: list[Any],
    *,
    components: list[Any] | None = None,
) -> list[Any]:
    patched_integrations = list(integrations)
    if patched_integrations or not components:
        return patched_integrations

    component_by_boundary: dict[str, str] = {}
    for item in components:
        if not isinstance(item, dict):
            continue
        component_name = _clean_text_value(item.get("component_name"))
        boundary_type = _clean_text_value(item.get("boundary_type"))
        if not component_name or not boundary_type:
            continue
        if boundary_type not in ARCHITECTURE_FLOW_ORDER:
            continue
        component_by_boundary.setdefault(boundary_type, component_name)

    def _add_relation(
        from_boundary: str,
        to_boundary: str,
        interaction: str,
        rationale: str,
    ) -> None:
        from_component = component_by_boundary.get(from_boundary)
        to_component = component_by_boundary.get(to_boundary)
        if not from_component or not to_component or from_component == to_component:
            return
        patched_integrations.append(
            {
                "from_component": from_component,
                "to_component": to_component,
                "interaction": interaction,
                "protocol": "архитектурная зависимость, подлежит подтверждению",
                "rationale": rationale,
            }
        )

    _add_relation(
        "business_architecture",
        "application_architecture",
        "Бизнес-процесс согласования передает запрос, статус и правила обработки в прикладной сервис.",
        "Связь показывает, какой Application Component поддерживает целевой Business Process.",
    )
    _add_relation(
        "application_architecture",
        "data_architecture",
        "Прикладной сервис создает, читает и обновляет Data Object архитектурного артефакта, замечаний и версии публикации.",
        "Связь показывает, какие данные нужны приложению для согласования и публикации.",
    )
    _add_relation(
        "application_architecture",
        "technology_architecture",
        "Прикладной сервис исполняется на технологической платформе и использует Technology Service хранения и резервного восстановления.",
        "Связь показывает зависимость Application Component от технологического слоя без фиксации неподтвержденной ОС или площадки.",
    )
    return patched_integrations


__all__ = [name for name in globals() if name != "__builtins__"]
