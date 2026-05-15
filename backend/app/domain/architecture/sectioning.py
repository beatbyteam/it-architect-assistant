from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

from .standards import (
    ARCHIMATE_LOOKUP,
    REQUIRED_TOGAF_SECTION_CODES,
    SECTION_ARCHIMATE_WHITELIST,
    TOGAF_SECTION_LOOKUP,
    extract_archimate_elements,
    normalize_architecture_boundary_type,
    render_togaf_heading,
)


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.strip().split())
    return " ".join(str(value).strip().split())


def _tokenize(value: str) -> set[str]:
    normalized = re.sub(r"[^\w\-]+", " ", value.casefold(), flags=re.UNICODE)
    return {token for token in normalized.split() if len(token) >= 3}


@dataclass(frozen=True, slots=True)
class SectionSignalGroup:
    name: str
    keywords: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SectionGenerationGuide:
    code: str
    purpose: str
    signal_groups: tuple[SectionSignalGroup, ...]
    fallback_focus: str


SECTION_GENERATION_GUIDES: Final[dict[str, SectionGenerationGuide]] = {
    "general_information": SectionGenerationGuide(
        code="general_information",
        purpose="Зафиксировать общие сведения, контекст, границы решения и исходные условия.",
        signal_groups=(
            SectionSignalGroup(
                "context", ("контекст", "context", "as is", "теку", "исход", "scope", "границ")
            ),
            SectionSignalGroup(
                "stakeholders", ("заказчик", "пользоват", "stakeholder", "owner", "владел")
            ),
            SectionSignalGroup(
                "target_state", ("результат", "outcome", "target", "эффект", "цель")
            ),
        ),
        fallback_focus="Укажи контекст, границы рассмотрения и известные ограничения исходной постановки.",
    ),
    "business_tasks_description": SectionGenerationGuide(
        code="business_tasks_description",
        purpose="Сформулировать бизнес-задачи, ожидаемый эффект и критерии результата.",
        signal_groups=(
            SectionSignalGroup("goal", ("цель", "goal", "outcome", "результат", "эффект")),
            SectionSignalGroup("problem", ("проблем", "pain", "issue", "задач", "необходимо")),
            SectionSignalGroup("requirements", ("требован", "requirement", "kpi", "sla", "срок")),
        ),
        fallback_focus="Опиши деловую цель, проблематику и критерии успеха без технических деталей.",
    ),
    "it_architecture_content": SectionGenerationGuide(
        code="it_architecture_content",
        purpose="Дать сводный взгляд на архитектурный контур и границы решения.",
        signal_groups=(
            SectionSignalGroup(
                "solution_scope", ("архитектур", "solution", "контур", "scope", "границ")
            ),
            SectionSignalGroup(
                "components", ("компонент", "component", "сервис", "service", "system")
            ),
            SectionSignalGroup("interactions", ("интеграц", "interaction", "flow", "api", "данн")),
        ),
        fallback_focus="Собери сводную картину решения и перечисли, какие слои будут раскрыты далее.",
    ),
    "business_architecture": SectionGenerationGuide(
        code="business_architecture",
        purpose="Описать бизнес-слой через объекты ArchiMate 3.2: роли, процессы, сервисы, события и объекты бизнеса.",
        signal_groups=(
            SectionSignalGroup("actors", ("role", "actor", "пользоват", "бизнес", "подраздел")),
            SectionSignalGroup(
                "processes", ("process", "процесс", "function", "функц", "workflow")
            ),
            SectionSignalGroup("services", ("service", "сервис", "capability", "услуг", "value")),
        ),
        fallback_focus="Используй только бизнес-объекты ArchiMate 3.2 и объясни, кто выполняет процесс и какой Business Service предоставляется.",
    ),
    "data_architecture": SectionGenerationGuide(
        code="data_architecture",
        purpose="Описать объекты данных, источники, потребители и потоки обмена.",
        signal_groups=(
            SectionSignalGroup(
                "data_assets", ("данн", "data", "entity", "объект", "record", "реестр")
            ),
            SectionSignalGroup(
                "ownership", ("владел", "source", "producer", "consumer", "owner", "получат")
            ),
            SectionSignalGroup(
                "flows", ("flow", "exchange", "message", "event", "sync", "batch", "api")
            ),
        ),
        fallback_focus="Назови Data Object, источники и потребителей, а также как данные создаются, хранятся и передаются.",
    ),
    "application_architecture": SectionGenerationGuide(
        code="application_architecture",
        purpose="Описать прикладной слой через Application Component, Application Service, интерфейсы и процессы.",
        signal_groups=(
            SectionSignalGroup(
                "components", ("component", "module", "system", "service", "приложен", "api")
            ),
            SectionSignalGroup(
                "interfaces", ("interface", "endpoint", "api", "ui", "web", "mobile")
            ),
            SectionSignalGroup(
                "behavior", ("function", "process", "workflow", "orchestration", "integration")
            ),
        ),
        fallback_focus="Покажи какие Application Component и Application Service реализуют решение и как они взаимодействуют.",
    ),
    "technology_architecture": SectionGenerationGuide(
        code="technology_architecture",
        purpose="Описать технологический слой через Node, Device, System Software, Network и Technology Service.",
        signal_groups=(
            SectionSignalGroup(
                "platform", ("platform", "node", "host", "сервер", "cluster", "k8s", "vm", "cloud")
            ),
            SectionSignalGroup(
                "runtime",
                ("postgres", "redis", "broker", "system software", "os", "runtime", "container"),
            ),
            SectionSignalGroup(
                "connectivity", ("network", "lb", "gateway", "firewall", "tls", "vpn", "subnet")
            ),
        ),
        fallback_focus="Покажи на каких Node и System Software исполняется решение и какие Technology Service доступны приложениям.",
    ),
    "additional_information": SectionGenerationGuide(
        code="additional_information",
        purpose="Собрать ограничения, допущения, риски, открытые вопросы и дальнейшие шаги.",
        signal_groups=(
            SectionSignalGroup(
                "constraints", ("огранич", "constraint", "limitation", "policy", "compliance")
            ),
            SectionSignalGroup("risks", ("risk", "риск", "mitigation", "зависим", "uncertainty")),
            SectionSignalGroup("next_steps", ("step", "этап", "roadmap", "следующ", "план")),
        ),
        fallback_focus="Явно зафиксируй ограничения, риски и действия, необходимые для доведения решения до целевого состояния.",
    ),
}


