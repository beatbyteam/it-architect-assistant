# ruff: noqa: E501
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.db.enums import (
    CheckResultStatus,
    ProtocolSummaryStatus,
    SolutionListItemGroup,
    SolutionVersionStatus,
)
from app.domain.architecture import (
    REQUIRED_TOGAF_SECTION_CODES,
    TOGAF_SECTION_ORDER,
    normalize_architecture_boundary_type,
    render_togaf_heading,
    validate_archimate_alignment,
)
from app.domain.services.knowledge_basis import build_basis_inventory_for_version_documents
from app.integrations.verification import (
    VerificationCheckResultPayload,
    VerificationRuleDefinition,
)

from .common import VerificationExecutionContext
from .document_scope import filter_version_documents


ROLE_LABELS: dict[str, str] = {
    "oda": "ODA",
    "ig1242_oda_component_inventory": "Инвентаризация компонентов IG1242 / ODA",
    "archimate_3_2": "ArchiMate 3.2",
    "technology_standard": "Технологический стандарт",
    "template_or_principles": "Шаблоны и принципы",
    "reference_only": "Справочный материал",
}

RULE_GROUP_LABELS: dict[str, str] = {
    "technical": "Техническая готовность",
    "structure": "Структура TOGAF",
    "normative": "Нормативное соответствие",
    "consistency": "Согласованность решения",
    "nfr": "Нефункциональные требования",
    "other": "Прочие проверки",
}

SUMMARY_STATUS_LABELS: dict[str, str] = {
    "passed": "без замечаний",
    "passed_with_comments": "есть комментарии",
    "failed": "не пройдена",
    "incomplete": "неполная",
}


def _role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role.replace("_", " "))


def _rule_group_label(group: str | None) -> str:
    value = group or "other"
    return RULE_GROUP_LABELS.get(value, f"Группа {value.replace('_', ' ')}")


def _summary_status_label(status: ProtocolSummaryStatus) -> str:
    status_value = getattr(status, "value", status)
    return SUMMARY_STATUS_LABELS.get(str(status_value), str(status_value))


def _section_label(section_code: str | None) -> str:
    if not section_code:
        return "раздел не указан"
    return f"{render_togaf_heading(section_code)} ({section_code})"


def _section_list(section_codes: list[str] | set[str] | tuple[str, ...]) -> str:
    return ", ".join(_section_label(code) for code in section_codes)


@dataclass(slots=True)
class VerificationSupportContext:
    section_by_code: dict[str, Any]
    section_codes: set[str]
    combined_section_text: str
    assumptions: list[Any]
    next_steps: list[Any]
    components: list[Any]
    integrations: list[Any]
    risks: list[Any]
    basis_inventory: Any
    required_fragments_by_role: dict[str, list[Any]]
    rule_evidence_by_code: dict[str, list[dict[str, Any]]]
    support_summary: dict[str, Any]

    def evidence_for_roles(self, *roles: str) -> str | None:
        parts: list[str] = []
        for role in roles:
            fragments = self.required_fragments_by_role.get(role) or []
            if not fragments:
                continue
            fragment_ids = ",".join(str(fragment.fragment_id) for fragment in fragments[:3])
            parts.append(f"{_role_label(role)}: {fragment_ids}")
        return "; ".join(parts) if parts else None

    def evidence_for_rule(self, rule_code: str) -> list[dict[str, Any]]:
        return list(self.rule_evidence_by_code.get(rule_code) or [])

    def section_role_refs(self, section_code: str) -> set[str]:
        section = self.section_by_code.get(section_code)
        if section is None:
            return set()
        refs = getattr(section, "source_refs", []) or []
        roles: set[str] = set()
        for ref in refs:
            fragment = getattr(ref, "fragment", None)
            metadata = dict(getattr(fragment, "fragment_metadata", None) or {})
            role_code = metadata.get("role_code")
            if role_code:
                roles.add(str(role_code))
        return roles

    @classmethod
    def build(cls, context: VerificationExecutionContext) -> VerificationSupportContext:
        solution = context.solution
        section_by_code = {
            str(getattr(section, "section_code", "")): section
            for section in getattr(solution, "sections", [])
            if getattr(section, "section_code", None)
        }
        section_codes = set(section_by_code.keys())
        assumptions = [
            item
            for item in getattr(solution, "list_items", [])
            if item.item_group == SolutionListItemGroup.ASSUMPTION
        ]
        next_steps = [
            item
            for item in getattr(solution, "list_items", [])
            if item.item_group == SolutionListItemGroup.NEXT_STEP
        ]
        components = list(getattr(solution, "components", []))
        integrations = list(getattr(solution, "integrations", []))
        risks = list(getattr(solution, "risks", []))
        knowledge_versions = list(getattr(context, "knowledge_versions", []) or [])
        if not knowledge_versions:
            knowledge_version = getattr(context.run, "knowledge_version", None) or getattr(
                getattr(solution, "generation_run", None), "knowledge_version", None
            )
            if knowledge_version is not None:
                knowledge_versions = [knowledge_version]
        version_documents: list[Any] = []
        for knowledge_version in knowledge_versions:
            version_documents.extend(
                filter_version_documents(
                    getattr(knowledge_version, "version_documents", []) or [],
                    getattr(context, "selected_document_ids", []) or [],
                )
            )
        basis_inventory = build_basis_inventory_for_version_documents(version_documents)
        combined_section_text = "\n".join(
            filter(
                None,
                [getattr(solution, "executive_summary", None)]
                + [getattr(section, "title", None) for section in getattr(solution, "sections", [])]
                + [
                    getattr(section, "body_markdown", None)
                    for section in getattr(solution, "sections", [])
                ],
            )
        )
        support_context = dict(context.support_context_by_scope or {})
        support_summary = dict(support_context.get("support_summary") or {})
        support_summary.setdefault("scoped_document_count", len(version_documents))
        support_summary.setdefault(
            "document_scope",
            "selected" if getattr(context, "selected_document_ids", []) else "full",
        )
        support_summary.setdefault(
            "selected_document_count",
            len(getattr(context, "selected_document_ids", []) or []),
        )
        return cls(
            section_by_code=section_by_code,
            section_codes=section_codes,
            combined_section_text=combined_section_text,
            assumptions=assumptions,
            next_steps=next_steps,
            components=components,
            integrations=integrations,
            risks=risks,
            basis_inventory=basis_inventory,
            required_fragments_by_role=dict(
                support_context.get("required_fragments_by_role") or {}
            ),
            rule_evidence_by_code={
                str(rule_code): [dict(item) for item in list(items or [])]
                for rule_code, items in (
                    support_context.get("rule_evidence_by_code") or {}
                ).items()
            },
            support_summary=support_summary,
        )


