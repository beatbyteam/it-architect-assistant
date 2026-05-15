# ruff: noqa: E501
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from app.domain.architecture import validate_archimate_alignment
from app.integrations.generation.contracts import (
    REQUIRED_SECTION_CODES,
    GenerationSection,
    GenerationSectionReadiness,
    GenerationSolutionPayload,
    GenerationStructuredArchitectureModel,
)

from .payload_normalization_common import (
    SECTION_FIELD_ALIASES,
    SECTION_TITLE_BY_CODE,
    _clean_text_value,
    _extract_first_text,
    _extract_list_payload,
    _normalize_section_code_value,
    _sanitize_unconfirmed_architecture_terms,
    _tokenize_for_match,
    assess_section_readiness,
    build_section_fallback_body,
    derive_structured_architecture_model,
    normalize_architecture_boundary_type,
    should_apply_section_fallback,
)
from .payload_normalization_source_refs import (
    _deduplicate_source_ref_dicts,
    _normalize_source_refs,
)

if TYPE_CHECKING:
    from app.integrations.generation.llm_gateway import RetrievedFragment


ARCHITECTURE_SECTION_CODES = {
    "business_architecture",
    "data_architecture",
    "application_architecture",
    "technology_architecture",
}

ARCHIMATE_ALIGNMENT_HINTS = {
    "business_architecture": (
        "Business Process координирует поток согласования, Business Role отвечает за решения, "
        "Business Actor участвует в сценарии, а Business Service описывает бизнес-услугу."
    ),
    "data_architecture": (
        "Data Object фиксирует артефакты, версии, замечания и метаданные; Business Object "
        "описывает деловую запись, а Representation задает опубликованное представление документа."
    ),
    "application_architecture": (
        "Application Component реализует границу сервиса, Application Service предоставляет "
        "прикладную возможность, а Application Interface задает точку доступа."
    ),
    "technology_architecture": (
        "Node размещает среду исполнения, System Software поддерживает выполнение, "
        "Technology Service предоставляет платформенную возможность, а Artifact описывает развертываемый пакет."
    ),
}

SECTION_QUALITY_FALLBACK_MARKERS = (
    "dữ liệu",
    "node a",
    "node b",
    "node c",
    "archimate 3.2 alignment:",
    "business interface",
    "service document processing",
    "нескольких секунд",
    "пяти слоев",
    "пять слоев",
    "сисечт",
    "единый резерв",
    "нагрузочный тестовый процесс",
    "документацие",
    "mitigation:",
    "в артикуле",
    "сокрываются",
    "облачн",
    "cloud",
    "ландшаft",
    "репликасы",
    "проще всего",
    "postgresql",
    "redis",
    "amazon s3",
    "aws s3",
    "операционная система",
    "бизнес- 서비스",
)


def _ensure_allowed_archimate_marker(section_code: str, body_markdown: str) -> tuple[str, bool]:
    if section_code not in ARCHITECTURE_SECTION_CODES:
        return body_markdown, False
    alignment = validate_archimate_alignment(section_code, body_markdown)
    if alignment.get("has_allowed_content") and not alignment.get("disallowed_element_codes"):
        return body_markdown, False
    hint = ARCHIMATE_ALIGNMENT_HINTS.get(section_code)
    if not hint:
        return body_markdown, False
    body = _clean_text_value(body_markdown) or ""
    separator = "" if body.endswith((".", "!", "?")) else "."
    return f"{body}{separator} Соответствие ArchiMate 3.2: {hint}", True


def _repair_section_archimate_alignment(
    section_code: str,
    title: str,
    body_markdown: str,
    *,
    payload_context: dict[str, Any],
    task_title: str,
    task_text: str,
    context_items: list[str],
    retrieved_fragments: list[RetrievedFragment],
) -> tuple[str, bool]:
    if section_code not in ARCHITECTURE_SECTION_CODES:
        return body_markdown, False
    alignment = validate_archimate_alignment(section_code, body_markdown)
    if alignment.get("has_allowed_content") and not alignment.get("disallowed_element_codes"):
        return body_markdown, False

    candidates = [
        _build_section_body(section_code, title, payload_context),
        build_section_fallback_body(
            section_code,
            task_title=task_title,
            task_text=task_text,
            context_items=context_items,
            knowledge_fragments=retrieved_fragments,
        ),
    ]
    for candidate in candidates:
        cleaned_candidate = _clean_section_body_artifacts(candidate)
        candidate_alignment = validate_archimate_alignment(section_code, cleaned_candidate)
        if (
            candidate_alignment.get("has_allowed_content")
            and not candidate_alignment.get("disallowed_element_codes")
        ):
            return cleaned_candidate, cleaned_candidate != body_markdown

    fallback_body, _ = _ensure_allowed_archimate_marker(section_code, candidates[-1])
    return fallback_body, fallback_body != body_markdown