PLACEHOLDER_MARKERS: Final[tuple[str, ...]] = (
    "todo",
    "tbd",
    "placeholder",
    "template",
    "шаблон",
    "пример заполнения",
)


SECTION_DEFAULT_ELEMENT_HINTS: Final[dict[str, tuple[str, ...]]] = {
    code: tuple(
        ARCHIMATE_LOOKUP[item].title
        for item in SECTION_ARCHIMATE_WHITELIST.get(code, ())
        if item in ARCHIMATE_LOOKUP
    )
    for code in REQUIRED_TOGAF_SECTION_CODES
}


def section_generation_plan_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for code in REQUIRED_TOGAF_SECTION_CODES:
        guide = SECTION_GENERATION_GUIDES[code]
        records.append(
            {
                "section_code": code,
                "heading": render_togaf_heading(code),
                "purpose": guide.purpose,
                "fallback_focus": guide.fallback_focus,
                "allowed_archimate_elements": list(SECTION_DEFAULT_ELEMENT_HINTS.get(code, ())),
                "signal_groups": [
                    {"name": group.name, "keywords": list(group.keywords)}
                    for group in guide.signal_groups
                ],
            }
        )
    return records


def _knowledge_text(knowledge_fragments: list[Any] | None) -> str:
    parts: list[str] = []
    for item in knowledge_fragments or []:
        if isinstance(item, dict):
            parts.append(_clean_text(item.get("content")))
            continue
        parts.append(_clean_text(getattr(item, "content", None)))
    return "\n".join(part for part in parts if part)