class _BaseRuleExecutor:
    def result(
        self,
        *,
        rule: VerificationRuleDefinition,
        status: CheckResultStatus,
        finding: str | None = None,
        evidence: str | None = None,
        diagnostics: dict[str, Any] | None = None,
        related_section_ref: str | None = None,
    ) -> VerificationCheckResultPayload:
        return VerificationCheckResultPayload(
            rule_code=rule.code,
            check_name=rule.name,
            rule_group=rule.group,
            status=status,
            severity=rule.default_severity,
            finding_text=finding,
            evidence_ref=evidence,
            related_section_ref=related_section_ref,
            diagnostics=diagnostics,
            is_technical_check=rule.technical,
        )

    @staticmethod
    def _has_any(text: str, patterns: list[str]) -> bool:
        lowered = (text or "").lower()
        return any(pattern in lowered for pattern in patterns)

    @staticmethod
    def _first_section_ref(
        support: VerificationSupportContext, *preferred_section_codes: str
    ) -> str | None:
        for section_code in preferred_section_codes:
            if section_code in support.section_codes:
                return section_code
        ordered_sections = sorted(
            support.section_by_code.values(), key=lambda row: getattr(row, "sort_order", 0)
        )
        for section in ordered_sections:
            fallback_section_code = getattr(section, "section_code", None)
            if fallback_section_code:
                return str(fallback_section_code)
        return None

    @staticmethod
    def _has_verification_materials(support: VerificationSupportContext) -> bool:
        basis_count = len(support.basis_inventory.basis_documents or [])
        selected_document_count = int(
            support.support_summary.get("selected_document_count") or 0
        )
        scoped_document_count = int(support.support_summary.get("scoped_document_count") or 0)
        return max(basis_count, selected_document_count, scoped_document_count) > 0


class TechnicalRulesExecutor(_BaseRuleExecutor):
    def execute(
        self,
        *,
        rule: VerificationRuleDefinition,
        context: VerificationExecutionContext,
        support: VerificationSupportContext,
    ) -> VerificationCheckResultPayload:
        solution = context.solution
        if rule.code == "VR-TEC-01":
            status_value = getattr(
                getattr(solution, "status", None), "value", getattr(solution, "status", None)
            )
            if status_value is None:
                return self.result(
                    rule=rule,
                    status=CheckResultStatus.NOT_DETERMINED,
                    finding="Не удалось определить статус решения.",
                    evidence=str(getattr(solution, "solution_version_id", "неизвестно")),
                    diagnostics={"solution_status": None},
                )
            ok = status_value == SolutionVersionStatus.PUBLISHED.value
            return self.result(
                rule=rule,
                status=CheckResultStatus.PASSED if ok else CheckResultStatus.FAILED,
                finding=None
                if ok
                else "Решение не опубликовано и пока не готово к проверке.",
                evidence=str(getattr(solution, "solution_version_id", "неизвестно")),
                diagnostics={"solution_status": status_value},
            )

        if rule.code == "VR-TEC-02":
            knowledge_version_id = str(getattr(context.run, "knowledge_version_id", "") or "")
            if not knowledge_version_id:
                return self.result(
                    rule=rule,
                    status=CheckResultStatus.FAILED,
                    finding="Для запуска проверки не зафиксирована версия базы знаний.",
                    evidence="версия базы знаний не задана",
                    diagnostics={"knowledge_version_id": None},
                )
            return self.result(
                rule=rule,
                status=CheckResultStatus.PASSED,
                evidence=knowledge_version_id,
                diagnostics={"knowledge_version_id": knowledge_version_id},
            )

        if rule.code == "VR-TEC-03":
            missing = list(support.basis_inventory.missing_required_packages or [])
            basis_count = len(support.basis_inventory.basis_documents or [])
            selected_document_count = int(
                support.support_summary.get("selected_document_count") or 0
            )
            scoped_document_count = int(support.support_summary.get("scoped_document_count") or 0)
            has_verification_materials = self._has_verification_materials(support)
            if not missing:
                status = CheckResultStatus.PASSED
            elif has_verification_materials:
                status = CheckResultStatus.WARNING
            else:
                status = CheckResultStatus.FAILED
            return self.result(
                rule=rule,
                status=status,
                finding=None
                if not missing
                else "В выбранной области знаний не хватает ожидаемых пакетов оснований: "
                f"{', '.join(_role_label(item) for item in missing)}.",
                evidence=", ".join(
                    _role_label(item["role_code"])
                    for item in support.basis_inventory.required_packages
                ),
                diagnostics={
                    "required_packages": support.basis_inventory.required_packages,
                    "missing_required_packages": missing,
                    "basis_document_count": basis_count,
                    "selected_document_count": selected_document_count,
                    "scoped_document_count": scoped_document_count,
                },
            )

        if rule.code == "VR-TEC-04":
            basis_count = len(support.basis_inventory.basis_documents)
            selected_document_count = int(
                support.support_summary.get("selected_document_count") or 0
            )
            effective_basis_count = max(basis_count, selected_document_count)
            if effective_basis_count == 0:
                return self.result(
                    rule=rule,
                    status=CheckResultStatus.FAILED,
                    finding="В протоколе нет документов-оснований.",
                    evidence="документы-основания: 0",
                    diagnostics={"basis_document_count": 0},
                )
            return self.result(
                rule=rule,
                status=CheckResultStatus.PASSED,
                evidence=f"документы-основания: {effective_basis_count}",
                diagnostics={"basis_document_count": effective_basis_count},
            )

        return self.result(
            rule=rule,
            status=CheckResultStatus.NOT_DETERMINED,
            finding="Техническое правило не поддерживается обработчиком проверки.",
            evidence=rule.code,
            diagnostics={"group": "technical"},
        )