def _ensure_section_readiness_signals(
    section_code: str,
    body_markdown: str,
    readiness: dict[str, Any],
) -> tuple[str, bool]:
    missing_groups = set(readiness.get("missing_signal_groups") or [])
    hints_by_section = {
        "general_information": {
            "context": "Контекст и границы решения фиксируются для внутреннего корпоративного контура.",
            "stakeholders": "Заказчик, владелец процесса и пользователи подтверждают целевую область применения.",
            "target_state": "Цель и ожидаемый результат состоят в прозрачном согласовании и публикации актуальных версий.",
        },
        "business_tasks_description": {
            "goal": "Цель и ожидаемый результат задают сокращение времени согласования и повышение прозрачности.",
            "problem": "Проблема и бизнес-задача связаны с ручной передачей документов и отсутствием единого статуса.",
            "requirements": "Требования, KPI, SLA и сроки подлежат подтверждению на архитектурном согласовании.",
        },
        "it_architecture_content": {
            "solution_scope": "Архитектурный scope и границы решения охватывают бизнес-, data-, application- и technology-слои.",
            "components": "Компоненты решения включают сервис согласования, объекты данных и технологическую платформу.",
            "interactions": "Интеграции, API и flow данных связывают бизнес-процесс, приложение и хранилище.",
        },
        "business_architecture": {
            "actors": "Business Actor и Business Role включают пользователя, согласующего эксперта и владельца процесса.",
            "processes": "Business Process описывает workflow создания, согласования и публикации архитектурного артефакта.",
            "services": "Business Service предоставляет ценность и услугу управляемого согласования архитектурных документов.",
        },
        "data_architecture": {
            "data_assets": "Data Object и объект данных фиксируют артефакт, версию, замечание, статус и запись аудита.",
            "ownership": "Source, producer, consumer и владелец данных подлежат подтверждению для каждого Data Object.",
            "flows": "Data flow, API exchange, message или event описывают создание, чтение и обновление артефакта.",
        },
        "application_architecture": {
            "components": "Application Component и Application Service реализуют прикладной service согласования.",
            "interfaces": "Application Interface, API, endpoint, UI и web-точка доступа фиксируют внешние контракты.",
            "behavior": "Application Function, Application Process, workflow и integration описывают поведение приложения.",
        },
        "technology_architecture": {
            "platform": "Node, platform, host или серверная площадка подлежат подтверждению до финального развертывания.",
            "runtime": "System Software, runtime, container, broker или БД подлежат подтверждению как часть платформы.",
            "connectivity": (
                "Сетевая связность подлежит подтверждению: Network и Technology Interface "
                "фиксируют gateway, TLS и сетевой контур доступа без указания конкретной "
                "подсети, продукта или площадки до подтверждения инфраструктуры."
            ),
        },
        "additional_information": {
            "constraints": "Ограничения, constraint, policy и compliance фиксируются как условия дальнейшей детализации.",
            "risks": "Риски, risk, mitigation и зависимости ведутся с назначенными мерами реагирования.",
            "next_steps": "Следующие step, этап, roadmap и план уточнений закрывают открытые вопросы.",
        },
    }
    section_hints = hints_by_section.get(section_code, {})
    additions = [
        hint
        for group, hint in section_hints.items()
        if group in missing_groups and hint not in (body_markdown or "")
    ]
    if additions:
        body = _clean_text_value(body_markdown) or ""
        separator = "" if body.endswith((".", "!", "?")) else "."
        return f"{body}{separator} {' '.join(additions)}", True
    return body_markdown, False


def _section_duplicate_key(body_markdown: str | None) -> str:
    body = (body_markdown or "").casefold()
    return re.sub(r"[^a-zа-я0-9]+", " ", body).strip()


def _deduplicate_section_bodies(
    sections: list[GenerationSection],
    *,
    payload_context: dict[str, Any],
    task_title: str,
    task_text: str,
    context_items: list[str],
    retrieved_fragments: list[RetrievedFragment],
) -> tuple[list[GenerationSection], list[str]]:
    seen_bodies: set[str] = set()
    patched_sections: list[GenerationSection] = []
    deduplicated_codes: list[str] = []
    for section in sections:
        duplicate_key = _section_duplicate_key(section.body_markdown)
        if duplicate_key and duplicate_key in seen_bodies:
            section_body = _build_section_body(section.section_code, section.title, payload_context)
            if not section_body:
                section_body = build_section_fallback_body(
                    section.section_code,
                    task_title=task_title,
                    task_text=task_text,
                    context_items=context_items,
                    knowledge_fragments=retrieved_fragments,
                )
            section_body = f"{section.title}. {section_body}"
            section_body, _ = _ensure_section_mentions_declared_components(
                section.section_code,
                section_body,
                payload_context,
            )
            readiness = assess_section_readiness(
                section.section_code,
                task_text=task_text,
                context_items=context_items,
                knowledge_fragments=retrieved_fragments,
                section_body=section_body,
            )
            section_body, _ = _ensure_allowed_archimate_marker(
                section.section_code,
                section_body,
            )
            section_body, _ = _ensure_section_readiness_signals(
                section.section_code,
                section_body,
                readiness,
            )
            section = section.model_copy(update={"body_markdown": section_body})
            duplicate_key = _section_duplicate_key(section_body)
            deduplicated_codes.append(section.section_code)
        if duplicate_key:
            seen_bodies.add(duplicate_key)
        patched_sections.append(section)
    return patched_sections, deduplicated_codes