def assess_section_readiness(
    section_code: str,
    *,
    task_text: str,
    context_items: list[str] | None = None,
    knowledge_fragments: list[Any] | None = None,
    section_body: str | None = None,
) -> dict[str, Any]:
    guide = SECTION_GENERATION_GUIDES[section_code]
    text_blocks = [
        task_text,
        "\n".join(context_items or []),
        _knowledge_text(knowledge_fragments),
        section_body or "",
    ]
    combined_text = "\n".join(block for block in text_blocks if block)
    normalized = combined_text.casefold()
    observed_groups: list[str] = []
    missing_groups: list[str] = []
    for group in guide.signal_groups:
        if any(keyword in normalized for keyword in group.keywords):
            observed_groups.append(group.name)
        else:
            missing_groups.append(group.name)
    score = round(len(observed_groups) / max(len(guide.signal_groups), 1), 3)
    if score >= 0.8:
        status = "ready"
    elif score >= 0.45:
        status = "partial"
    else:
        status = "insufficient"
    reasons: list[str] = []
    if missing_groups:
        reasons.append(f"Недостаточно сигналов по аспектам: {', '.join(missing_groups)}.")
    if section_body:
        cleaned_body = _clean_text(section_body)
        if len(cleaned_body) < 80:
            reasons.append(
                "Текст секции получился слишком коротким для устойчивой архитектурной интерпретации."
            )
        lowered_body = cleaned_body.casefold()
        if any(marker in lowered_body for marker in PLACEHOLDER_MARKERS):
            reasons.append(
                "В секции обнаружены шаблонные или технические маркеры вместо содержательного описания."
            )
        allowed = set(SECTION_ARCHIMATE_WHITELIST.get(section_code, ()))
        if allowed and not (extract_archimate_elements(cleaned_body) & allowed):
            reasons.append("В тексте нет явных ArchiMate-объектов, допустимых для этого слоя.")
    return {
        "section_code": section_code,
        "heading": render_togaf_heading(section_code),
        "status": status,
        "score": score,
        "observed_signal_groups": observed_groups,
        "missing_signal_groups": missing_groups,
        "minimum_signal_count": len(guide.signal_groups),
        "observed_signal_count": len(observed_groups),
        "reasons": reasons,
        "allowed_archimate_elements": list(SECTION_DEFAULT_ELEMENT_HINTS.get(section_code, ())),
    }


def _section_context_excerpt(
    task_title: str, task_text: str, context_items: list[str] | None
) -> str:
    context_text = "; ".join(item for item in (context_items or []) if _clean_text(item))
    excerpt = _clean_text(task_text)
    if len(excerpt) > 360:
        excerpt = excerpt[:357].rstrip() + "..."
    if context_text:
        return f"{task_title}: {excerpt} Дополнительный контекст: {context_text}."
    return f"{task_title}: {excerpt}."