class StructureRulesExecutor(_BaseRuleExecutor):
    def execute(
        self,
        *,
        rule: VerificationRuleDefinition,
        context: VerificationExecutionContext,
        support: VerificationSupportContext,
    ) -> VerificationCheckResultPayload:
        solution = context.solution
        general_section = support.section_by_code.get("general_information")
        task_section = support.section_by_code.get("business_tasks_description")
        data_section = support.section_by_code.get("data_architecture")
        app_section = support.section_by_code.get("application_architecture")
        additional_section = support.section_by_code.get("additional_information")
        normalized_text = support.combined_section_text.lower()
        if rule.code == "VR-STR-01":
            business_task = getattr(solution, "business_task", None)
            general_text = (
                (
                    (getattr(general_section, "title", None) or "")
                    + " "
                    + (getattr(general_section, "body_markdown", None) or "")
                )
                .strip()
                .lower()
            )
            task_text_section = (
                (
                    (getattr(task_section, "title", None) or "")
                    + " "
                    + (getattr(task_section, "body_markdown", None) or "")
                )
                .strip()
                .lower()
            )
            task_text = (getattr(business_task, "task_text", None) or "").strip()
            has_goal = (
                bool(task_text)
                or self._has_any(normalized_text, ["цель", "goal", "результат", "business outcome"])
                or self._has_any(
                    task_text_section, ["цель", "goal", "результат", "business outcome"]
                )
            )
            has_context = bool(general_text or task_text_section) or self._has_any(
                normalized_text, ["контекст", "context", "as is", "текущ", "существующ"]
            )
            ok = has_goal and has_context
            return self.result(
                rule=rule,
                status=CheckResultStatus.PASSED if ok else CheckResultStatus.FAILED,
                finding=None if ok else "Цель и/или контекст задачи описаны недостаточно.",
                evidence=str(getattr(solution, "business_task_id", "неизвестно")),
                diagnostics={"has_goal": has_goal, "has_context": has_context},
                related_section_ref=self._first_section_ref(
                    support,
                    "business_tasks_description",
                    "general_information",
                    "it_architecture_content",
                ),
            )

        if rule.code == "VR-STR-02":
            additional_text = (
                (
                    (getattr(additional_section, "title", None) or "")
                    + " "
                    + (getattr(additional_section, "body_markdown", None) or "")
                )
                .strip()
                .lower()
            )
            assumptions_present = bool(support.assumptions) or self._has_any(
                additional_text or normalized_text, ["допущ", "assumption"]
            )
            constraints_present = self._has_any(
                additional_text or normalized_text,
                [
                    "огранич",
                    "constraint",
                    "limitation",
                    "не допускается",
                    "нельзя",
                    "должен быть только",
                ],
            )
            if assumptions_present and constraints_present:
                status = CheckResultStatus.PASSED
            elif assumptions_present or constraints_present:
                status = CheckResultStatus.WARNING
            else:
                status = CheckResultStatus.FAILED
            return self.result(
                rule=rule,
                status=status,
                finding=None
                if status == CheckResultStatus.PASSED
                else "Ограничения и допущения отражены только частично."
                if status == CheckResultStatus.WARNING
                else "Ограничения и допущения не описаны.",
                evidence="ограничения и допущения",
                diagnostics={
                    "assumption_count": len(support.assumptions),
                    "constraints_present": constraints_present,
                },
                related_section_ref=self._first_section_ref(support, "additional_information"),
            )

        if rule.code == "VR-STR-03":
            component_count = len(support.components)
            if component_count == 0:
                status = CheckResultStatus.FAILED
            elif component_count < 2:
                status = CheckResultStatus.WARNING
            else:
                status = CheckResultStatus.PASSED
            return self.result(
                rule=rule,
                status=status,
                finding=None
                if status == CheckResultStatus.PASSED
                else "Состав компонентов описан недостаточно подробно."
                if status == CheckResultStatus.WARNING
                else "Состав компонентов не описан.",
                evidence=", ".join(
                    component.component_name for component in support.components[:8]
                ),
                diagnostics={"component_count": component_count},
                related_section_ref=self._first_section_ref(
                    support,
                    "application_architecture",
                    "it_architecture_content",
                    "business_architecture",
                    "general_information",
                ),
            )

        if rule.code == "VR-STR-04":
            mentions_api = self._has_any(
                normalized_text, ["api", "rest", "grpc", "soap", "webhook", "интеграц"]
            )
            integration_count = len(support.integrations)
            if not mentions_api and integration_count == 0:
                return self.result(
                    rule=rule,
                    status=CheckResultStatus.NOT_APPLICABLE,
                    evidence="интеграции не упомянуты",
                    diagnostics={"integration_count": 0},
                )
            if integration_count == 0:
                return self.result(
                    rule=rule,
                status=CheckResultStatus.FAILED,
                    finding=(
                        "В тексте архитектуры упоминаются API или интеграции, но они не "
                        "раскрыты как структурная модель: источник, получатель, направление, "
                        "протокол, данные и обработка ошибок."
                    ),
                    evidence="интеграции упомянуты, но не смоделированы",
                    diagnostics={"integration_count": 0},
                    related_section_ref=self._first_section_ref(
                        support, "data_architecture", "application_architecture"
                    ),
                )
            incomplete = [
                str(getattr(item, "integration_id", "неизвестная интеграция"))
                for item in support.integrations
                if not (getattr(item, "protocol", None) and getattr(item, "rationale", None))
            ]
            disclosure_text = " ".join(
                part
                for part in [
                    getattr(data_section, "body_markdown", None) or "",
                    getattr(app_section, "body_markdown", None) or "",
                ]
                if part
            ).strip()
            status = (
                CheckResultStatus.PASSED
                if disclosure_text and not incomplete
                else CheckResultStatus.WARNING
            )
            return self.result(
                rule=rule,
                status=status,
                finding=None
                if status == CheckResultStatus.PASSED
                else (
                    "Часть интеграций описана неполно: проверьте протокол, назначение, "
                    "связь с TOGAF-разделами и ответственность компонентов."
                ),
                evidence=", ".join(incomplete)
                if incomplete
                else f"интеграции: {integration_count}",
                diagnostics={
                    "integration_count": integration_count,
                    "incomplete_integrations": incomplete,
                },
                related_section_ref=self._first_section_ref(
                    support, "data_architecture", "application_architecture"
                ),
            )

        if rule.code == "VR-STR-05":
            risk_count = len(support.risks)
            if risk_count == 0:
                status = CheckResultStatus.FAILED
            elif risk_count == 1 or len(support.next_steps) == 0:
                status = CheckResultStatus.WARNING
            else:
                status = CheckResultStatus.PASSED
            return self.result(
                rule=rule,
                status=status,
                finding=None
                if status == CheckResultStatus.PASSED
                else "Риски и открытые вопросы описаны поверхностно или неполно."
                if status == CheckResultStatus.WARNING
                else "Блок рисков и открытых вопросов отсутствует.",
                evidence=f"риски: {risk_count}",
                diagnostics={"risk_count": risk_count, "next_step_count": len(support.next_steps)},
                related_section_ref=self._first_section_ref(support, "additional_information"),
            )

        if rule.code == "VR-STR-06":
            missing_sections = [
                code for code in REQUIRED_TOGAF_SECTION_CODES if code not in support.section_codes
            ]
            status = CheckResultStatus.PASSED if not missing_sections else CheckResultStatus.FAILED
            return self.result(
                rule=rule,
                status=status,
                finding=None
                if status == CheckResultStatus.PASSED
                else f"Не заполнены обязательные разделы TOGAF: {_section_list(missing_sections)}.",
                evidence=", ".join(sorted(support.section_codes))
                if support.section_codes
                else "разделы не найдены",
                diagnostics={
                    "missing_sections": missing_sections,
                    "present_sections": sorted(support.section_codes),
                },
                related_section_ref=missing_sections[0] if missing_sections else None,
            )

        if rule.code == "VR-STR-07":
            ordered_sections = [
                getattr(item, "section_code", None)
                for item in sorted(
                    support.section_by_code.values(), key=lambda row: getattr(row, "sort_order", 0)
                )
                if getattr(item, "section_code", None)
            ]
            canonical_subset = [
                code for code in ordered_sections if code in REQUIRED_TOGAF_SECTION_CODES
            ]
            expected_subset = [
                code for code in REQUIRED_TOGAF_SECTION_CODES if code in support.section_codes
            ]
            status = (
                CheckResultStatus.PASSED
                if canonical_subset == expected_subset
                else CheckResultStatus.FAILED
            )
            return self.result(
                rule=rule,
                status=status,
                finding=None
                if status == CheckResultStatus.PASSED
                else "Разделы TOGAF расположены не в каноническом порядке документа.",
                evidence=_section_list(canonical_subset)
                if canonical_subset
                else "порядок разделов не определён",
                diagnostics={
                    "observed_order": canonical_subset,
                    "expected_order": expected_subset,
                    "order_indexes": {
                        code: TOGAF_SECTION_ORDER.get(code) for code in canonical_subset
                    },
                },
                related_section_ref=canonical_subset[0] if canonical_subset else None,
            )

        return self.result(
            rule=rule,
            status=CheckResultStatus.NOT_DETERMINED,
            finding="Структурное правило не поддерживается обработчиком проверки.",
            evidence=rule.code,
            diagnostics={"group": "structure"},
        )