def _clean_section_body_artifacts(body_markdown: str | None) -> str:
    body = _sanitize_unconfirmed_architecture_terms(body_markdown) or ""
    body = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", body)
    body = body.replace("dữ liệu", "данных")
    body = re.sub(
        r"\bNode\s+[ABC]\b",
        "инфраструктурный узел, подлежит подтверждению",
        body,
        flags=re.IGNORECASE,
    )
    return _clean_text_value(body) or ""


def _section_body_needs_quality_fallback(body_markdown: str | None) -> bool:
    body = body_markdown or ""
    lowered = body.casefold()
    if any(marker in lowered for marker in SECTION_QUALITY_FALLBACK_MARKERS):
        return True
    return bool(re.search(r"(?m)^\s{0,3}#{1,6}\s*", body))


def _metadata_string_set(value: Any) -> set[str]:
    if isinstance(value, str):
        cleaned = _clean_text_value(value)
        return {cleaned} if cleaned else set()
    if isinstance(value, list | tuple | set):
        return {
            cleaned
            for cleaned in (_clean_text_value(item) for item in value)
            if cleaned
        }
    return set()


def _pick_fragment_for_section(
    *,
    section_code: str,
    section_title: str,
    body_markdown: str,
    retrieved_fragments: list[RetrievedFragment],
) -> RetrievedFragment | None:
    if not retrieved_fragments:
        return None

    section_tokens = _tokenize_for_match(
        " ".join(part for part in (section_code, section_title, body_markdown) if part)
    )
    body_tokens = _tokenize_for_match(body_markdown or "")
    generic_tokens = _tokenize_for_match(
        " ".join(part for part in (section_code, section_title) if part)
    )
    best_fragment: RetrievedFragment | None = None
    best_score = float("-inf")

    for index, fragment in enumerate(retrieved_fragments):
        fragment_text = " ".join(
            part for part in (fragment.title or "", fragment.content or "") if part
        )
        fragment_metadata = getattr(fragment, "metadata", {}) or {}
        section_tags = _metadata_string_set(fragment_metadata.get("section_tags"))
        architecture_layers = _metadata_string_set(
            fragment_metadata.get("architecture_layers")
        )
        metadata_section_match = section_code in section_tags or section_code in architecture_layers
        fragment_tokens = _tokenize_for_match(fragment_text)
        overlap_tokens = section_tokens.intersection(fragment_tokens)
        overlap_score = len(overlap_tokens)
        body_overlap = len(body_tokens.intersection(fragment_tokens))
        generic_overlap = len(generic_tokens.intersection(fragment_tokens))
        meaningful_overlap = max(overlap_score - generic_overlap, 0)
        if (
            not metadata_section_match
            and body_overlap <= 0
            and meaningful_overlap <= 0
            and overlap_score < 3
        ):
            continue

        lexical_score = float(fragment.lexical_score or 0.0)
        vector_score = float(fragment.vector_score or 0.0)
        retrieval_score = float(fragment.score or 0.0)
        score = (
            (5000 if metadata_section_match else 0)
            + body_overlap * 2000
            + meaningful_overlap * 1000
            + overlap_score * 250
            + lexical_score * 10
            + vector_score * 10
            + retrieval_score
            - index * 0.001
        )
        if score > best_score:
            best_score = score
            best_fragment = fragment

    return best_fragment


def _component_lines(
    payload: dict[str, Any],
    *,
    boundary: str,
    limit: int = 6,
) -> list[str]:
    components_raw = payload.get("components")
    components: list[Any] = components_raw if isinstance(components_raw, list) else []
    lines: list[str] = []
    for item in components:
        if not isinstance(item, dict):
            continue
        if normalize_architecture_boundary_type(item.get("boundary_type")) != boundary:
            continue
        component_name = _extract_first_text(
            item,
            ("component_name", "component_code", "name", "title"),
        )
        role_description = _extract_first_text(
            item,
            ("role_description", "description", "role", "purpose"),
        )
        if component_name and role_description:
            lines.append(f"{component_name}: {role_description}")
        elif component_name:
            lines.append(component_name)
        if len(lines) >= limit:
            break
    return lines


