from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.exceptions import ValidationError
from app.domain.architecture import normalize_architecture_boundary_type
from app.integrations.generation.contracts import GenerationSolutionPayload
from app.integrations.generation.llm_gateway import RetrievedFragment
from app.integrations.generation.payload_normalization import (
    _apply_section_guidance,
    _clean_text_value,
    _coerce_generation_solution_payload,
    _derive_assumptions_from_task,
    _derive_next_steps_from_task,
    _derive_risks_from_task,
)
from app.integrations.generation.payload_normalization_components import (
    _role_description_for_boundary,
)

from .post_validation import GenerationPostValidator

REPAIRABLE_VALIDATION_ERROR_CODES = {
    "SOLUTION_COMPONENT_ROLE_GENERIC",
    "SOLUTION_INTEGRATION_RATIONALE_REQUIRED",
    "SOLUTION_RISK_DESCRIPTION_GENERIC",
    "SOLUTION_RISK_MITIGATION_REQUIRED",
    "SOLUTION_ASSUMPTIONS_GENERIC",
    "SOLUTION_ASSUMPTIONS_REQUIRED",
    "SOLUTION_NEXT_STEPS_GENERIC",
    "SOLUTION_NEXT_STEPS_REQUIRED",
    "SOLUTION_RISKS_REQUIRED",
}

ROLE_TYPE_ONLY_MARKERS = {
    "artifact",
    "business actor",
    "business process",
    "business role",
    "business service",
    "data object",
    "application component",
    "application interface",
    "application service",
    "node",
    "system software",
    "technology service",
}


@dataclass(slots=True)
class GenerationValidationRepairResult:
    payload: GenerationSolutionPayload
    applied: bool
    diagnostics: dict[str, Any]