class NormativeRulesExecutor(_BaseRuleExecutor):
    CONTRADICTION_MARKERS = {
        "VR-NRM-01": ["вне oda", "без oda", "игнорируем oda", "не используем ig1242"],
        "VR-NRM-02": ["произвольная метамодель", "без archimate", "не следуем archimate"],
    }

    def execute(
        self,
        *,
        rule: VerificationRuleDefinition,
        context: VerificationExecutionContext,
        support: VerificationSupportContext,
    ) -> VerificationCheckResultPayload:
        normalized_text = support.combined_section_text.lower()
        if rule.code == "VR-NRM-01":
            related_section_ref = self._first_section_ref(
                support,
                "it_architecture_content",
                "application_architecture",
                "data_architecture",
                "business_architecture",
                "technology_architecture",
                "general_information",
            )
            evidence = support.evidence_for_roles("oda", "ig1242_oda_component_inventory")
            if evidence is None:
                status = (
                    CheckResultStatus.WARNING
                    if self._has_verification_materials(support)
                    else CheckResultStatus.NOT_DETERMINED
                )
                return self.result(
                    rule=rule,
                    status=status,
                    finding="Для нормативной оценки недоступны обязательные фрагменты ODA / IG1242.",
                    evidence="фрагменты ODA / IG1242 не найдены",
                    diagnostics={
                        "required_roles": ["oda", "ig1242_oda_component_inventory"],
                        "missing_basis_fragments": True,
                    },
                    related_section_ref=related_section_ref,
                )
            contradiction = any(
                marker in normalized_text for marker in self.CONTRADICTION_MARKERS["VR-NRM-01"]
            )
            role_refs = (
                support.section_role_refs("it_architecture_content")
                | support.section_role_refs("application_architecture")
                | support.section_role_refs("data_architecture")
            )
            selected_document_scope = bool(getattr(context, "selected_document_ids", []) or [])
            if contradiction:
                status = CheckResultStatus.FAILED
                finding = "Решение явно противоречит предпосылкам соответствия ODA / IG1242."
            elif selected_document_scope or {"oda", "ig1242_oda_component_inventory"} & role_refs:
                status = CheckResultStatus.PASSED
                finding = None
            else:
                status = CheckResultStatus.WARNING
                finding = "Основания ODA / IG1242 есть, но связь с разделами решения выражена слабо."
            return self.result(
                rule=rule,
                status=status,
                finding=finding,
                evidence=evidence,
                diagnostics={
                    "linked_roles": sorted(role_refs),
                    "selected_document_scope": selected_document_scope,
                },
                related_section_ref=related_section_ref,
            )

        if rule.code == "VR-NRM-02":
            related_section_ref = self._first_section_ref(
                support,
                "it_architecture_content",
                "business_architecture",
                "data_architecture",
                "application_architecture",
                "technology_architecture",
                "general_information",
            )
            evidence = support.evidence_for_roles("archimate_3_2")
            if evidence is None:
                status = (
                    CheckResultStatus.WARNING
                    if self._has_verification_materials(support)
                    else CheckResultStatus.NOT_DETERMINED
                )
                return self.result(
                    rule=rule,
                    status=status,
                    finding="Для нормативной оценки недоступны фрагменты ArchiMate 3.2.",
                    evidence="фрагменты ArchiMate 3.2 не найдены",
                    diagnostics={
                        "required_roles": ["archimate_3_2"],
                        "missing_basis_fragments": True,
                    },
                    related_section_ref=related_section_ref,
                )
            contradiction = any(
                marker in normalized_text for marker in self.CONTRADICTION_MARKERS["VR-NRM-02"]
            )
            alignments = [
                validate_archimate_alignment(
                    section_code,
                    getattr(support.section_by_code.get(section_code), "body_markdown", None),
                )
                for section_code in [
                    "business_architecture",
                    "data_architecture",
                    "application_architecture",
                    "technology_architecture",
                ]
                if section_code in support.section_codes
            ]
            has_disallowed = any(item.get("disallowed_element_codes") for item in alignments)
            has_allowed_content = (
                all(item.get("has_allowed_content") for item in alignments) if alignments else False
            )
            if contradiction or has_disallowed:
                status = CheckResultStatus.FAILED
                finding = "Терминология или структура решения противоречит предпосылкам соответствия ArchiMate 3.2."
            elif has_allowed_content:
                status = CheckResultStatus.PASSED
                finding = None
            else:
                status = CheckResultStatus.WARNING
                finding = "Структура решения только частично показывает разложение по слоям ArchiMate 3.2."
            return self.result(
                rule=rule,
                status=status,
                finding=finding,
                evidence=evidence,
                diagnostics={
                    "alignments": alignments,
                    "component_count": len(support.components),
                    "integration_count": len(support.integrations),
                },
                related_section_ref=related_section_ref,
            )

        if rule.code == "VR-NRM-03":
            related_section_ref = self._first_section_ref(
                support,
                "technology_architecture",
                "application_architecture",
                "it_architecture_content",
            )
            evidence = support.evidence_for_roles("technology_standard")
            if evidence is None:
                status = (
                    CheckResultStatus.WARNING
                    if self._has_verification_materials(support)
                    else CheckResultStatus.NOT_DETERMINED
                )
                return self.result(
                    rule=rule,
                    status=status,
                    finding="Для нормативной оценки недоступны фрагменты технологического стандарта.",
                    evidence="фрагменты технологического стандарта не найдены",
                    diagnostics={
                        "required_roles": ["technology_standard"],
                        "missing_basis_fragments": True,
                    },
                    related_section_ref=related_section_ref,
                )
            tech_text = " ".join(
                (getattr(component, "technology_stack", None) or "")
                for component in support.components
            ).lower()
            fragments = support.required_fragments_by_role.get("technology_standard") or []
            prohibited_hits: list[str] = []
            aligned_hits: list[str] = []
            for fragment in fragments[:12]:
                content = (getattr(fragment, "content", None) or "").lower()
                title = (getattr(fragment, "title", None) or "").lower()
                for token in re.findall(r"[a-zA-Z0-9_\-\.]{3,}", tech_text):
                    if token in {"and", "the", "for", "with", "без", "или"}:
                        continue
                    if token in content or token in title:
                        aligned_hits.append(token)
                    if token in content and any(
                        marker in content
                        for marker in [
                            "forbid",
                            "must not",
                            "deprecated",
                            "not recommended",
                            "запрещ",
                            "не рекоменду",
                        ]
                    ):
                        prohibited_hits.append(token)
            if prohibited_hits:
                status = CheckResultStatus.FAILED
                finding = (
                    "Выбранные технологии конфликтуют с технологическим стандартом: "
                    f"{', '.join(sorted(set(prohibited_hits)))}."
                )
            elif aligned_hits:
                status = CheckResultStatus.PASSED
                finding = None
            else:
                status = CheckResultStatus.WARNING
                finding = "Выбор технологий недостаточно явно подтверждён выбранным технологическим стандартом."
            return self.result(
                rule=rule,
                status=status,
                finding=finding,
                evidence=evidence,
                diagnostics={
                    "aligned_hits": sorted(set(aligned_hits))[:12],
                    "prohibited_hits": sorted(set(prohibited_hits))[:12],
                },
                related_section_ref=related_section_ref,
            )

        if rule.code == "VR-NRM-04":
            template_docs = [
                item
                for item in support.basis_inventory.basis_documents
                if item.role_code == "template_or_principles"
            ]
            if not template_docs:
                return self.result(
                    rule=rule,
                    status=CheckResultStatus.NOT_APPLICABLE,
                    evidence="шаблоны и принципы не загружены",
                    diagnostics={"basis_present": False},
                )
            evidence = (
                support.evidence_for_roles("template_or_principles") or "шаблоны и принципы"
            )
            has_refs = bool(
                support.section_role_refs("general_information")
                | support.section_role_refs("it_architecture_content")
                | support.section_role_refs("additional_information")
            )
            selected_document_scope = bool(getattr(context, "selected_document_ids", []) or [])
            if has_refs or selected_document_scope:
                status = CheckResultStatus.PASSED
                finding = None
            elif (
                "general_information" not in support.section_codes
                or "additional_information" not in support.section_codes
            ):
                status = CheckResultStatus.FAILED
                finding = "Обязательные шаблоны или принципы есть, но разделы для их применения отсутствуют."
            else:
                status = CheckResultStatus.WARNING
                finding = "Пакет шаблонов или принципов присутствует, но его использование в решении неочевидно."
            return self.result(
                rule=rule,
                status=status,
                finding=finding,
                evidence=evidence,
                diagnostics={
                    "basis_present": True,
                    "selected_document_scope": selected_document_scope,
                    "template_document_count": len(template_docs),
                },
                related_section_ref=self._first_section_ref(
                    support,
                    "general_information",
                    "additional_information",
                    "it_architecture_content",
                ),
            )

        if rule.code == "VR-NRM-05":
            section_alignments = {
                section_code: validate_archimate_alignment(
                    section_code,
                    getattr(support.section_by_code.get(section_code), "body_markdown", None),
                )
                for section_code in [
                    "business_architecture",
                    "data_architecture",
                    "application_architecture",
                    "technology_architecture",
                ]
                if section_code in support.section_codes
            }
            violating_sections = [
                section_code
                for section_code, alignment in section_alignments.items()
                if alignment.get("disallowed_element_codes")
            ]
            status = (
                CheckResultStatus.PASSED if not violating_sections else CheckResultStatus.FAILED
            )
            return self.result(
                rule=rule,
                status=status,
                finding=None
                if status == CheckResultStatus.PASSED
                else "В разделах обнаружены неразрешённые элементы ArchiMate: "
                f"{_section_list(violating_sections)}.",
                evidence=_section_list(sorted(section_alignments))
                if section_alignments
                else "разделы для проверки ArchiMate не найдены",
                diagnostics={
                    "alignments": section_alignments,
                    "violating_sections": violating_sections,
                },
                related_section_ref=violating_sections[0] if violating_sections else None,
            )

        if rule.code == "VR-NRM-06":
            section_alignments = {
                section_code: validate_archimate_alignment(
                    section_code,
                    getattr(support.section_by_code.get(section_code), "body_markdown", None),
                )
                for section_code in [
                    "business_architecture",
                    "data_architecture",
                    "application_architecture",
                    "technology_architecture",
                ]
                if section_code in support.section_codes
            }
            weak_sections = [
                section_code
                for section_code, alignment in section_alignments.items()
                if not alignment.get("has_allowed_content")
            ]
            if not section_alignments:
                status = CheckResultStatus.FAILED
                finding = "Отсутствуют разделы архитектуры, необходимые для проверки соответствия ArchiMate."
            elif weak_sections:
                status = CheckResultStatus.WARNING
                finding = (
                    "В некоторых разделах недостаточно разрешённых объектов ArchiMate: "
                    f"{_section_list(weak_sections)}."
                )
            else:
                status = CheckResultStatus.PASSED
                finding = None
            return self.result(
                rule=rule,
                status=status,
                finding=finding,
                evidence=_section_list(sorted(section_alignments))
                if section_alignments
                else "разделы для проверки ArchiMate не найдены",
                diagnostics={
                    "alignments": section_alignments,
                    "weak_sections": weak_sections
                    if section_alignments
                    else list(REQUIRED_TOGAF_SECTION_CODES),
                },
                related_section_ref=weak_sections[0]
                if section_alignments and weak_sections
                else self._first_section_ref(
                    support,
                    "it_architecture_content",
                    "business_architecture",
                    "data_architecture",
                    "application_architecture",
                    "technology_architecture",
                    "general_information",
                )
                if not section_alignments
                else None,
            )

        return self.result(
            rule=rule,
            status=CheckResultStatus.NOT_DETERMINED,
            finding="Нормативное правило не поддерживается обработчиком проверки.",
            evidence=rule.code,
            diagnostics={"group": "normative"},
        )