def _component_boundary_lookup(payload: dict[str, Any]) -> dict[str, str]:
    components_raw = payload.get("components")
    components: list[Any] = components_raw if isinstance(components_raw, list) else []
    lookup: dict[str, str] = {}
    for item in components:
        if not isinstance(item, dict):
            continue
        component_name = _extract_first_text(
            item,
            ("component_name", "component_code", "name", "title"),
        )
        boundary_type = normalize_architecture_boundary_type(item.get("boundary_type"))
        if component_name and boundary_type:
            lookup[component_name.casefold()] = boundary_type
    return lookup


def _integration_lines(
    payload: dict[str, Any],
    *,
    limit: int = 6,
    boundary: str | None = None,
) -> list[str]:
    integrations_raw = payload.get("integrations")
    integrations: list[Any] = integrations_raw if isinstance(integrations_raw, list) else []
    component_boundaries = _component_boundary_lookup(payload) if boundary else {}
    lines: list[str] = []
    for item in integrations:
        if not isinstance(item, dict):
            continue
        from_component = _extract_first_text(
            item,
            ("from_component", "source", "from", "producer"),
        )
        to_component = _extract_first_text(
            item,
            ("to_component", "target", "to", "consumer"),
        )
        interaction = _extract_first_text(
            item,
            ("interaction", "description", "flow", "purpose"),
        )
        protocol = _extract_first_text(item, ("protocol", "transport", "type"))
        if boundary and (
            component_boundaries.get((from_component or "").casefold()) != boundary
            and component_boundaries.get((to_component or "").casefold()) != boundary
        ):
            continue
        if from_component and to_component and interaction and protocol:
            lines.append(f"{from_component} -> {to_component}, протокол: {protocol}: {interaction}")
        elif from_component and to_component and interaction:
            lines.append(f"{from_component} -> {to_component}: {interaction}")
        elif from_component and to_component:
            lines.append(f"{from_component} -> {to_component}")
        if len(lines) >= limit:
            break
    return lines


def _risk_lines(payload: dict[str, Any], *, limit: int = 3) -> list[str]:
    risks_raw = payload.get("risks")
    risks: list[Any] = risks_raw if isinstance(risks_raw, list) else []
    lines: list[str] = []
    for item in risks[:limit]:
        if not isinstance(item, dict):
            continue
        risk_title = _extract_first_text(item, ("title", "name"))
        risk_description = _extract_first_text(
            item,
            ("description", "details", "summary"),
        )
        mitigation = _extract_first_text(item, ("mitigation", "action", "response"))
        if risk_title and risk_description and mitigation:
            lines.append(f"{risk_title}: {risk_description}. Мера реагирования: {mitigation}")
        elif risk_title and risk_description:
            lines.append(f"{risk_title}: {risk_description}")
    return lines


def _section_component_summary(section_code: str, payload: dict[str, Any]) -> str | None:
    if section_code not in ARCHITECTURE_SECTION_CODES:
        return None
    lines = _component_lines(payload, boundary=section_code, limit=8)
    if not lines:
        return None
    intro_by_section = {
        "business_architecture": "Объекты управления бизнес-слоя ArchiMate 3.2",
        "data_architecture": "Объекты управления слоя данных ArchiMate 3.2",
        "application_architecture": "Объекты управления прикладного слоя ArchiMate 3.2",
        "technology_architecture": "Объекты управления технологического слоя ArchiMate 3.2",
    }
    intro = intro_by_section.get(section_code, "Объекты управления ArchiMate 3.2")
    return f"{intro}: " + "; ".join(lines) + "."


def _ensure_section_mentions_declared_components(
    section_code: str,
    body_markdown: str,
    payload: dict[str, Any],
) -> tuple[str, bool]:
    summary = _section_component_summary(section_code, payload)
    if not summary:
        return body_markdown, False
    body = _clean_text_value(body_markdown) or ""
    component_lines = _component_lines(payload, boundary=section_code, limit=8)
    if component_lines and any(line.split(":", 1)[0].casefold() in body.casefold() for line in component_lines):
        return body, False
    separator = "" if body.endswith((".", "!", "?")) else "."
    return f"{body}{separator} {summary}", True


