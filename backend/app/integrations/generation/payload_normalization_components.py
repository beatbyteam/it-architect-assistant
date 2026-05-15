# ruff: noqa: E501
from __future__ import annotations

import re
from typing import Any

from .payload_normalization_common import (
    _clean_text_value,
    _component_name_key,
    _deduplicate_texts,
    _extract_first_text,
    _extract_list_payload,
    _normalize_bool_like,
    _normalize_component_name,
    _normalize_interfaces_container,
    _sanitize_unconfirmed_architecture_terms,
    normalize_architecture_boundary_type,
)

ARCHITECTURE_BOUNDARY_TYPES = (
    "business_architecture",
    "data_architecture",
    "application_architecture",
    "technology_architecture",
)

GENERIC_COMPONENT_NAME_MARKERS = {
    "solution core",
    "обзор бизнес-сущностей",
    "роли и бизнес-процессы",
    "роли и бизнес процессы",
    "объекты бизнес-услуг",
    "данные",
    "источники данных",
    "источники dữ liệu",
    "потребители данных",
    "компоненты прикладного слоя",
    "услуги приложения",
    "уровни инфраструктуры",
    "примерный сервис работы",
}

ARCHIMATE_LAYER_FALLBACK_COMPONENTS: tuple[dict[str, Any], ...] = (
    {
        "component_name": "Процесс согласования архитектурных артефактов",
        "role_description": (
            "Business Process координирует создание карточки артефакта, передачу на "
            "согласование, обработку замечаний и публикацию утвержденной версии."
        ),
        "boundary_type": "business_architecture",
        "technology_stack": "не применимо для бизнес-слоя",
        "external_flag": False,
        "interfaces": [],
    },
    {
        "component_name": "Инициатор архитектурного артефакта",
        "role_description": (
            "Business Actor и Business Role инициируют подготовку артефакта, получают "
            "статус согласования и подтверждают необходимость публикации."
        ),
        "boundary_type": "business_architecture",
        "technology_stack": "не применимо для бизнес-слоя",
        "external_flag": False,
        "interfaces": [],
    },
    {
        "component_name": "Архитектурный артефакт",
        "role_description": (
            "Data Object хранит содержимое архитектурного документа, его метаданные, "
            "версии, замечания экспертов и статус публикации."
        ),
        "boundary_type": "data_architecture",
        "technology_stack": "корпоративное хранилище данных, подлежит подтверждению",
        "external_flag": False,
        "interfaces": [],
    },
    {
        "component_name": "Журнал аудита согласования",
        "role_description": (
            "Data Object фиксирует события маршрута согласования, изменения версии, "
            "публикацию и действия участников процесса."
        ),
        "boundary_type": "data_architecture",
        "technology_stack": "управляемое хранилище событий, подлежит подтверждению",
        "external_flag": False,
        "interfaces": [],
    },
    {
        "component_name": "Сервис управления артефактами",
        "role_description": (
            "Application Component реализует прикладной сервис создания карточки, "
            "загрузки файла, маршрутизации согласования и публикации версии."
        ),
        "boundary_type": "application_architecture",
        "technology_stack": "прикладной сервис в корпоративном контуре, подлежит подтверждению",
        "external_flag": False,
        "interfaces": [
            {
                "interface_name": "API управления архитектурными артефактами",
                "protocol": "REST/HTTP или внутренний API, подлежит подтверждению",
                "description": "Application Interface для загрузки, согласования и публикации артефактов.",
            }
        ],
    },
    {
        "component_name": "Веб-интерфейс согласования",
        "role_description": (
            "Application Interface предоставляет пользователям прикладной доступ к "
            "созданию карточки, просмотру статусов, внесению замечаний и публикации."
        ),
        "boundary_type": "application_architecture",
        "technology_stack": "корпоративный веб-интерфейс, подлежит подтверждению",
        "external_flag": False,
        "interfaces": [],
    },
    {
        "component_name": "Платформа выполнения сервиса",
        "role_description": (
            "Node и System Software предоставляют среду исполнения прикладных "
            "компонентов без фиксации конкретной ОС до подтверждения инфраструктуры."
        ),
        "boundary_type": "technology_architecture",
        "technology_stack": "серверная или контейнерная платформа, подлежит подтверждению",
        "external_flag": False,
        "interfaces": [],
    },
    {
        "component_name": "Хранилище документов и метаданных",
        "role_description": (
            "Technology Service предоставляет хранение файлов артефактов, метаданных, "
            "версий публикации и резервное восстановление."
        ),
        "boundary_type": "technology_architecture",
        "technology_stack": "объектное хранилище и СУБД, подлежат подтверждению",
        "external_flag": False,
        "interfaces": [],
    },
)