class ConsistencyRulesExecutor(_BaseRuleExecutor):
    _DOMAIN_STOPWORDS = {
        "business",
        "application",
        "technology",
        "service",
        "system",
        "process",
        "component",
        "role",
        "office",
        "node",
        "runtime",
        "cluster",
        "platform",
        "module",
        "adapter",
        "gateway",
        "layer",
        "api",
        "данных",
        "данные",
        "сервис",
        "система",
        "процесс",
        "компонент",
        "платформа",
        "кластер",
        "узел",
    }
    _BUSINESS_APP_LINK_PATTERNS = [
        "support",
        "supports",
        "supported",
        "implement",
        "implements",
        "realize",
        "realizes",
        "handle",
        "handles",
        "orchestr",
        "use",
        "uses",
        "using",
        "through",
        "via",
        "mapped",
        "backed",
        "automate",
        "drives",
        "поддерж",
        "реализ",
        "использ",
        "через",
        "обеспеч",
        "автоматиз",
        "оркестр",
        "обрабаты",
    ]
    _APP_TECH_LINK_PATTERNS = [
        "host",
        "hosts",
        "hosted",
        "run on",
        "runs on",
        "deploy",
        "deployed",
        "execution",
        "runtime",
        "storage",
        "container",
        "node",
        "cluster",
        "kubernetes",
        "database",
        "redis",
        "postgres",
        "infra",
        "platform",
        "размещ",
        "запуска",
        "исполня",
        "хост",
        "кластер",
        "контейнер",
        "база данных",
        "postgres",
        "redis",
        "kubernetes",
    ]

    @staticmethod
    def _component_text(component: Any) -> str:
        return " ".join(
            part.strip()
            for part in [
                str(getattr(component, "component_name", "") or ""),
                str(getattr(component, "role_description", "") or ""),
                str(getattr(component, "technology_stack", "") or ""),
            ]
            if str(part or "").strip()
        )

    def _extract_domain_tokens(self, value: str) -> set[str]:
        tokens = set()
        for token in re.findall(r"[a-zA-Zа-яА-Я0-9_\-]{4,}", value.lower()):
            normalized = token.strip("_-")
            if not normalized or normalized in self._DOMAIN_STOPWORDS:
                continue
            tokens.add(normalized)
        return tokens

    def _relation_fragments(self, *texts: str) -> list[str]:
        fragments: list[str] = []
        for text in texts:
            for fragment in re.split(r"[\n.;:!?]+", text or ""):
                cleaned = " ".join(fragment.split()).strip().lower()
                if cleaned:
                    fragments.append(cleaned)
        return fragments

    def _has_component_relation(
        self,
        left_components: list[Any],
        right_components: list[Any],
        *,
        texts: list[str],
        relation_patterns: list[str],
    ) -> tuple[bool, str | None]:
        fragments = self._relation_fragments(*texts)
        for fragment in fragments:
            if not any(pattern in fragment for pattern in relation_patterns):
                continue
            for left in left_components:
                left_name = str(getattr(left, "component_name", "") or "").strip().lower()
                if not left_name or left_name not in fragment:
                    continue
                for right in right_components:
                    right_name = str(getattr(right, "component_name", "") or "").strip().lower()
                    if right_name and right_name in fragment:
                        return True, fragment
        return False, None

    def _has_token_overlap(
        self, left_components: list[Any], right_components: list[Any]
    ) -> tuple[bool, list[str]]:
        overlaps: set[str] = set()
        right_tokens = {
            token
            for component in right_components
            for token in self._extract_domain_tokens(self._component_text(component))
        }
        for component in left_components:
            overlaps.update(
                self._extract_domain_tokens(self._component_text(component)) & right_tokens
            )
        filtered = sorted(token for token in overlaps if token not in self._DOMAIN_STOPWORDS)
        return bool(filtered), filtered[:8]

    def _has_integration_link(
        self, left_components: list[Any], right_components: list[Any], integrations: list[Any]
    ) -> bool:
        left_ids = {
            str(getattr(component, "component_id", ""))
            for component in left_components
            if getattr(component, "component_id", None)
        }
        right_ids = {
            str(getattr(component, "component_id", ""))
            for component in right_components
            if getattr(component, "component_id", None)
        }
        if not left_ids or not right_ids:
            return False
        for integration in integrations:
            from_id = str(getattr(integration, "from_component_id", "") or "")
            to_id = str(getattr(integration, "to_component_id", "") or "")
            if (from_id in left_ids and to_id in right_ids) or (
                from_id in right_ids and to_id in left_ids
            ):
                return True
        return False

    def execute(
        self,
        *,
        rule: VerificationRuleDefinition,
        context: VerificationExecutionContext,
        support: VerificationSupportContext,
    ) -> VerificationCheckResultPayload:
        normalized_text = support.combined_section_text.lower()
        component_names = [component.component_name for component in support.components]
        component_ids = {
            str(getattr(component, "component_id", ""))
            for component in support.components
            if getattr(component, "component_id", None)
        }
        if rule.code == "VR-CNS-01":
            duplicate_component_names = len(component_names) != len(set(component_names))
            broken_integrations = [
                str(getattr(item, "integration_id", "неизвестная интеграция"))
                for item in support.integrations
                if component_ids
                and (
                    str(getattr(item, "from_component_id", "")) not in component_ids
                    or str(getattr(item, "to_component_id", "")) not in component_ids
                )
            ]
            contradiction_reasons: list[str] = []
            protocols = " ".join(
                (getattr(integration, "protocol", None) or "").lower()
                for integration in support.integrations
            )
            has_external_components = any(
                getattr(component, "external_flag", False) for component in support.components
            )
            has_integrations = bool(support.integrations)
            for text_item in [getattr(item, "item_text", "") for item in support.assumptions] or [
                normalized_text
            ]:
                lowered = text_item.lower()
                if "без интегра" in lowered and has_integrations:
                    contradiction_reasons.append(
                        "в решении заявлено отсутствие интеграций, но интеграции есть"
                    )
                if (
                    "без api" in lowered
                    or "api не требуется" in lowered
                    or "api не нужен" in lowered
                ) and "api" in normalized_text:
                    contradiction_reasons.append("в решении заявлено отсутствие API, но API описан")
                if ("без внешн" in lowered or "только внутрен" in lowered) and (
                    has_external_components or has_integrations
                ):
                    contradiction_reasons.append(
                        "в решении заявлен только внутренний контур, но есть внешние участники или интеграции"
                    )
                if (
                    "только batch" in lowered
                    or "только пакет" in lowered
                    or "только оффлайн" in lowered
                ) and self._has_any(protocols, ["http", "rest", "grpc", "websocket", "api"]):
                    contradiction_reasons.append(
                        "в решении заявлен пакетный или офлайн-режим, но используются синхронные онлайн-протоколы"
                    )
            issues = []
            if duplicate_component_names:
                issues.append("дублируются названия компонентов")
            if broken_integrations:
                issues.append("есть некорректные ссылки в интеграциях")
            if contradiction_reasons:
                issues.extend(contradiction_reasons)
            return self.result(
                rule=rule,
                status=CheckResultStatus.PASSED if not issues else CheckResultStatus.FAILED,
                finding=None
                if not issues
                else f"Обнаружены проблемы внутренней согласованности: {'; '.join(issues)}.",
                evidence=", ".join(broken_integrations)
                if broken_integrations
                else ", ".join(component_names),
                diagnostics={
                    "broken_integrations": broken_integrations,
                    "contradiction_reasons": contradiction_reasons,
                },
                related_section_ref="data_architecture"
                if "data_architecture" in support.section_codes
                else (
                    "application_architecture"
                    if "application_architecture" in support.section_codes
                    else None
                ),
            )

        if rule.code == "VR-CNS-02":
            deficiencies = []
            source_ref_total = 0
            for section_code in [
                "general_information",
                "business_tasks_description",
                "it_architecture_content",
                "business_architecture",
                "data_architecture",
                "application_architecture",
                "technology_architecture",
                "additional_information",
            ]:
                section = support.section_by_code.get(section_code)
                refs = getattr(section, "source_refs", []) or [] if section is not None else []
                source_ref_total += len(refs)
                if section is not None and not refs:
                    deficiencies.append(section_code)
            imported_without_generation_link = getattr(context.solution, "generation_run", None) is None
            rag_summary = dict(support.support_summary.get("rule_rag") or {})
            has_rule_rag = int(rag_summary.get("rules_with_evidence") or 0) > 0
            if not deficiencies:
                status = CheckResultStatus.PASSED
            elif imported_without_generation_link or (source_ref_total == 0 and has_rule_rag):
                status = CheckResultStatus.WARNING
            else:
                status = CheckResultStatus.FAILED
            return self.result(
                rule=rule,
                status=status,
                finding=None
                if status == CheckResultStatus.PASSED
                else (
                    "У импортированной или несвязанной архитектуры нет сохраненных source_ref в секциях; проверка использует выбранные документы базы знаний и RAG-доказательства по правилам."
                    if status == CheckResultStatus.WARNING
                    else "Для части ключевых разделов нет ссылок на основания: "
                    f"{_section_list(deficiencies)}."
                ),
                evidence=_section_list(deficiencies)
                if deficiencies
                else str(source_ref_total),
                diagnostics={
                    "sections_missing_evidence": deficiencies,
                    "source_ref_total": source_ref_total,
                    "imported_without_generation_link": imported_without_generation_link,
                    "rule_rag": rag_summary,
                },
                related_section_ref=deficiencies[0] if deficiencies else None,
            )

        if rule.code == "VR-CNS-03":
            business_components = [
                item
                for item in support.components
                if normalize_architecture_boundary_type(getattr(item, "boundary_type", None))
                == "business_architecture"
            ]
            application_components = [
                item
                for item in support.components
                if normalize_architecture_boundary_type(getattr(item, "boundary_type", None))
                == "application_architecture"
            ]
            business_text = (
                getattr(support.section_by_code.get("business_architecture"), "body_markdown", None)
                or ""
            ).lower()
            app_text = (
                getattr(
                    support.section_by_code.get("application_architecture"), "body_markdown", None
                )
                or ""
            ).lower()
            explicit_relation, relation_fragment = self._has_component_relation(
                business_components,
                application_components,
                texts=[business_text, app_text],
                relation_patterns=self._BUSINESS_APP_LINK_PATTERNS,
            )
            integrated = self._has_integration_link(
                business_components, application_components, support.integrations
            )
            token_overlap, overlap_tokens = self._has_token_overlap(
                business_components, application_components
            )
            supported = bool(application_components) and (
                explicit_relation or integrated or token_overlap
            )
            if not business_components:
                status = CheckResultStatus.NOT_APPLICABLE
                finding = None
            elif supported:
                status = CheckResultStatus.PASSED
                finding = None
            else:
                status = CheckResultStatus.WARNING
                finding = "Бизнес-слой есть, но связь с поддерживающими компонентами приложений выражена слабо."
            evidence = relation_fragment or (
                ", ".join(overlap_tokens)
                if overlap_tokens
                else ", ".join(component.component_name for component in application_components[:8])
                if application_components
                else "компоненты приложений не найдены"
            )
            return self.result(
                rule=rule,
                status=status,
                finding=finding,
                evidence=evidence,
                diagnostics={
                    "business_component_count": len(business_components),
                    "application_component_count": len(application_components),
                    "explicit_relation": explicit_relation,
                    "integration_link": integrated,
                    "token_overlap": overlap_tokens,
                },
                related_section_ref="application_architecture"
                if application_components
                else ("business_architecture" if business_components else None),
            )

        if rule.code == "VR-CNS-04":
            application_components = [
                item
                for item in support.components
                if normalize_architecture_boundary_type(getattr(item, "boundary_type", None))
                == "application_architecture"
            ]
            technology_components = [
                item
                for item in support.components
                if normalize_architecture_boundary_type(getattr(item, "boundary_type", None))
                == "technology_architecture"
            ]
            app_text = (
                getattr(
                    support.section_by_code.get("application_architecture"), "body_markdown", None
                )
                or ""
            ).lower()
            tech_text = (
                getattr(
                    support.section_by_code.get("technology_architecture"), "body_markdown", None
                )
                or ""
            ).lower()
            explicit_relation, relation_fragment = self._has_component_relation(
                application_components,
                technology_components,
                texts=[tech_text, app_text],
                relation_patterns=self._APP_TECH_LINK_PATTERNS,
            )
            integrated = self._has_integration_link(
                application_components, technology_components, support.integrations
            )
            token_overlap, overlap_tokens = self._has_token_overlap(
                application_components, technology_components
            )
            linked = (
                bool(application_components)
                and bool(technology_components)
                and (explicit_relation or integrated or token_overlap)
            )
            if not application_components:
                status = CheckResultStatus.NOT_APPLICABLE
                finding = None
            elif linked:
                status = CheckResultStatus.PASSED
                finding = None
            else:
                status = (
                    CheckResultStatus.WARNING if technology_components else CheckResultStatus.FAILED
                )
                finding = "Слой приложений недостаточно явно связан с технологическими узлами или сервисами."
            evidence = relation_fragment or (
                ", ".join(overlap_tokens)
                if overlap_tokens
                else ", ".join(component.component_name for component in technology_components[:8])
                if technology_components
                else "технологические компоненты не найдены"
            )
            return self.result(
                rule=rule,
                status=status,
                finding=finding,
                evidence=evidence,
                diagnostics={
                    "application_component_count": len(application_components),
                    "technology_component_count": len(technology_components),
                    "explicit_relation": explicit_relation,
                    "integration_link": integrated,
                    "token_overlap": overlap_tokens,
                },
                related_section_ref="technology_architecture"
                if technology_components
                else "application_architecture",
            )

        if rule.code == "VR-CNS-05":
            data_text = (
                getattr(support.section_by_code.get("data_architecture"), "body_markdown", None)
                or ""
            ).lower()
            has_data_object = (
                "data object" in data_text
                or "объект данных" in data_text
                or "business object" in data_text
                or "бизнес-объект" in data_text
            )
            has_source = self._has_any(
                data_text, ["source", "producer", "owner", "источник", "владел", "создает"]
            )
            has_consumer = self._has_any(
                data_text, ["consumer", "target", "receiver", "потребител", "получат", "использует"]
            )
            if not data_text and not support.integrations:
                status = CheckResultStatus.NOT_APPLICABLE
                finding = None
            elif has_data_object and has_source and has_consumer:
                status = CheckResultStatus.PASSED
                finding = None
            else:
                status = CheckResultStatus.WARNING
                finding = "Архитектура данных недостаточно явно показывает источник, владельца или потребителя ключевых объектов данных."
            return self.result(
                rule=rule,
                status=status,
                finding=finding,
                evidence=f"интеграции: {len(support.integrations)}",
                diagnostics={
                    "has_data_object": has_data_object,
                    "has_source": has_source,
                    "has_consumer": has_consumer,
                },
                related_section_ref="data_architecture"
                if "data_architecture" in support.section_codes
                else None,
            )

        if rule.code == "VR-CNS-06":
            business_task = getattr(context.solution, "business_task", None)
            task_text = (
                (
                    (getattr(business_task, "title", None) or "")
                    + " "
                    + (getattr(business_task, "task_text", None) or "")
                )
                .strip()
                .lower()
            )
            tokens = {
                token
                for token in re.findall(r"[a-zA-Zа-яА-Я0-9_\-]{4,}", task_text)
                if token
                not in {
                    "which",
                    "that",
                    "with",
                    "from",
                    "this",
                    "для",
                    "надо",
                    "нужно",
                    "будет",
                    "система",
                }
            }
            matched_components = [
                name
                for name in component_names
                if any(token in name.lower() for token in list(tokens)[:24])
            ]
            matched_text = [token for token in list(tokens)[:24] if token in normalized_text]
            if matched_components or matched_text:
                status = CheckResultStatus.PASSED
                finding = None
            else:
                status = CheckResultStatus.WARNING
                finding = (
                    "Прослеживаемость от формулировки бизнес-задачи до архитектурных решений выражена слабо."
                )
            return self.result(
                rule=rule,
                status=status,
                finding=finding,
                evidence=", ".join(matched_components[:8])
                if matched_components
                else (
                    ", ".join(matched_text[:8])
                    if matched_text
                    else str(getattr(context.solution, "business_task_id", "неизвестно"))
                ),
                diagnostics={
                    "matched_components": matched_components[:12],
                    "matched_task_tokens": matched_text[:12],
                },
                related_section_ref="business_tasks_description"
                if "business_tasks_description" in support.section_codes
                else None,
            )

        return self.result(
            rule=rule,
            status=CheckResultStatus.NOT_DETERMINED,
            finding="Правило согласованности не поддерживается обработчиком проверки.",
            evidence=rule.code,
            diagnostics={"group": "consistency"},
        )