def _build_section_body(section_code: str, title: str, payload: dict[str, Any]) -> str:
    executive_summary = _clean_text_value(payload.get("executive_summary")) or ""
    assumptions_raw = payload.get("assumptions")
    assumptions: list[Any] = assumptions_raw if isinstance(assumptions_raw, list) else []
    next_steps_raw = payload.get("next_steps")
    next_steps: list[Any] = next_steps_raw if isinstance(next_steps_raw, list) else []

    title_text = title or section_code.replace("_", " ").title()
    integration_lines = _integration_lines(payload)
    risk_lines = _risk_lines(payload)

    if section_code == "general_information":
        parts = [
            part
            for part in (
                executive_summary,
                *[str(item) for item in assumptions[:2] if item],
            )
            if part
        ]
        if parts:
            return ". ".join(parts).rstrip(".") + "."

    if section_code == "business_tasks_description":
        parts = [
            "Раздел фиксирует целевую бизнес-задачу, границы процесса и ожидаемый результат."
        ]
        if executive_summary:
            parts.append(executive_summary)
        if assumptions:
            parts.append("Допущения: " + "; ".join(str(item) for item in assumptions[:3]))
        return " ".join(parts)

    if section_code == "it_architecture_content":
        return (
            "Раздел описывает состав ИТ-архитектуры в структуре TOGAF: бизнес-архитектуру, "
            "архитектуру данных, архитектуру приложений и технологическую архитектуру. "
            "Дальнейшие подразделы раскрывают объекты управления каждого слоя в терминах ArchiMate 3.2."
        )

    if section_code == "business_architecture":
        lines = _component_lines(payload, boundary="business_architecture")
        if lines:
            return (
                f"{title_text} описывает объекты бизнес-слоя ArchiMate 3.2: Business Process, Business Role, Business Actor и Business Service. Объекты слоя: "
                + "; ".join(lines)
                + "."
            )
        return (
            f"{title_text} описывает Business Process, Business Actor, Business Role и Business Service, "
            "которые требуются для целевого процесса согласования и публикации архитектурных артефактов."
        )

    if section_code == "data_architecture":
        parts = [
            "Раздел описывает Data Object, Business Object и Representation, а также правила владения, хранения и обмена данными."
        ]
        if integration_lines:
            data_integration_lines = _integration_lines(
                payload,
                boundary="data_architecture",
            )
            parts.append(
                "Ключевые потоки данных: " + "; ".join(data_integration_lines or integration_lines[:2])
            )
        data_component_lines = _component_lines(payload, boundary="data_architecture")
        if data_component_lines:
            parts.append("Объекты данных и хранилища: " + "; ".join(data_component_lines))
        return " ".join(parts)

    if section_code == "application_architecture":
        lines = _component_lines(payload, boundary="application_architecture")
        if lines:
            return (
                f"{title_text} описывает Application Component, Application Service и Application Interface. Объекты слоя: "
                + "; ".join(lines)
                + "."
            )
        return (
            f"{title_text} описывает Application Component, Application Service, Application Interface "
            "и их взаимодействия в целевом сервисе согласования."
        )

    if section_code == "technology_architecture":
        lines = _component_lines(payload, boundary="technology_architecture")
        if lines:
            return (
                f"{title_text} описывает Node, System Software, Technology Service и Artifact без неподтвержденной фиксации конкретной ОС. Объекты слоя: "
                + "; ".join(lines)
                + "."
            )
        return (
            f"{title_text} описывает Node, System Software, Technology Service, Network и Artifact, "
            "которые обеспечивают исполнение и эксплуатацию прикладного контура."
        )

    if section_code == "additional_information":
        additional_parts: list[str] = []
        if risk_lines:
            additional_parts.append("Риски и ограничения: " + "; ".join(risk_lines))
        if next_steps:
            additional_parts.append(
                "Следующие шаги: " + "; ".join(str(item) for item in next_steps[:3])
            )
        if assumptions and not additional_parts:
            additional_parts.append(
                "Допущения: " + "; ".join(str(item) for item in assumptions[:3])
            )
        if additional_parts:
            return " ".join(additional_parts)

    fallback_parts = [
        part
        for part in (
            executive_summary,
            "; ".join(integration_lines),
            "; ".join(risk_lines),
        )
        if part
    ]
    if fallback_parts:
        return ". ".join(fallback_parts).rstrip(".") + "."
    return (
        f"{title_text} описывает решение в канонической структуре TOGAF и фиксирует "
        "архитектурный контекст, который требуется уточнить на следующем шаге."
    )


def _default_section_title(section_code: str) -> str:
    return SECTION_TITLE_BY_CODE.get(section_code, section_code.replace("_", " ").title())


