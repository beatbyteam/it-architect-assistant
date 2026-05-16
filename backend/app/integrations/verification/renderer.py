from __future__ import annotations

from collections import defaultdict
from html import escape
from typing import Any

from pydantic import BaseModel

from app.integrations.verification.contracts import VerificationProtocolPayload


GROUP_LABELS = {
    "technical": "Техническая готовность",
    "structure": "Структура TOGAF",
    "normative": "Соответствие ArchiMate / нормативам",
    "consistency": "Семантическая согласованность",
    "other": "Прочие проверки",
}

STATUS_LABELS = {
    "passed": "Без замечаний",
    "passed_with_comments": "Есть комментарии",
    "warning": "Предупреждение",
    "failed": "Ошибка",
    "not_determined": "Требует ручной проверки",
    "not_applicable": "Не применяется",
    "incomplete": "Неполный результат",
    "published": "Опубликован",
    "draft": "Черновик",
}

SEVERITY_LABELS = {
    "critical": "Критично",
    "major": "Серьёзно",
    "minor": "Незначительно",
    "info": "Информация",
}

ROLE_LABELS = {
    "oda": "ODA",
    "ig1242_oda_component_inventory": "Инвентаризация компонентов IG1242 / ODA",
    "archimate_3_2": "ArchiMate 3.2",
    "technology_standard": "Технологический стандарт",
    "template_or_principles": "Шаблоны и принципы",
    "reference_only": "Справочный материал",
}

SECTION_LABELS = {
    "general_information": "1. Общие сведения",
    "business_tasks_description": "2. Описание бизнес-задач",
    "it_architecture_content": "3. Содержание ИТ-архитектуры",
    "business_architecture": "3.1 Бизнес-архитектура",
    "data_architecture": "3.2 Архитектура данных",
    "application_architecture": "3.3 Архитектура приложений",
    "technology_architecture": "3.4 Технологическая архитектура",
    "additional_information": "4. Дополнительные сведения",
}

METADATA_LABELS = {
    "verification_run_id": "Запуск проверки",
    "issued_at": "Дата выпуска",
    "protocol_state": "Статус протокола",
    "summary_status": "Итог проверки",
    "knowledge_version_id": "Версия базы знаний",
    "basis_document_count": "Документов-оснований",
    "findings_with_evidence": "Замечаний с основанием",
    "findings_without_section_links": "Замечаний без ссылки на раздел",
}


def _label(mapping: dict[str, str], value: Any) -> str:
    text = str(value or "")
    return mapping.get(text, text.replace("_", " "))


def _group_label(value: str) -> str:
    return GROUP_LABELS.get(value, f"Группа {value.replace('_', ' ')}")


def _section_label(value: str | None) -> str:
    if not value:
        return ""
    return SECTION_LABELS.get(value, value.replace("_", " "))


def _metadata_value(key: str, value: Any) -> str:
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    if key in {"protocol_state", "summary_status"}:
        return _label(STATUS_LABELS, value)
    return str(value)


class VerificationProtocolRenderer:
    def render_html(
        self,
        *,
        protocol_no: str | None,
        payload: VerificationProtocolPayload,
        basis_documents: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        basis_documents = basis_documents or []
        metadata = metadata or {}
        grouped_results: dict[str, list[Any]] = defaultdict(list)
        for item in payload.check_results:
            grouped_results[item.rule_group or "other"].append(item)

        status_counters = {"failed": 0, "warning": 0, "not_determined": 0, "passed": 0}
        for item in payload.check_results:
            status_counters[item.status.value] = status_counters.get(item.status.value, 0) + 1

        group_sections: list[str] = []
        preferred_group_order = ["technical", "structure", "normative", "consistency", "other"]
        ordered_group_codes = [group for group in preferred_group_order if group in grouped_results]
        ordered_group_codes.extend(
            sorted(group for group in grouped_results if group not in preferred_group_order)
        )
        for group_code in ordered_group_codes:
            items = grouped_results.get(group_code)
            if not items:
                continue
            rows = []
            for item in items:
                rows.append(
                    "<tr>"
                    f"<td>{escape(item.rule_code or '')}</td>"
                    f"<td>{escape(item.check_name)}</td>"
                    f"<td>{escape(_label(STATUS_LABELS, item.status.value))}</td>"
                    f"<td>{escape(_label(SEVERITY_LABELS, item.severity.value))}</td>"
                    f"<td>{escape(item.finding_text or '')}</td>"
                    f"<td>{escape(item.evidence_ref or '')}</td>"
                    f"<td>{escape(_section_label(item.related_section_ref))}</td>"
                    "</tr>"
                )
            group_sections.append(
                f"<h2>{escape(_group_label(group_code))}</h2>"
                "<table border='1' cellpadding='6' cellspacing='0'>"
                "<thead><tr><th>Правило</th><th>Проверка</th><th>Статус</th><th>Важность</th><th>Замечание</th><th>Основание</th><th>Раздел</th></tr></thead>"
                f"<tbody>{''.join(rows)}</tbody></table>"
            )

        basis_rows = []
        for basis_item in basis_documents:
            basis_document = (
                basis_item.model_dump() if isinstance(basis_item, BaseModel) else dict(basis_item)
            )
            basis_rows.append(
                "<tr>"
                f"<td>{escape(str(basis_document.get('title') or ''))}</td>"
                f"<td>{escape(_label(ROLE_LABELS, basis_document.get('role_code')))}</td>"
                f"<td>{escape(str(basis_document.get('version_ref') or ''))}</td>"
                f"<td>{'Да' if basis_document.get('required_flag') else 'Нет'}</td>"
                "</tr>"
            )
        protocol_label = escape(protocol_no or "черновик протокола")
        metadata_rows = []
        for key, value in metadata.items():
            if value in (None, "", [], {}):
                continue
            metadata_rows.append(
                f"<li><strong>{escape(METADATA_LABELS.get(key, key.replace('_', ' ')))}:</strong> "
                f"{escape(_metadata_value(key, value))}</li>"
            )
        executive_summary = (
            "<ul>"
            f"<li><strong>Ошибок:</strong> {status_counters.get('failed', 0)}</li>"
            f"<li><strong>Предупреждений:</strong> {status_counters.get('warning', 0)}</li>"
            f"<li><strong>Неполных проверок:</strong> {status_counters.get('not_determined', 0)}</li>"
            f"<li><strong>Пройдено:</strong> {status_counters.get('passed', 0)}</li>"
            "</ul>"
        )
        return (
            "<html><body>"
            f"<h1>Протокол проверки {protocol_label}</h1>"
            f"<p><strong>Итоговый статус:</strong> {escape(_label(STATUS_LABELS, payload.final_status.value))}</p>"
            f"<p>{escape(payload.summary)}</p>"
            f"<h2>Краткая сводка</h2>{executive_summary}"
            + (
                f"<h2>Паспорт протокола</h2><ul>{''.join(metadata_rows)}</ul>"
                if metadata_rows
                else ""
            )
            + (
                "<h2>Документы-основания</h2>"
                "<table border='1' cellpadding='6' cellspacing='0'>"
                "<thead><tr><th>Название</th><th>Роль</th><th>Версия</th><th>Обязательный</th></tr></thead>"
                f"<tbody>{''.join(basis_rows)}</tbody></table>"
                if basis_rows
                else ""
            )
            + "".join(group_sections)
            + "</body></html>"
        )