class NfrRulesExecutor(_BaseRuleExecutor):
    _RULE_PATTERNS = {
        "VR-NFR-01": {
            "section": "technology_architecture",
            "patterns": [
                "security",
                "secure",
                "authentication",
                "authorization",
                "auth",
                "oauth",
                "sso",
                "mfa",
                "rbac",
                "tls",
                "ssl",
                "encryption",
                "шифр",
                "безопас",
                "аутенти",
                "авториз",
                "доступ",
                "роль",
                "персональн",
            ],
            "finding": "Безопасность не описана явно: нужно указать контроль доступа, аутентификацию, авторизацию или шифрование.",
        },
        "VR-NFR-02": {
            "section": "technology_architecture",
            "patterns": [
                "availability",
                "fault tolerance",
                "failover",
                "ha",
                "replication",
                "redundancy",
                "resilience",
                "доступност",
                "отказоуст",
                "резервирован",
                "реплика",
                "кластер",
            ],
            "finding": "Доступность и отказоустойчивость не описаны явно: нужно указать резервирование, failover или поведение при восстановлении.",
        },
        "VR-NFR-03": {
            "section": "technology_architecture",
            "patterns": [
                "performance",
                "latency",
                "throughput",
                "rps",
                "load",
                "scalability",
                "scale",
                "cache",
                "sla",
                "производ",
                "задерж",
                "нагруз",
                "масштаб",
                "кэш",
            ],
            "finding": "Производительность и масштабирование не описаны явно: нужно указать ожидаемую нагрузку, latency/SLA или подход к масштабированию.",
        },
        "VR-NFR-04": {
            "section": "technology_architecture",
            "patterns": [
                "monitoring",
                "observability",
                "metrics",
                "logs",
                "logging",
                "tracing",
                "alert",
                "prometheus",
                "grafana",
                "монитор",
                "наблюдаем",
                "метрик",
                "лог",
                "трасс",
                "алерт",
                "оповещ",
            ],
            "finding": "Мониторинг и наблюдаемость не описаны явно: нужно указать метрики, логи, трассировку и оповещения.",
        },
        "VR-NFR-05": {
            "section": "additional_information",
            "patterns": [
                "backup",
                "restore",
                "recovery",
                "rpo",
                "rto",
                "disaster recovery",
                "archive",
                "резервн",
                "бэкап",
                "восстанов",
                "аварийн",
            ],
            "finding": "Резервное копирование и восстановление не описаны явно: нужно указать частоту backup, сценарий restore, RPO/RTO или DR-допущения.",
        },
    }

    def _nfr_text(self, support: VerificationSupportContext) -> str:
        component_text = "\n".join(
            " ".join(
                str(part or "")
                for part in [
                    getattr(component, "component_name", None),
                    getattr(component, "role_description", None),
                    getattr(component, "technology_stack", None),
                ]
            )
            for component in support.components
        )
        risk_text = "\n".join(
            " ".join(
                str(part or "")
                for part in [
                    getattr(risk, "title", None),
                    getattr(risk, "description", None),
                    getattr(risk, "mitigation", None),
                ]
            )
            for risk in support.risks
        )
        list_text = "\n".join(
            str(getattr(item, "item_text", "") or "")
            for item in [*support.assumptions, *support.next_steps]
        )
        return "\n".join([support.combined_section_text, component_text, risk_text, list_text]).lower()

    def execute(
        self,
        *,
        rule: VerificationRuleDefinition,
        context: VerificationExecutionContext,
        support: VerificationSupportContext,
    ) -> VerificationCheckResultPayload:
        del context
        rule_config = self._RULE_PATTERNS.get(rule.code)
        if rule_config is None:
            return self.result(
                rule=rule,
                status=CheckResultStatus.NOT_DETERMINED,
                finding="Правило нефункциональных требований не поддерживается обработчиком проверки.",
                evidence=rule.code,
                diagnostics={"group": "nfr"},
            )
        haystack = self._nfr_text(support)
        patterns = list(rule_config["patterns"])
        matched = [pattern for pattern in patterns if pattern in haystack]
        related_section_ref = str(rule_config["section"])
        has_section = related_section_ref in support.section_codes
        status = CheckResultStatus.PASSED if matched else CheckResultStatus.WARNING
        return self.result(
            rule=rule,
            status=status,
            finding=None if matched else str(rule_config["finding"]),
            evidence=", ".join(matched[:8]) if matched else "термины NFR не найдены",
            diagnostics={
                "matched_terms": matched[:12],
                "expected_terms": patterns[:20],
                "section_present": has_section,
            },
            related_section_ref=related_section_ref if has_section else None,
        )


