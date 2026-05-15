# ruff: noqa: E501
from __future__ import annotations

from typing import Any

from app.integrations.generation.contracts import GenerationSolutionPayload

from .payload_normalization_common import (
    _clean_text_value,
    _deduplicate_texts,
    _split_sentences,
)
from .payload_normalization_validation import _coerce_generation_solution_payload


def _derive_assumptions_from_task(
    *, task_text: str, context_items: list[str], payload: GenerationSolutionPayload
) -> list[str]:
    combined_parts = [task_text, *context_items]
    combined_text = "\n".join(part for part in combined_parts if part).strip()
    lowered = combined_text.lower()
    candidates: list[str] = []

    if any(
        marker in lowered
        for marker in (
            "внутрен",
            "корпоратив",
            "internal",
            "on-prem",
            "он-прем",
            "без обязательной зависимости от внешних облачных сервисов",
        )
    ):
        candidates.append(
            "Решение разворачивается во внутреннем корпоративном контуре и не требует обязательной зависимости от внешних облачных сервисов."
        )
    if any(
        marker in lowered
        for marker in (
            "sso",
            "ldap",
            "ad",
            "reverse proxy",
            "авторизац",
            "аутентификац",
            "каталог пользователей",
        )
    ):
        candidates.append(
            "Аутентификация и роли предоставляются корпоративным SSO/LDAP/AD или доверенным reverse proxy, без локального хранения учётных данных приложения."
        )
    if any(
        marker in lowered
        for marker in (
            "объект",
            "файлов",
            "хранилищ",
            "postgres",
            "postgre",
            "резерв",
            "backup",
            "документ",
            "metadata",
            "метадан",
        )
    ):
        candidates.append(
            "Метаданные и документы размещаются в управляемых корпоративных хранилищах с резервным копированием и контролем доступа."
        )
    if any(marker in lowered for marker in ("почт", "уведом", "notification", "email", "mail")):
        candidates.append(
            "Корпоративная почта или внутренний сервис уведомлений доступны для доставки событий о статусах согласования и замечаниях."
        )
    if any(
        marker in lowered
        for marker in (
            "api",
            "интегра",
            "портал",
            "внешними внутренними системами",
            "rest",
            "grpc",
            "webhook",
        )
    ):
        candidates.append(
            "Внутренние интеграции доступны по управляемым API внутри корпоративного контура и могут быть использованы без выхода во внешний интернет."
        )
    if any(
        marker in lowered
        for marker in ("масштаб", "одноврем", "пользовател", "нагруз", "3 секунд", "секунд")
    ):
        candidates.append(
            "Контур допускает горизонтальное масштабирование application layer и способен выдерживать заявленную пользовательскую и транзакционную нагрузку после профильной настройки инфраструктуры."
        )

    if not candidates:
        component_names = ", ".join(
            component.component_name for component in payload.components[:3]
        )
        if component_names:
            candidates.append(
                f"Ключевые зависимости и компоненты решения ({component_names}) доступны в целевом корпоративном контуре и могут быть внедрены без изменения базовых ограничений задачи."
            )
        else:
            candidates.append(
                "Базовые корпоративные зависимости, описанные во входе задачи, доступны и могут быть использованы через управляемые внутренние интеграции."
            )

    return _deduplicate_texts(candidates)[:3]


def _derive_next_steps_from_task(
    *, task_text: str, context_items: list[str], payload: GenerationSolutionPayload
) -> list[str]:
    combined_text = "\n".join(part for part in [task_text, *context_items] if part).strip().lower()
    candidates: list[str] = []

    if any(
        marker in combined_text
        for marker in ("api", "интегра", "портал", "ldap", "ad", "sso", "уведом")
    ):
        candidates.append(
            "Согласовать детальные API-контракты и интеграционные сценарии для SSO/LDAP/AD, уведомлений, публикации и внешнего чтения опубликованных артефактов."
        )
    if any(
        marker in combined_text
        for marker in (
            "версион",
            "замечан",
            "аудит",
            "метадан",
            "документ",
            "publication",
            "публикац",
        )
    ):
        candidates.append(
            "Уточнить физическую модель данных и жизненный цикл сущностей: артефакт, версия, замечание, маршрут, публикация и событие аудита."
        )
    if any(
        marker in combined_text
        for marker in ("нагруз", "масштаб", "3 секунд", "секунд", "300", "5000", "резерв")
    ):
        candidates.append(
            "Подготовить нефункциональный дизайн: профиль нагрузки, резервное копирование, отказоустойчивость, RPO/RTO и критерии горизонтального масштабирования application layer."
        )

    if not candidates:
        component_names = ", ".join(
            component.component_name for component in payload.components[:3]
        )
        if component_names:
            candidates.append(
                f"Детализировать HLD до уровня API, схем данных и эксплуатационных сценариев по компонентам {component_names}."
            )
        else:
            candidates.append(
                "Детализировать high-level design до уровня API, данных, развертывания и эксплуатационных сценариев для MVP."
            )

    return _deduplicate_texts(candidates)[:3]