def _render_section_body_candidate(
    value: Any,
    *,
    section_code: str,
    payload: dict[str, Any],
) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _clean_text_value(value)
    if isinstance(value, dict):
        direct_text = _extract_first_text(
            value,
            (
                "body_markdown",
                "body",
                "content",
                "markdown",
                "text",
                "description",
                "details",
                "summary",
                "executive_summary",
                "general_information",
                "it_architecture_content",
            ),
        )
        if direct_text:
            return direct_text
        list_candidate = _extract_list_payload(
            value,
            wrapper_keys=(
                "items",
                "entries",
                "sections",
                "section_list",
                "components",
                "component_list",
                "integrations",
                "integration_list",
                "risks",
                "risk_list",
                "checks",
                "results",
            ),
            allow_mapping_values=True,
        )
        if list_candidate is not None:
            return _render_section_body_candidate(
                list_candidate,
                section_code=section_code,
                payload=payload,
            )
        return None
    if isinstance(value, list):
        lines: list[str] = []
        for item in value[:6]:
            if isinstance(item, str):
                cleaned = _clean_text_value(item)
                if cleaned:
                    lines.append(cleaned)
                continue
            if not isinstance(item, dict):
                cleaned = _clean_text_value(str(item))
                if cleaned:
                    lines.append(cleaned)
                continue

            if section_code in {
                "business_architecture",
                "application_architecture",
                "technology_architecture",
            }:
                component_name = _extract_first_text(
                    item,
                    ("component_name", "name", "title", "component_code", "mapping_key"),
                )
                role_description = _extract_first_text(
                    item,
                    ("role_description", "description", "role", "purpose", "details"),
                )
                if component_name and role_description:
                    lines.append(f"{component_name}: {role_description}")
                elif component_name:
                    lines.append(component_name)
                continue

            if section_code == "data_architecture":
                component_name = _extract_first_text(
                    item,
                    ("component_name", "name", "title", "component_code", "mapping_key"),
                )
                role_description = _extract_first_text(
                    item,
                    ("role_description", "description", "role", "purpose", "details"),
                )
                if component_name and role_description:
                    lines.append(f"{component_name}: {role_description}")
                    continue
                if component_name:
                    lines.append(component_name)
                    continue
                from_component = _extract_first_text(
                    item,
                    ("from_component", "source", "from", "producer", "mapping_key"),
                )
                to_component = _extract_first_text(
                    item,
                    ("to_component", "target", "to", "consumer", "destination"),
                )
                interaction = _extract_first_text(
                    item,
                    ("interaction", "description", "flow", "purpose", "details"),
                )
                protocol = _extract_first_text(item, ("protocol", "transport", "type"))
                if from_component and to_component and interaction and protocol:
                    lines.append(
                        f"{from_component} -> {to_component}, протокол: {protocol}: {interaction}"
                    )
                elif from_component and to_component and interaction:
                    lines.append(f"{from_component} -> {to_component}: {interaction}")
                elif from_component and to_component:
                    lines.append(f"{from_component} -> {to_component}")
                continue

            if section_code == "additional_information":
                title = _extract_first_text(
                    item,
                    ("title", "name", "label", "risk_title", "mapping_key"),
                )
                description = _extract_first_text(
                    item,
                    ("description", "details", "summary", "risk", "text"),
                )
                mitigation = _extract_first_text(
                    item,
                    ("mitigation", "action", "response", "plan"),
                )
                if title and description and mitigation:
                    lines.append(f"{title}: {description}. Мера реагирования: {mitigation}")
                elif title and description:
                    lines.append(f"{title}: {description}")
                elif description:
                    lines.append(description)
                continue

            generic_text = _extract_first_text(
                item,
                (
                    "title",
                    "name",
                    "label",
                    "summary",
                    "description",
                    "details",
                    "body_markdown",
                    "text",
                    "mapping_key",
                ),
            )
            if generic_text:
                lines.append(generic_text)
        joined = "; ".join(lines)
        return joined or None
    return None


def _resolve_section_body_from_payload(
    section_code: str,
    payload: dict[str, Any],
) -> str | None:
    for alias in SECTION_FIELD_ALIASES.get(section_code, (section_code,)):
        if alias not in payload:
            continue
        candidate = _render_section_body_candidate(
            payload.get(alias),
            section_code=section_code,
            payload=payload,
        )
        if candidate:
            return candidate
    return None