def aggregate_summary_status(
    results: list[VerificationCheckResultPayload],
) -> ProtocolSummaryStatus:
    statuses = {item.status for item in results}
    if CheckResultStatus.NOT_DETERMINED in statuses:
        return ProtocolSummaryStatus.INCOMPLETE
    if CheckResultStatus.FAILED in statuses:
        return ProtocolSummaryStatus.FAILED
    if CheckResultStatus.WARNING in statuses:
        return ProtocolSummaryStatus.PASSED_WITH_COMMENTS
    return ProtocolSummaryStatus.PASSED


def calculate_verification_score(results: list[VerificationCheckResultPayload]) -> int:
    severity_weights = {
        "info": 1.0,
        "minor": 2.0,
        "major": 4.0,
        "critical": 6.0,
    }
    status_multipliers = {
        CheckResultStatus.PASSED: 1.0,
        CheckResultStatus.NOT_APPLICABLE: 1.0,
        CheckResultStatus.WARNING: 0.55,
        CheckResultStatus.FAILED: 0.0,
        CheckResultStatus.NOT_DETERMINED: 0.0,
    }
    total = 0.0
    earned = 0.0
    for item in results:
        severity_value = getattr(item.severity, "value", item.severity)
        weight = severity_weights.get(str(severity_value or "").lower(), 3.0)
        total += weight
        earned += weight * status_multipliers.get(item.status, 0.0)
    if total <= 0:
        return 0
    return max(0, min(100, round((earned / total) * 100)))