def _fallback_component_for_boundary(boundary_type: str) -> dict[str, Any]:
    for component in ARCHIMATE_LAYER_FALLBACK_COMPONENTS:
        if component["boundary_type"] == boundary_type:
            return dict(component)
    raise KeyError(boundary_type)


def _infer_archimate_boundary_type(
    component_name: Any,
    role_description: Any = None,
    technology_stack: Any = None,
) -> str | None:
    name_text = (_clean_text_value(component_name) or "").casefold()
    role_text = (_clean_text_value(role_description) or "").casefold()
    stack_text = (_clean_text_value(technology_stack) or "").casefold()
    text = " ".join(part for part in (name_text, role_text, stack_text) if part)
    if not text:
        return None
    if any(
        marker in name_text
        for marker in (
            "серверное приложение",
            "клиентское приложение",
            "приложение",
            "приклад",
            "application component",
            "application service",
            "application interface",
            "ui",
            "web",
            "backend",
            "frontend",
        )
    ):
        return "application_architecture"
    if any(
        marker in text
        for marker in (
            "business actor",
            "business role",
            "business process",
            "business service",
            "специалист",
            "архитектор",
            "эксперт",
            "инициатор",
            "участник",
            "пользователь",
            "согласующий",
            "владелец процесса",
            "роль",
            "создание",
            "отправка",
            "процесс согласования",
            "согласование и утверждение",
            "согласование архитектурных",
            "обработка и утверждение",
            "workflow",
        )
    ):
        return "business_architecture"
    if any(
        marker in text
        for marker in (
            "data object",
            "business object",
            "representation",
            "метаданн",
            "модель данных",
            "объект данных",
            "артефакт",
            "документ",
            "версия",
            "замечан",
            "реестр",
            "данн",
        )
    ) and not any(
        marker in name_text
        for marker in (
            "сервис",
            "api",
            "ui",
            "web",
            "интерфейс",
            "приложение",
            "приклад",
        )
    ):
        return "data_architecture"
    if any(
        marker in text
        for marker in (
            "node",
            "system software",
            "technology service",
            "network",
            "technology interface",
            "сервер",
            "postgres",
            "redis",
            "broker",
            "очеред",
            "runtime",
            "container",
            "kubernetes",
            "gateway",
            "tls",
            "бд",
            "платформа",
        )
    ):
        return "technology_architecture"
    if any(
        marker in text
        for marker in (
            "application component",
            "application service",
            "application interface",
            "сервис",
            "api",
            "ui",
            "web",
            "прилож",
            "интерфейс",
            "backend",
            "frontend",
        )
    ):
        return "application_architecture"
    return None