def _merge_section_records(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    base_title = _clean_text_value(merged.get("title"))
    incoming_title = _clean_text_value(incoming.get("title"))
    if not base_title and incoming_title:
        merged["title"] = incoming_title

    base_body = _clean_text_value(merged.get("body_markdown"))
    incoming_body = _clean_text_value(incoming.get("body_markdown"))
    if (
        not base_body
        and incoming_body
        or incoming_body
        and base_body
        and len(incoming_body) > len(base_body)
    ):
        merged["body_markdown"] = incoming_body

    merged_refs = _normalize_source_refs(merged.get("source_refs", []))
    incoming_refs = _normalize_source_refs(incoming.get("source_refs", []))
    merged["source_refs"] = _deduplicate_source_ref_dicts(merged_refs + incoming_refs)
    return merged


def _synthesize_missing_required_sections(payload: dict[str, Any]) -> list[dict[str, Any]]:
    existing_sections_raw = payload.get("sections")
    existing_sections: list[Any] = (
        existing_sections_raw if isinstance(existing_sections_raw, list) else []
    )
    merged_by_code: dict[str, dict[str, Any]] = {}

    for item in existing_sections:
        if not isinstance(item, dict):
            continue
        section = dict(item)
        section_code = _normalize_section_code_value(
            section.get("section_code"),
            title=(
                section.get("title")
                or section.get("name")
                or section.get("heading")
                or section.get("label")
            ),
        )
        if not section_code:
            continue
        section["section_code"] = section_code
        section.setdefault("title", _default_section_title(section_code))
        section["body_markdown"] = (
            _clean_text_value(section.get("body_markdown"))
            or _resolve_section_body_from_payload(section_code, payload)
            or _build_section_body(
                section_code,
                section.get("title") or _default_section_title(section_code),
                payload,
            )
        )
        section["source_refs"] = _normalize_source_refs(
            section.get("source_refs")
            or section.get("references")
            or section.get("citations")
            or section.get("evidence")
            or []
        )
        if section_code in merged_by_code:
            merged_by_code[section_code] = _merge_section_records(
                merged_by_code[section_code],
                section,
            )
            continue
        merged_by_code[section_code] = section

    for required_code in REQUIRED_SECTION_CODES:
        existing = merged_by_code.get(required_code)
        if existing is not None:
            existing["title"] = _clean_text_value(existing.get("title")) or _default_section_title(
                required_code
            )
            existing["body_markdown"] = (
                _clean_text_value(existing.get("body_markdown"))
                or _resolve_section_body_from_payload(required_code, payload)
                or _build_section_body(required_code, existing["title"], payload)
            )
            existing["source_refs"] = _normalize_source_refs(existing.get("source_refs", []))
            continue
        merged_by_code[required_code] = {
            "section_code": required_code,
            "title": _default_section_title(required_code),
            "body_markdown": (
                _resolve_section_body_from_payload(required_code, payload)
                or _build_section_body(
                    required_code,
                    _default_section_title(required_code),
                    payload,
                )
            ),
            "source_refs": [],
        }

    final_codes = [code for code in REQUIRED_SECTION_CODES if code in merged_by_code]
    return [merged_by_code[code] for code in final_codes]


def _normalize_sections(sections: Any, payload: dict[str, Any]) -> Any:
    if not isinstance(sections, list):
        return sections

    patched_sections: list[dict[str, Any] | Any] = []
    for item in sections:
        if not isinstance(item, dict):
            patched_sections.append(item)
            continue

        section = dict(item)
        normalized_section_code = _normalize_section_code_value(
            section.get("section_code"),
            title=(
                section.get("title")
                or section.get("name")
                or section.get("heading")
                or section.get("label")
            ),
        )
        if normalized_section_code:
            section["section_code"] = normalized_section_code
        if "title" not in section or not _clean_text_value(section.get("title")):
            section["title"] = (
                _extract_first_text(
                    section,
                    ("title", "name", "heading", "label"),
                )
                or (_clean_text_value(section.get("section_code")) or "Section").title()
            )
        body_value = _extract_first_text(
            section,
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
        if body_value is None:
            body_value = _build_section_body(
                _clean_text_value(section.get("section_code")) or "section",
                section.get("title") or "Section",
                payload,
            )
        section["body_markdown"] = body_value
        source_refs_value = section.get("source_refs")
        if source_refs_value is None:
            for alias in ("references", "citations", "evidence", "source_ref"):
                if alias in section:
                    source_refs_value = section.get(alias)
                    break
        section["source_refs"] = _normalize_source_refs(source_refs_value or [])
        patched_sections.append(section)
    return patched_sections


def _apply_section_guidance(
    result: GenerationSolutionPayload,
    *,
    task_title: str,
    task_text: str,
    context_items: list[str],
    retrieved_fragments: list[RetrievedFragment],
) -> tuple[GenerationSolutionPayload, dict[str, Any]]:
    payload_context = result.model_dump(mode="python")
    patched_sections: list[GenerationSection] = []
    readiness_payloads: list[GenerationSectionReadiness] = []
    fallback_sections: list[str] = []
    archimate_alignment_sections: list[str] = []
    component_alignment_sections: list[str] = []
    readiness_signal_sections: list[str] = []
    deduplicated_section_codes: list[str] = []

    for section in result.sections:
        section_body = _clean_section_body_artifacts(section.body_markdown)
        if section_body != section.body_markdown:
            section = section.model_copy(update={"body_markdown": section_body})
        readiness = assess_section_readiness(
            section.section_code,
            task_text=task_text,
            context_items=context_items,
            knowledge_fragments=retrieved_fragments,
            section_body=section.body_markdown,
        )
        fallback_applied = False
        if should_apply_section_fallback(
            section.section_code, section_body, readiness
        ) or _section_body_needs_quality_fallback(section.body_markdown):
            section_body = _build_section_body(
                section.section_code,
                section.title,
                payload_context,
            )
            if not section_body:
                section_body = build_section_fallback_body(
                    section.section_code,
                    task_title=task_title,
                    task_text=task_text,
                    context_items=context_items,
                    knowledge_fragments=retrieved_fragments,
                )
            section = section.model_copy(update={"body_markdown": section_body})
            readiness = assess_section_readiness(
                section.section_code,
                task_text=task_text,
                context_items=context_items,
                knowledge_fragments=retrieved_fragments,
                section_body=section_body,
            )
            fallback_applied = True
            fallback_sections.append(section.section_code)

        section_body, component_alignment_applied = _ensure_section_mentions_declared_components(
            section.section_code,
            section_body,
            payload_context,
        )
        if component_alignment_applied:
            section = section.model_copy(update={"body_markdown": section_body})
            readiness = assess_section_readiness(
                section.section_code,
                task_text=task_text,
                context_items=context_items,
                knowledge_fragments=retrieved_fragments,
                section_body=section_body,
            )
            component_alignment_sections.append(section.section_code)

        alignment = validate_archimate_alignment(section.section_code, section_body)
        if (
            section.section_code in ARCHITECTURE_SECTION_CODES
            and alignment.get("disallowed_element_codes")
        ):
            section_body = _build_section_body(
                section.section_code,
                section.title,
                payload_context,
            )
            section = section.model_copy(update={"body_markdown": section_body})
            readiness = assess_section_readiness(
                section.section_code,
                task_text=task_text,
                context_items=context_items,
                knowledge_fragments=retrieved_fragments,
                section_body=section_body,
            )
            fallback_applied = True
            if section.section_code not in fallback_sections:
                fallback_sections.append(section.section_code)

        section_body, archimate_alignment_applied = _ensure_allowed_archimate_marker(
            section.section_code,
            section_body,
        )
        if archimate_alignment_applied:
            section = section.model_copy(update={"body_markdown": section_body})
            readiness = assess_section_readiness(
                section.section_code,
                task_text=task_text,
                context_items=context_items,
                knowledge_fragments=retrieved_fragments,
                section_body=section_body,
            )
            archimate_alignment_sections.append(section.section_code)

        section_body, readiness_signal_applied = _ensure_section_readiness_signals(
            section.section_code,
            section_body,
            readiness,
        )
        if readiness_signal_applied:
            section = section.model_copy(update={"body_markdown": section_body})
            readiness = assess_section_readiness(
                section.section_code,
                task_text=task_text,
                context_items=context_items,
                knowledge_fragments=retrieved_fragments,
                section_body=section_body,
            )
            readiness_signal_sections.append(section.section_code)

        readiness["fallback_applied"] = fallback_applied
        readiness["archimate_alignment_applied"] = archimate_alignment_applied
        readiness_payloads.append(GenerationSectionReadiness.model_validate(readiness))
        patched_sections.append(section)

    patched_sections, deduplicated_section_codes = _deduplicate_section_bodies(
        patched_sections,
        payload_context=payload_context,
        task_title=task_title,
        task_text=task_text,
        context_items=context_items,
        retrieved_fragments=retrieved_fragments,
    )
    final_patched_sections: list[GenerationSection] = []
    for section in patched_sections:
        section_body, final_alignment_applied = _repair_section_archimate_alignment(
            section.section_code,
            section.title,
            section.body_markdown,
            payload_context=payload_context,
            task_title=task_title,
            task_text=task_text,
            context_items=context_items,
            retrieved_fragments=retrieved_fragments,
        )
        if final_alignment_applied:
            section = section.model_copy(update={"body_markdown": section_body})
            if section.section_code not in archimate_alignment_sections:
                archimate_alignment_sections.append(section.section_code)
            if section.section_code not in fallback_sections:
                fallback_sections.append(section.section_code)
        final_patched_sections.append(section)
    patched_sections = final_patched_sections

    readiness_payloads = []
    for section in patched_sections:
        readiness = assess_section_readiness(
            section.section_code,
            task_text=task_text,
            context_items=context_items,
            knowledge_fragments=retrieved_fragments,
            section_body=section.body_markdown,
        )
        readiness["fallback_applied"] = (
            section.section_code in fallback_sections
            or section.section_code in deduplicated_section_codes
        )
        readiness["archimate_alignment_applied"] = (
            section.section_code in archimate_alignment_sections
        )
        readiness_payloads.append(GenerationSectionReadiness.model_validate(readiness))

    patched_result = result.model_copy(update={"sections": patched_sections})
    structured_model = GenerationStructuredArchitectureModel.model_validate(
        derive_structured_architecture_model(patched_result)
    )
    patched_result = patched_result.model_copy(
        update={
            "section_readiness": readiness_payloads,
            "structured_model": structured_model,
        }
    )

    section_status_counts: dict[str, int] = {}
    for item in readiness_payloads:
        section_status_counts[item.status] = section_status_counts.get(item.status, 0) + 1
    return patched_result, {
            "fallback_sections": fallback_sections,
            "archimate_alignment_sections": archimate_alignment_sections,
            "component_alignment_sections": component_alignment_sections,
            "readiness_signal_sections": readiness_signal_sections,
            "deduplicated_section_codes": deduplicated_section_codes,
            "section_status_counts": section_status_counts,
        "structured_model": {
            "version": structured_model.version,
            "entity_count": len(structured_model.entities),
            "relation_count": len(structured_model.relations),
            "section_count": len(structured_model.section_summaries),
        },
    }


__all__ = [name for name in globals() if name != "__builtins__"]