def _derive_risks_from_task(
    *, task_text: str, context_items: list[str], payload: GenerationSolutionPayload
) -> list[dict[str, Any]]:
    sections_by_code = {section.section_code: section for section in payload.sections}
    additional_section = sections_by_code.get("additional_information")
    risks_section_text = (
        additional_section.body_markdown if additional_section is not None else ""
    ) or ""
    combined_text = (
        "\n".join(part for part in [task_text, *context_items, risks_section_text] if part)
        .strip()
        .lower()
    )
    candidates: list[dict[str, Any]] = []

    if any(
        marker in combined_text
        for marker in ("ldap", "ad", "sso", "почт", "mail", "уведом", "notification", "интегра")
    ):
        candidates.append(
            {
                "title": "Зависимости от корпоративных интеграций могут задержать поставку",
                "severity": "major",
                "description": "Интеграция с LDAP/AD, SSO, почтой, уведомлениями или другими корпоративными сервисами может задержать реализацию и тестирование, если контракты и доступы не согласованы заранее.",
                "mitigation": "Владелец интеграций согласует ответственных, предусловия доступа, тестовые контуры и API-контракты на раннем архитектурном ревью; при блокировке используются согласованные заглушки и откат к ручному сценарию проверки.",
            }
        )
    if any(
        marker in combined_text
        for marker in (
            "backup",
            "резерв",
            "object",
            "объект",
            "storage",
            "хранилищ",
            "публикац",
            "version",
            "верс",
        )
    ):
        candidates.append(
            {
                "title": "Ошибки настройки хранения и резервного копирования могут повлиять на опубликованные артефакты",
                "severity": "critical",
                "description": "Некорректная настройка хранилища документов, политик резервного копирования или сроков хранения может привести к потере опубликованных версий и метаданных.",
                "mitigation": "Владелец платформы хранения фиксирует процедуры резервного копирования и восстановления, проверяет политики хранения на архитектурном чекпоинте и до промышленного запуска проводит тест восстановления; при неуспехе публикация блокируется до исправления.",
            }
        )
    if any(
        marker in combined_text
        for marker in (
            "нагруз",
            "масштаб",
            "performance",
            "latency",
            "отказ",
            "availability",
            "доступност",
        )
    ):
        candidates.append(
            {
                "title": "Нефункциональные требования могут быть недооценены",
                "severity": "major",
                "description": "Требования к нагрузке, доступности и эксплуатации могут превысить исходные проектные допущения, если планирование емкости и отказоустойчивость не проверены заранее.",
                "mitigation": "Архитектор решения добавляет сценарии НФТ, проверки емкости и отказоустойчивости в критерии приемки архитектуры; при непрохождении тестов объем MVP ограничивается до подтвержденного профиля нагрузки.",
            }
        )

    if not candidates and risks_section_text:
        for sentence in _split_sentences(risks_section_text):
            cleaned = _clean_text_value(sentence)
            if not cleaned or len(cleaned) < 20:
                continue
            candidates.append(
                {
                    "title": cleaned[:80],
                    "severity": "major",
                    "description": cleaned,
                    "mitigation": "Архитектор решения рассматривает риск на архитектурной валидации, назначает владельца меры, фиксирует действие и условие отката до публикации решения.",
                }
            )
            if len(candidates) >= 3:
                break

    if not candidates:
        candidates.append(
            {
                "title": "Архитектурные допущения могут измениться в ходе реализации",
                "severity": "major",
                "description": "Внешние зависимости, интеграционные контракты или инфраструктурные ограничения могут измениться в ходе реализации и повлиять на объем, сроки или проектные решения.",
                "mitigation": "Архитектор решения ведет журнал допущений, проверяет их на каждом архитектурном чекпоинте и заранее фиксирует резервные действия и условия отката.",
            }
        )

    deduped: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for item in candidates:
        title = _clean_text_value(item.get("title"))
        if not title:
            continue
        key = title.casefold()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        deduped.append(item)
    return deduped[:3]


def _enrich_required_generation_lists(
    payload: GenerationSolutionPayload,
    *,
    task_text: str,
    context_items: list[str],
) -> GenerationSolutionPayload:
    patched = payload.model_dump()
    assumptions = _deduplicate_texts(list(payload.assumptions))
    next_steps = _deduplicate_texts(list(payload.next_steps))
    risks: list[Any] = [item.model_dump() for item in payload.risks]

    if not assumptions:
        assumptions = _derive_assumptions_from_task(
            task_text=task_text, context_items=context_items, payload=payload
        )
    if not next_steps:
        next_steps = _derive_next_steps_from_task(
            task_text=task_text, context_items=context_items, payload=payload
        )
    if not risks:
        risks = _derive_risks_from_task(
            task_text=task_text, context_items=context_items, payload=payload
        )

    patched["assumptions"] = assumptions
    patched["next_steps"] = next_steps
    patched["risks"] = risks
    return _coerce_generation_solution_payload(patched)


__all__ = [name for name in globals() if name != "__builtins__"]