def _role_description_for_boundary(component_name: str, boundary_type: str) -> str:
    if boundary_type == "business_architecture":
        lowered_name = component_name.casefold()
        if any(marker in lowered_name for marker in ("отдел", "подраздел", "команда")):
            return (
                f"Business Actor {component_name} представляет организационного участника "
                "процесса согласования архитектурных артефактов."
            )
        if any(
            marker in lowered_name
            for marker in (
                "специалист",
                "архитектор",
                "эксперт",
                "инициатор",
                "участник",
                "пользователь",
                "роль",
            )
        ):
            return (
                f"Business Role {component_name} отвечает за участие в целевом "
                "бизнес-сценарии согласования архитектурных артефактов."
            )
        if any(
            marker in lowered_name
            for marker in (
                "процесс",
                "создание",
                "отправка",
                "загрузка",
                "согласование",
                "утверждение",
                "обработка",
                "workflow",
            )
        ):
            return (
                f"Business Process {component_name} описывает бизнес-поток создания, "
                "согласования и публикации архитектурных артефактов."
            )
        return (
            f"Business Service {component_name} описывает бизнес-услугу целевого "
            "сценария согласования архитектурных артефактов."
        )
    if boundary_type == "data_architecture":
        return (
            f"Data Object {component_name} фиксирует данные, версии, метаданные или "
            "представление архитектурного артефакта."
        )
    if boundary_type == "technology_architecture":
        return (
            f"Node, System Software или Technology Service {component_name} обеспечивает "
            "исполнение, хранение или сетевую связность прикладного контура."
        )
    return (
        f"Application Component {component_name} реализует прикладную возможность "
        "целевого сервиса согласования архитектурных артефактов."
    )


def _is_generic_component_role_description(value: Any) -> bool:
    role_description = (_clean_text_value(value) or "").casefold()
    return (
        not role_description
        or "участвует в реализации целевой архитектуры" in role_description
        or "требует дальнейшей детализации" in role_description
        or "требует последующей детализации" in role_description
    )


def _should_refresh_business_role_description(component_name: Any, role_description: Any) -> bool:
    name_text = (_clean_text_value(component_name) or "").casefold()
    role_text = (_clean_text_value(role_description) or "").casefold()
    if not name_text:
        return False
    actor_or_role_markers = (
        "специалист",
        "архитектор",
        "эксперт",
        "инициатор",
        "участник",
        "пользователь",
        "роль",
    )
    process_markers = (
        "процесс",
        "создание",
        "отправка",
        "загрузка",
        "согласование",
        "утверждение",
        "обработка",
        "workflow",
    )
    if not any(marker in name_text for marker in actor_or_role_markers + process_markers):
        return False
    explicit_business_elements = (
        "business actor",
        "business role",
        "business process",
        "business function",
        "business service",
        "business event",
    )
    return "business service" in role_text or not any(
        marker in role_text for marker in explicit_business_elements
    )


def _normalize_component_interfaces(interfaces: Any) -> list[Any]:
    interfaces = _normalize_interfaces_container(interfaces)

    patched_interfaces: list[dict[str, Any] | Any] = []
    for item in interfaces:
        if isinstance(item, str):
            interface_name = _clean_text_value(item)
            if interface_name:
                patched_interfaces.append({"interface_name": interface_name})
            continue
        if isinstance(item, dict):
            interface = dict(item)
            if "interface_name" not in interface:
                for alias in ("name", "title", "interface", "endpoint"):
                    alias_value = _clean_text_value(interface.get(alias))
                    if alias_value:
                        interface["interface_name"] = alias_value
                        break
            if "protocol" not in interface:
                for alias in ("transport", "type"):
                    alias_value = _clean_text_value(interface.get(alias))
                    if alias_value:
                        interface["protocol"] = alias_value
                        break
            if "description" not in interface:
                for alias in ("details", "purpose", "summary"):
                    alias_value = _clean_text_value(interface.get(alias))
                    if alias_value:
                        interface["description"] = alias_value
                        break
            interface_name = _clean_text_value(interface.get("interface_name"))
            if not interface_name:
                continue
            interface["interface_name"] = interface_name
            protocol = _clean_text_value(interface.get("protocol"))
            if protocol is not None:
                interface["protocol"] = protocol
            description = _clean_text_value(interface.get("description"))
            if description is not None:
                interface["description"] = description
            patched_interfaces.append(interface)
            continue
        patched_interfaces.append(item)
    return patched_interfaces