def build_section_fallback_body(
    section_code: str,
    *,
    task_title: str,
    task_text: str,
    context_items: list[str] | None = None,
    knowledge_fragments: list[Any] | None = None,
) -> str:
    heading = render_togaf_heading(section_code)
    excerpt = _section_context_excerpt(task_title, task_text, context_items)
    knowledge_titles: list[str] = []
    for item in knowledge_fragments or []:
        title = item.get("title") if isinstance(item, dict) else getattr(item, "title", None)
        cleaned = _clean_text(title)
        if cleaned and cleaned not in knowledge_titles:
            knowledge_titles.append(cleaned)
        if len(knowledge_titles) >= 3:
            break
    basis_sentence = ""
    if knowledge_titles:
        basis_sentence = (
            f" В качестве опорных материалов использованы: {', '.join(knowledge_titles)}."
        )
    allowed_titles = ", ".join(SECTION_DEFAULT_ELEMENT_HINTS.get(section_code, ())[:4])

    if section_code == "general_information":
        return (
            f"{heading}. {excerpt} Раздел фиксирует исходный контекст, рамки решения, заинтересованные стороны и условия, "
            f"которые уже просматриваются в постановке. Для итоговой редакции потребуется уточнить организационные границы, "
            f"приоритеты заказчика и связь решения с текущим контуром ИТ-ландшафта.{basis_sentence}"
        )
    if section_code == "business_tasks_description":
        return (
            f"{heading}. На основании постановки задачи выделяется целевой бизнес-результат и ожидаемый операционный эффект. "
            f"{excerpt} В текущей версии зафиксированы деловая цель, проблематика и ориентиры по результату; для полной детализации "
            f"понадобится уточнить KPI, SLA, сроки и критерии приемки.{basis_sentence}"
        )
    if section_code == "it_architecture_content":
        return (
            f"{heading}. Архитектурный контур решения описывается как связка бизнес-, data-, application- и technology-слоев. "
            f"{excerpt} Ниже по документу каждый слой раскрывается отдельно; на данном уровне фиксируются границы решения, основные участники, "
            f"ключевые потоки данных и опорные технологические платформы.{basis_sentence}"
        )
    if section_code == "business_architecture":
        return (
            f"{heading}. В бизнес-слое используются только допустимые объекты ArchiMate 3.2: {allowed_titles}. "
            f"{excerpt} На текущем уровне детализации базовая модель исходит из того, что Business Actor и Business Role инициируют Business Process, "
            f"результатом которого становится Business Service для целевого пользователя. До финального согласования требуется уточнить состав ролей, "
            f"точки ответственности и бизнес-события, запускающие процесс.{basis_sentence}"
        )
    if section_code == "data_architecture":
        return (
            f"{heading}. Раздел фиксирует объекты данных и их движение между участниками решения. В рамках допустимой метамодели используются {allowed_titles}. "
            f"{excerpt} Базовый вариант предполагает выделение Data Object, определение источника записи, потребителя данных и канала передачи. Для завершения секции "
            f"нужно уточнить владельца данных, требования к качеству и режим синхронизации.{basis_sentence}"
        )
    if section_code == "application_architecture":
        return (
            f"{heading}. Прикладной слой описывается через объекты ArchiMate 3.2: {allowed_titles}. {excerpt} Базовая композиция предполагает, что Application Component "
            f"реализует прикладную функцию и публикует Application Service через явный интерфейс. Для точной схемы надо дополнить перечень систем, API и распределение ответственности "
            f"между сервисами.{basis_sentence}"
        )
    if section_code == "technology_architecture":
        return (
            f"{heading}. Технологический слой раскрывается через допустимые объекты ArchiMate 3.2: {allowed_titles}. {excerpt} На текущем уровне можно зафиксировать Node, "
            f"System Software и Technology Service, на которых будет исполняться прикладной контур. Для окончательной версии требуется уточнить инфраструктурную площадку, сетевые связи, "
            f"средства защиты и эксплуатационные ограничения.{basis_sentence}"
        )
    if section_code == "additional_information":
        return (
            f"{heading}. Здесь собраны ограничения, допущения, риски и шаги по доработке решения. {excerpt} До выпуска финальной версии необходимо зафиксировать регуляторные ограничения, "
            f"технические зависимости, риски по интеграциям и план уточнения спорных мест, чтобы дальнейшая генерация не заполняла пробелы предположениями.{basis_sentence}"
        )
    return f"{heading}. {excerpt}"


def should_apply_section_fallback(
    section_code: str, section_body: str | None, readiness: dict[str, Any]
) -> bool:
    cleaned_body = _clean_text(section_body)
    if not cleaned_body:
        return True
    if len(cleaned_body) < 80:
        return True
    lowered = cleaned_body.casefold()
    if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
        return True
    return readiness.get("status") == "insufficient"


def default_archimate_element_for_boundary(
    boundary_type: str | None, role_description: str | None = None
) -> str | None:
    boundary = normalize_architecture_boundary_type(boundary_type)
    role_text = _clean_text(role_description)
    detected = extract_archimate_elements(role_text)
    allowed = set(SECTION_ARCHIMATE_WHITELIST.get(boundary or "", ()))
    if detected & allowed:
        return sorted(detected & allowed)[0]
    defaults = {
        "business_architecture": "business_service",
        "data_architecture": "data_object",
        "application_architecture": "application_component",
        "technology_architecture": "node",
    }
    return defaults.get(boundary or "")