def build_summary(
    status: ProtocolSummaryStatus, results: list[VerificationCheckResultPayload]
) -> str:
    failed = sum(1 for item in results if item.status == CheckResultStatus.FAILED)
    warnings = sum(1 for item in results if item.status == CheckResultStatus.WARNING)
    incomplete = sum(1 for item in results if item.status == CheckResultStatus.NOT_DETERMINED)
    passed = sum(1 for item in results if item.status == CheckResultStatus.PASSED)
    score = calculate_verification_score(results)
    group_counts: dict[str, dict[str, int]] = {}
    for item in results:
        group = item.rule_group or "other"
        bucket = group_counts.setdefault(
            group, {"failed": 0, "warnings": 0, "incomplete": 0, "passed": 0}
        )
        if item.status == CheckResultStatus.FAILED:
            bucket["failed"] += 1
        elif item.status == CheckResultStatus.WARNING:
            bucket["warnings"] += 1
        elif item.status == CheckResultStatus.NOT_DETERMINED:
            bucket["incomplete"] += 1
        elif item.status == CheckResultStatus.PASSED:
            bucket["passed"] += 1
    group_labels = {
        "technical": "техническая готовность",
        "structure": "структура",
        "normative": "нормативная база",
        "consistency": "согласованность",
        "nfr": "NFR",
        "other": "прочее",
    }
    group_summary = "; ".join(
        (
            f"{group_labels.get(group, group)}: ошибок {values['failed']}, "
            f"замечаний {values['warnings']}, не определено {values['incomplete']}"
        )
        for group, values in sorted(group_counts.items())
    )
    status_labels = {
        ProtocolSummaryStatus.PASSED: "проверка пройдена без замечаний",
        ProtocolSummaryStatus.PASSED_WITH_COMMENTS: "проверка пройдена с замечаниями",
        ProtocolSummaryStatus.FAILED: "есть блокирующие нарушения",
        ProtocolSummaryStatus.INCOMPLETE: "результат неполный",
    }
    base = (
        f"Оценка проверки: {score}/100. Итог: "
        f"{status_labels.get(status, status.value)}. "
        f"Пройдено: {passed}; ошибок: {failed}; предупреждений: {warnings}; "
        f"не определено: {incomplete}."
    )
    return f"{base} Разбивка по группам: {group_summary}." if group_summary else base