def _extract_component_names_from_text(text: str) -> list[str]:
    if not text:
        return []

    raw_chunks = re.split(r"[\n;•]+", text)
    candidates: list[str] = []
    for chunk in raw_chunks:
        head = re.split(r"\s[-—:]\s", chunk, maxsplit=1)[0]
        cleaned = head.strip(" .,:()[]{}\t")
        cleaned = re.sub(r"^[#*_`>\s-]+", "", cleaned).strip(" .,:()[]{}\t")
        if not cleaned:
            continue
        if len(cleaned) > 80:
            continue
        if len(cleaned.split()) > 8:
            continue
        lowered = cleaned.casefold()
        if lowered in {
            "компоненты",
            "components",
            "архитектура",
            "architecture",
            "интеграции",
            "integrations",
            "риски",
            "risks",
            "обзор",
            "overview",
            "общие сведения",
            "описание бизнес задач",
            "содержание ит архитектуры",
            "бизнес архитектура",
            "архитектура данных",
            "архитектура приложений",
            "технологическая архитектура",
            "дополнительные сведения",
        } or any(marker in lowered for marker in GENERIC_COMPONENT_NAME_MARKERS):
            continue
        candidates.append(cleaned)

    return _deduplicate_texts(candidates)[:8]


def _recover_missing_components_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    recovered: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_component(
        name: Any,
        role_description: str | None = None,
        *,
        boundary_type: str = "application_architecture",
        technology_stack: str | None = None,
    ) -> None:
        component_name = _normalize_component_name(name)
        if not component_name:
            return
        if component_name.casefold() in GENERIC_COMPONENT_NAME_MARKERS:
            return
        normalized_boundary_type = normalize_architecture_boundary_type(boundary_type)
        if normalized_boundary_type not in ARCHITECTURE_BOUNDARY_TYPES:
            normalized_boundary_type = "application_architecture"
        key = component_name.casefold()
        if key in seen:
            return
        seen.add(key)
        recovered.append(
            {
                "component_name": component_name,
                "role_description": (
                    _clean_text_value(role_description)
                    or f"Application Component {component_name} участвует в реализации целевой архитектуры и требует последующей детализации обязанностей и интерфейсов."
                ),
                "boundary_type": normalized_boundary_type,
                "technology_stack": _clean_text_value(technology_stack),
                "external_flag": False,
                "interfaces": [],
            }
        )

    integrations_raw = payload.get("integrations")
    integrations: list[Any] = integrations_raw if isinstance(integrations_raw, list) else []
    for item in integrations:
        if not isinstance(item, dict):
            continue
        interaction = _extract_first_text(item, ("interaction", "description", "flow", "purpose"))
        from_component = _extract_first_text(item, ("from_component", "source", "from", "producer"))
        to_component = _extract_first_text(item, ("to_component", "target", "to", "consumer"))
        if from_component:
            add_component(
                from_component,
                f"Application Component инициирует интеграционное взаимодействие{': ' + interaction if interaction else '.'}",
                boundary_type="application_architecture",
            )
        if to_component:
            add_component(
                to_component,
                f"Application Component принимает или обрабатывает интеграционное взаимодействие{': ' + interaction if interaction else '.'}",
                boundary_type="application_architecture",
            )

    sections_raw = payload.get("sections")
    sections: list[Any] = sections_raw if isinstance(sections_raw, list) else []
    for item in sections:
        if not isinstance(item, dict):
            continue
        section_code = _clean_text_value(item.get("section_code")) or ""
        if section_code not in {
            "it_architecture_content",
            "business_architecture",
            "data_architecture",
            "application_architecture",
            "technology_architecture",
        }:
            continue
        title = _extract_first_text(item, ("title", "name", "heading", "label")) or section_code
        body_text = (
            _extract_first_text(
                item,
                (
                    "body_markdown",
                    "body",
                    "content",
                    "markdown",
                    "text",
                    "description",
                    "details",
                    "summary",
                ),
            )
            or ""
        )
        for component_name in _extract_component_names_from_text(body_text):
            add_component(
                component_name,
                f"Объект ArchiMate 3.2 упомянут в разделе {title} и требует детализации обязанностей и интерфейсов.",
                boundary_type=section_code,
            )

    if not recovered:
        summary = _clean_text_value(payload.get("executive_summary"))
        solution_title = (
            _clean_text_value(payload.get("solution_title")) or "архитектурного решения"
        )
        add_component(
            "Solution Core",
            summary
            or f"Application Component центрального контура {solution_title} координирует основной бизнес-процесс и интеграции решения.",
            boundary_type="application_architecture",
        )

    recovered = _ensure_archimate_layer_component_coverage(recovered)
    return recovered