class GenerationValidationRepairer:
    def __init__(self, *, post_validator: GenerationPostValidator | None = None) -> None:
        self.post_validator = post_validator or GenerationPostValidator()

    def repair(
        self,
        payload: GenerationSolutionPayload,
        *,
        validation_error: ValidationError,
        task_title: str | None,
        task_text: str,
        context_items: list[str],
        retrieved_fragments: list[RetrievedFragment],
    ) -> GenerationValidationRepairResult:
        error_code = getattr(validation_error, "error_code", None)
        diagnostics: dict[str, Any] = {
            "error_code": error_code,
            "error": str(validation_error),
            "repairable": error_code in REPAIRABLE_VALIDATION_ERROR_CODES,
            "actions": [],
        }
        if error_code not in REPAIRABLE_VALIDATION_ERROR_CODES:
            return GenerationValidationRepairResult(payload=payload, applied=False, diagnostics=diagnostics)

        patched = payload.model_dump(mode="json")
        actions: list[dict[str, Any]] = []
        actions.extend(self._repair_component_roles(patched.get("components")))
        actions.extend(self._repair_integration_rationales(patched.get("integrations")))
        actions.extend(
            self._repair_required_text_lists(
                patched,
                payload=payload,
                task_text=task_text,
                context_items=context_items,
            )
        )
        actions.extend(self._repair_risks(patched, payload=payload, task_text=task_text, context_items=context_items))

        diagnostics["actions"] = actions
        if not actions:
            return GenerationValidationRepairResult(payload=payload, applied=False, diagnostics=diagnostics)

        repaired_payload = _coerce_generation_solution_payload(patched)
        repaired_payload, section_guidance = _apply_section_guidance(
            repaired_payload,
            task_title=task_title or "Проект решения",
            task_text=task_text,
            context_items=context_items,
            retrieved_fragments=retrieved_fragments,
        )
        diagnostics["section_guidance"] = section_guidance
        return GenerationValidationRepairResult(
            payload=repaired_payload,
            applied=True,
            diagnostics=diagnostics,
        )

    def _repair_component_roles(self, components: Any) -> list[dict[str, Any]]:
        if not isinstance(components, list):
            return []
        actions: list[dict[str, Any]] = []
        for component in components:
            if not isinstance(component, dict):
                continue
            component_name = _clean_text_value(component.get("component_name"))
            if not component_name:
                continue
            role_description = _clean_text_value(component.get("role_description"))
            if not self._is_component_role_generic(role_description):
                continue
            boundary_type = (
                normalize_architecture_boundary_type(component.get("boundary_type"))
                or "application_architecture"
            )
            component["boundary_type"] = boundary_type
            component["role_description"] = _role_description_for_boundary(
                component_name,
                boundary_type,
            )
            actions.append(
                {
                    "field": "components.role_description",
                    "component_name": component_name,
                    "boundary_type": boundary_type,
                }
            )
        return actions

    def _repair_integration_rationales(self, integrations: Any) -> list[dict[str, Any]]:
        if not isinstance(integrations, list):
            return []
        actions: list[dict[str, Any]] = []
        for integration in integrations:
            if not isinstance(integration, dict):
                continue
            rationale = _clean_text_value(integration.get("rationale"))
            if not self._is_low_signal_text(rationale, min_length=16):
                continue
            from_component = _clean_text_value(integration.get("from_component")) or "исходный компонент"
            to_component = _clean_text_value(integration.get("to_component")) or "целевой компонент"
            interaction = _clean_text_value(integration.get("interaction")) or "интеграционный обмен"
            protocol = _clean_text_value(integration.get("protocol")) or "согласованный внутренний интерфейс"
            integration["rationale"] = (
                f"Связь нужна для сценария «{interaction}»: {from_component} передает результат "
                f"в {to_component} через {protocol} в границах целевой архитектуры."
            )
            actions.append(
                {
                    "field": "integrations.rationale",
                    "from_component": from_component,
                    "to_component": to_component,
                }
            )
        return actions

    def _repair_required_text_lists(
        self,
        patched: dict[str, Any],
        *,
        payload: GenerationSolutionPayload,
        task_text: str,
        context_items: list[str],
    ) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        assumptions = patched.get("assumptions")
        if self._list_has_low_signal_items(assumptions, min_length=12):
            patched["assumptions"] = _derive_assumptions_from_task(
                task_text=task_text,
                context_items=context_items,
                payload=payload,
            )
            actions.append({"field": "assumptions"})
        next_steps = patched.get("next_steps")
        if self._list_has_low_signal_items(next_steps, min_length=12):
            patched["next_steps"] = _derive_next_steps_from_task(
                task_text=task_text,
                context_items=context_items,
                payload=payload,
            )
            actions.append({"field": "next_steps"})
        return actions

    def _repair_risks(
        self,
        patched: dict[str, Any],
        *,
        payload: GenerationSolutionPayload,
        task_text: str,
        context_items: list[str],
    ) -> list[dict[str, Any]]:
        risks = patched.get("risks")
        if not isinstance(risks, list) or not risks:
            patched["risks"] = _derive_risks_from_task(
                task_text=task_text,
                context_items=context_items,
                payload=payload,
            )
            return [{"field": "risks"}]

        actions: list[dict[str, Any]] = []
        for risk in risks:
            if not isinstance(risk, dict):
                continue
            title = _clean_text_value(risk.get("title")) or "Архитектурный риск"
            if self._is_low_signal_text(_clean_text_value(risk.get("description")), min_length=16):
                risk["description"] = (
                    f"Риск «{title}» может повлиять на объем, сроки, качество или эксплуатацию "
                    "решения, если его не контролировать на архитектурных чекпоинтах."
                )
                actions.append({"field": "risks.description", "title": title})
            if self._is_low_signal_text(_clean_text_value(risk.get("mitigation")), min_length=12):
                risk["mitigation"] = (
                    f"Архитектор решения назначает владельца риска «{title}», фиксирует действие "
                    "в плане реализации, проверяет меру на архитектурном чекпоинте и откатывает "
                    "изменение при непрохождении контрольного критерия."
                )
                actions.append({"field": "risks.mitigation", "title": title})
        return actions

    def _is_component_role_generic(self, value: str | None) -> bool:
        cleaned = _clean_text_value(value)
        if self._is_low_signal_text(cleaned, min_length=20):
            return True
        return (cleaned or "").casefold().strip(" .,:;") in ROLE_TYPE_ONLY_MARKERS

    def _list_has_low_signal_items(self, value: Any, *, min_length: int) -> bool:
        if not isinstance(value, list) or not value:
            return True
        return any(self._is_low_signal_text(_clean_text_value(item), min_length=min_length) for item in value)

    def _is_low_signal_text(self, value: str | None, *, min_length: int) -> bool:
        return self.post_validator._is_low_signal_text(value, min_length=min_length)