def derive_structured_architecture_model(payload: Any) -> dict[str, Any]:
    sections = list(getattr(payload, "sections", []) or [])
    components = list(getattr(payload, "components", []) or [])
    integrations = list(getattr(payload, "integrations", []) or [])
    section_index = {
        getattr(section, "section_code", None): section
        for section in sections
        if getattr(section, "section_code", None)
    }
    entities: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    entity_id_by_component: dict[str, str] = {}
    skipped_relation_count = 0

    for index, component in enumerate(components, start=1):
        component_name = (
            _clean_text(getattr(component, "component_name", None)) or f"component_{index}"
        )
        boundary = normalize_architecture_boundary_type(getattr(component, "boundary_type", None))
        element_code = default_archimate_element_for_boundary(
            boundary, getattr(component, "role_description", None)
        )
        entity_id = f"component:{index}:{re.sub(r'[^a-z0-9]+', '-', component_name.casefold()).strip('-') or index}"
        entity_id_by_component[component_name] = entity_id
        entities.append(
            {
                "entity_id": entity_id,
                "name": component_name,
                "source_kind": "component",
                "section_code": boundary,
                "layer": ARCHIMATE_LOOKUP[element_code].layer
                if element_code and element_code in ARCHIMATE_LOOKUP
                else None,
                "archimate_element_code": element_code,
                "archimate_element_title": ARCHIMATE_LOOKUP[element_code].title
                if element_code and element_code in ARCHIMATE_LOOKUP
                else None,
                "confidence": 0.95 if element_code else 0.5,
                "external_flag": bool(getattr(component, "external_flag", False)),
                "technology_stack": _clean_text(getattr(component, "technology_stack", None))
                or None,
                "description": _clean_text(getattr(component, "role_description", None)) or None,
            }
        )

    for code in REQUIRED_TOGAF_SECTION_CODES:
        section = section_index.get(code)
        if section is None:
            continue
        detected = sorted(
            extract_archimate_elements(_clean_text(getattr(section, "body_markdown", None)))
        )
        entities.append(
            {
                "entity_id": f"section:{code}",
                "name": TOGAF_SECTION_LOOKUP[code].title,
                "source_kind": "section",
                "section_code": code,
                "layer": None,
                "archimate_element_code": None,
                "archimate_element_title": None,
                "confidence": 1.0,
                "detected_archimate_elements": detected,
                "description": _clean_text(getattr(section, "body_markdown", None))[:300] or None,
            }
        )

    for index, integration in enumerate(integrations, start=1):
        source_name = _clean_text(getattr(integration, "from_component", None))
        target_name = _clean_text(getattr(integration, "to_component", None))
        source_entity_id = entity_id_by_component.get(source_name)
        target_entity_id = entity_id_by_component.get(target_name)
        if source_entity_id is None or target_entity_id is None:
            skipped_relation_count += 1
            continue
        relations.append(
            {
                "relation_id": f"integration:{index}",
                "relation_type": "flow",
                "section_code": "data_architecture",
                "source_entity_id": source_entity_id,
                "target_entity_id": target_entity_id,
                "description": _clean_text(getattr(integration, "interaction", None)) or None,
                "protocol": _clean_text(getattr(integration, "protocol", None)) or None,
                "confidence": 0.9,
            }
        )

    section_summaries: list[dict[str, Any]] = []
    for code in REQUIRED_TOGAF_SECTION_CODES:
        section = section_index.get(code)
        body = _clean_text(getattr(section, "body_markdown", None)) if section is not None else ""
        detected = sorted(extract_archimate_elements(body))
        section_summaries.append(
            {
                "section_code": code,
                "heading": render_togaf_heading(code),
                "body_length": len(body),
                "allowed_archimate_elements": list(SECTION_DEFAULT_ELEMENT_HINTS.get(code, ())),
                "detected_archimate_elements": [
                    ARCHIMATE_LOOKUP[item].title for item in detected if item in ARCHIMATE_LOOKUP
                ],
                "component_count": sum(
                    1
                    for entity in entities
                    if entity.get("source_kind") == "component"
                    and entity.get("section_code") == code
                ),
            }
        )

    return {
        "version": "sectioned-architecture-model.v1",
        "entities": entities,
        "relations": relations,
        "section_summaries": section_summaries,
        "diagnostics": {
            "entity_count": len(entities),
            "relation_count": len(relations),
            "skipped_relation_count": skipped_relation_count,
            "component_entity_count": sum(
                1 for entity in entities if entity.get("source_kind") == "component"
            ),
            "section_entity_count": sum(
                1 for entity in entities if entity.get("source_kind") == "section"
            ),
        },
    }