def _merge_component_records(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for field_name in ("component_name", "role_description", "technology_stack", "boundary_type"):
        current = _clean_text_value(merged.get(field_name))
        candidate = _clean_text_value(incoming.get(field_name))
        if (
            not current
            and candidate
            or field_name == "role_description"
            and candidate
            and current
            and len(candidate) > len(current)
        ):
            merged[field_name] = candidate
    if "external_flag" not in merged or merged.get("external_flag") is None:
        merged["external_flag"] = incoming.get("external_flag", False)
    merged_interfaces = _normalize_component_interfaces(merged.get("interfaces"))
    incoming_interfaces = _normalize_component_interfaces(incoming.get("interfaces"))
    merged["interfaces"] = merged_interfaces + [
        item for item in incoming_interfaces if item not in merged_interfaces
    ]
    return merged


def _normalize_components(components: list[Any]) -> list[Any]:
    patched_components: list[dict[str, Any] | Any] = []
    for item in components:
        if isinstance(item, str):
            component_name = _normalize_component_name(item)
            if component_name:
                inferred_boundary_type = (
                    _infer_archimate_boundary_type(component_name)
                    or "application_architecture"
                )
                patched_components.append(
                    {
                        "component_name": component_name,
                        "role_description": _role_description_for_boundary(
                            component_name,
                            inferred_boundary_type,
                        ),
                        "boundary_type": inferred_boundary_type,
                        "interfaces": [],
                    }
                )
            continue
        if isinstance(item, dict):
            component = dict(item)
            if "component_name" not in component:
                for alias in ("component_code", "name", "title", "mapping_key"):
                    alias_value = _normalize_component_name(component.get(alias))
                    if alias_value:
                        component["component_name"] = alias_value
                        break
            else:
                component["component_name"] = _normalize_component_name(
                    component.get("component_name")
                )
            if "role_description" not in component:
                for alias in (
                    "description",
                    "role",
                    "purpose",
                    "responsibility",
                    "details",
                    "summary",
                ):
                    alias_value = _clean_text_value(component.get(alias))
                    if alias_value:
                        component["role_description"] = (
                            _sanitize_unconfirmed_architecture_terms(alias_value)
                            or alias_value
                        )
                        break
            if not _clean_text_value(component.get("role_description")) and _clean_text_value(
                component.get("component_name")
            ):
                component["role_description"] = (
                    f"Компонент {component['component_name']} участвует в реализации целевой архитектуры и требует дальнейшей детализации обязанностей."
                )
            if "boundary_type" not in component:
                for alias in ("boundary", "layer", "scope"):
                    alias_value = _clean_text_value(component.get(alias))
                    if alias_value:
                        component["boundary_type"] = alias_value
                        break
            normalized_component_boundary_type = normalize_architecture_boundary_type(
                component.get("boundary_type")
            )
            inferred_component_boundary_type = _infer_archimate_boundary_type(
                component.get("component_name"),
                component.get("role_description"),
                component.get("technology_stack"),
            )
            if (
                normalized_component_boundary_type == "application_architecture"
                and inferred_component_boundary_type
                and inferred_component_boundary_type != "application_architecture"
            ) or not normalized_component_boundary_type and inferred_component_boundary_type:
                normalized_component_boundary_type = inferred_component_boundary_type
            if normalized_component_boundary_type:
                component["boundary_type"] = normalized_component_boundary_type
            elif _clean_text_value(component.get("technology_stack")):
                component["boundary_type"] = "technology_architecture"
            else:
                component["boundary_type"] = "application_architecture"
            sanitized_role_description = _sanitize_unconfirmed_architecture_terms(
                component.get("role_description")
            )
            if sanitized_role_description:
                component["role_description"] = sanitized_role_description
            if _is_generic_component_role_description(
                component.get("role_description")
            ) or (
                component["boundary_type"] == "business_architecture"
                and _should_refresh_business_role_description(
                    component.get("component_name"),
                    component.get("role_description"),
                )
            ):
                component_name_for_role = _clean_text_value(component.get("component_name"))
                if component_name_for_role:
                    component["role_description"] = _role_description_for_boundary(
                        component_name_for_role,
                        component["boundary_type"],
                    )
            external_flag = component.get("external_flag")
            if external_flag is None:
                external_flag = (
                    component.get("is_external")
                    if "is_external" in component
                    else component.get("external")
                )
            normalized_external = _normalize_bool_like(external_flag)
            if normalized_external is not None:
                component["external_flag"] = normalized_external
            technology_stack = component.get("technology_stack")
            if technology_stack is None:
                technology_stack = component.get("stack") or component.get("technologies")
            if isinstance(technology_stack, list):
                component["technology_stack"] = (
                    ", ".join(
                        _deduplicate_texts(
                            [
                                str(stack_item)
                                for stack_item in technology_stack
                                if _clean_text_value(str(stack_item))
                            ]
                        )
                    )
                    or None
                )
            elif isinstance(technology_stack, dict):
                stack_items = _extract_list_payload(
                    technology_stack,
                    wrapper_keys=("items", "entries", "stack", "technologies"),
                    allow_mapping_values=True,
                )
                if stack_items is not None:
                    component["technology_stack"] = (
                        ", ".join(
                            _deduplicate_texts(
                                [
                                    str(stack_item)
                                    for stack_item in stack_items
                                    if _clean_text_value(str(stack_item))
                                ]
                            )
                        )
                        or None
                    )
            elif technology_stack is not None:
                component["technology_stack"] = _sanitize_unconfirmed_architecture_terms(
                    technology_stack
                )
            interfaces_value = component.get("interfaces")
            if interfaces_value is None:
                interfaces_value = (
                    component.get("interface")
                    or component.get("endpoints")
                    or component.get("apis")
                )
            component["interfaces"] = _normalize_component_interfaces(interfaces_value)
            if _clean_text_value(component.get("component_name")):
                lowered_component_name = component["component_name"].casefold()
                if lowered_component_name in GENERIC_COMPONENT_NAME_MARKERS:
                    continue
                patched_components.append(component)
            continue
        patched_components.append(item)

    merged_components: list[dict[str, Any] | Any] = []
    seen_components: dict[str, int] = {}
    for item in patched_components:
        if not isinstance(item, dict):
            merged_components.append(item)
            continue
        key = _component_name_key(item.get("component_name"))
        if not key:
            continue
        if key in seen_components:
            index = seen_components[key]
            existing = merged_components[index]
            if isinstance(existing, dict):
                merged_components[index] = _merge_component_records(existing, item)
            continue
        seen_components[key] = len(merged_components)
        merged_components.append(item)
    return _ensure_archimate_layer_component_coverage(merged_components)


def _ensure_archimate_layer_component_coverage(components: list[Any]) -> list[Any]:
    patched_components: list[Any] = list(components)
    seen_names = {
        _component_name_key(item.get("component_name"))
        for item in patched_components
        if isinstance(item, dict)
    }
    covered_boundaries = {
        normalized_boundary_type
        for item in patched_components
        if isinstance(item, dict)
        and (
            normalized_boundary_type := normalize_architecture_boundary_type(
                item.get("boundary_type")
            )
        )
        in ARCHITECTURE_BOUNDARY_TYPES
    }
    for boundary_type in ARCHITECTURE_BOUNDARY_TYPES:
        if boundary_type in covered_boundaries:
            continue
        fallback = _fallback_component_for_boundary(boundary_type)
        fallback_key = _component_name_key(fallback.get("component_name"))
        if fallback_key in seen_names:
            continue
        patched_components.append(fallback)
        seen_names.add(fallback_key)
        covered_boundaries.add(boundary_type)
    return patched_components


__all__ = [name for name in globals() if name != "__builtins__"]
