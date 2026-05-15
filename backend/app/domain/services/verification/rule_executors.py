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
    validate_archimate_alignment,
)
from app.domain.services.knowledge_basis import build_basis_inventory_for_version_documents
from app.integrations.verification import (
    VerificationCheckResultPayload,
    VerificationRuleDefinition,
)

from .common import VerificationExecutionContext
from .document_scope import filter_version_documents


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
    support_summary: dict[str, Any]

    def evidence_for_roles(self, *roles: str) -> str | None:
        parts: list[str] = []
        for role in roles:
            fragments = self.required_fragments_by_role.get(role) or []
            if not fragments:
                continue
            fragment_ids = ",".join(str(fragment.fragment_id) for fragment in fragments[:3])
            parts.append(f"{role}:{fragment_ids}")
        return "; ".join(parts) if parts else None

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
            support_summary=dict(support_context.get("support_summary") or {}),
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
                    finding="Solution status cannot be determined.",
                    evidence=str(getattr(solution, "solution_version_id", "unknown")),
                    diagnostics={"solution_status": None},
                )
            ok = status_value == SolutionVersionStatus.PUBLISHED.value
            return self.result(
                rule=rule,
                status=CheckResultStatus.PASSED if ok else CheckResultStatus.FAILED,
                finding=None
                if ok
                else "Solution does not exist in published state and is not ready for verification.",
                evidence=str(getattr(solution, "solution_version_id", "unknown")),
                diagnostics={"solution_status": status_value},
            )

        if rule.code == "VR-TEC-02":
            knowledge_version_id = str(getattr(context.run, "knowledge_version_id", "") or "")
            if not knowledge_version_id:
                return self.result(
                    rule=rule,
                    status=CheckResultStatus.FAILED,
                    finding="Verification run is missing a fixed knowledge version.",
                    evidence="knowledge_version:missing",
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
            status = CheckResultStatus.PASSED if not missing else CheckResultStatus.FAILED
            return self.result(
                rule=rule,
                status=status,
                finding=None
                if not missing
                else f"Knowledge version is missing required basis packages: {', '.join(missing)}.",
                evidence=", ".join(
                    item["role_code"] for item in support.basis_inventory.required_packages
                ),
                diagnostics={
                    "required_packages": support.basis_inventory.required_packages,
                    "missing_required_packages": missing,
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
                    finding="Protocol basis documents section is empty.",
                    evidence="basis_documents:0",
                    diagnostics={"basis_document_count": 0},
                )
            return self.result(
                rule=rule,
                status=CheckResultStatus.PASSED,
                evidence=f"basis_documents:{effective_basis_count}",
                diagnostics={"basis_document_count": effective_basis_count},
            )

        return self.result(
            rule=rule,
            status=CheckResultStatus.NOT_DETERMINED,
            finding="Unsupported technical rule.",
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
                finding=None if ok else "Goal and/or task context are not sufficiently captured.",
                evidence=str(getattr(solution, "business_task_id", "unknown")),
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
                else "Constraints and assumptions are only partially captured."
                if status == CheckResultStatus.WARNING
                else "Constraints and assumptions are missing.",
                evidence="constraints_assumptions",
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
                else "Component composition is under-specified."
                if status == CheckResultStatus.WARNING
                else "Component composition is not described.",
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
                    evidence="integrations:not_mentioned",
                    diagnostics={"integration_count": 0},
                )
            if integration_count == 0:
                return self.result(
                    rule=rule,
                    status=CheckResultStatus.FAILED,
                    finding="Integrations/API are mentioned but not structurally disclosed.",
                    evidence="integrations:mentioned_without_model",
                    diagnostics={"integration_count": 0},
                    related_section_ref=self._first_section_ref(
                        support, "data_architecture", "application_architecture"
                    ),
                )
            incomplete = [
                str(getattr(item, "integration_id", "unknown"))
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
                else "Some integrations are missing protocol, rationale, or TOGAF section disclosure.",
                evidence=", ".join(incomplete)
                if incomplete
                else f"integrations:{integration_count}",
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
                else "Risks/open questions are shallow or missing."
                if status == CheckResultStatus.WARNING
                else "Risks/open questions block is missing.",
                evidence=f"risks:{risk_count}",
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
                else f"Mandatory TOGAF sections are missing: {', '.join(missing_sections)}.",
                evidence=", ".join(sorted(support.section_codes))
                if support.section_codes
                else "sections:none",
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
                else "TOGAF sections are not ordered according to the canonical document structure.",
                evidence=", ".join(canonical_subset) if canonical_subset else "section_order:none",
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
            finding="Unsupported structure rule.",
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
                return self.result(
                    rule=rule,
                    status=CheckResultStatus.NOT_DETERMINED,
                    finding="Required ODA / IG1242 basis fragments are unavailable for normative evaluation.",
                    evidence="oda,ig1242:missing",
                    diagnostics={"required_roles": ["oda", "ig1242_oda_component_inventory"]},
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
                finding = "Solution explicitly contradicts ODA / IG1242 alignment assumptions."
            elif selected_document_scope or {"oda", "ig1242_oda_component_inventory"} & role_refs:
                status = CheckResultStatus.PASSED
                finding = None
            else:
                status = CheckResultStatus.WARNING
                finding = "ODA / IG1242 basis exists, but section-level evidence linkage is weak."
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
                return self.result(
                    rule=rule,
                    status=CheckResultStatus.NOT_DETERMINED,
                    finding="ArchiMate 3.2 basis fragments are unavailable for normative evaluation.",
                    evidence="archimate_3_2:missing",
                    diagnostics={"required_roles": ["archimate_3_2"]},
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
                finding = "Solution terminology or structure contradicts ArchiMate 3.2 alignment assumptions."
            elif has_allowed_content:
                status = CheckResultStatus.PASSED
                finding = None
            else:
                status = CheckResultStatus.WARNING
                finding = "Solution structure only partially demonstrates ArchiMate 3.2 layer decomposition."
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
                return self.result(
                    rule=rule,
                    status=CheckResultStatus.NOT_DETERMINED,
                    finding="Technology standard basis fragments are unavailable for normative evaluation.",
                    evidence="technology_standard:missing",
                    diagnostics={"required_roles": ["technology_standard"]},
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
                finding = f"Selected technologies conflict with the technology standard: {', '.join(sorted(set(prohibited_hits)))}."
            elif aligned_hits:
                status = CheckResultStatus.PASSED
                finding = None
            else:
                status = CheckResultStatus.WARNING
                finding = "Technology choices are not clearly evidenced against the selected technology standard."
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
                    evidence="template_or_principles:not_loaded",
                    diagnostics={"basis_present": False},
                )
            evidence = (
                support.evidence_for_roles("template_or_principles") or "template_or_principles"
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
                finding = "Required templates/principles exist but mandatory sections for applying them are missing."
            else:
                status = CheckResultStatus.WARNING
                finding = "Templates/principles package is present, but its usage is not obvious in the solution."
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
                else f"Non-whitelisted ArchiMate elements were detected in sections: {', '.join(violating_sections)}.",
                evidence=", ".join(sorted(section_alignments))
                if section_alignments
                else "archimate_alignments:none",
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
                finding = "Architecture sections required for ArchiMate alignment are missing."
            elif weak_sections:
                status = CheckResultStatus.WARNING
                finding = f"Some architecture sections do not expose enough allowed ArchiMate objects: {', '.join(weak_sections)}."
            else:
                status = CheckResultStatus.PASSED
                finding = None
            return self.result(
                rule=rule,
                status=status,
                finding=finding,
                evidence=", ".join(sorted(section_alignments))
                if section_alignments
                else "archimate_alignments:none",
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
            finding="Unsupported normative rule.",
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
                str(getattr(item, "integration_id", "unknown"))
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
                        "solution declares no integrations but integrations exist"
                    )
                if (
                    "без api" in lowered
                    or "api не требуется" in lowered
                    or "api не нужен" in lowered
                ) and "api" in normalized_text:
                    contradiction_reasons.append("solution declares no API but API is described")
                if ("без внешн" in lowered or "только внутрен" in lowered) and (
                    has_external_components or has_integrations
                ):
                    contradiction_reasons.append(
                        "solution declares internal-only contour but contains external participants or integrations"
                    )
                if (
                    "только batch" in lowered
                    or "только пакет" in lowered
                    or "только оффлайн" in lowered
                ) and self._has_any(protocols, ["http", "rest", "grpc", "websocket", "api"]):
                    contradiction_reasons.append(
                        "solution declares batch/offline mode but uses synchronous online protocols"
                    )
            issues = []
            if duplicate_component_names:
                issues.append("duplicate component names")
            if broken_integrations:
                issues.append("broken integration references")
            if contradiction_reasons:
                issues.extend(contradiction_reasons)
            return self.result(
                rule=rule,
                status=CheckResultStatus.PASSED if not issues else CheckResultStatus.FAILED,
                finding=None
                if not issues
                else f"Internal consistency issues detected: {'; '.join(issues)}.",
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
                if section is not None and not refs:
                    deficiencies.append(section_code)
            status = CheckResultStatus.PASSED if not deficiencies else CheckResultStatus.FAILED
            return self.result(
                rule=rule,
                status=status,
                finding=None
                if status == CheckResultStatus.PASSED
                else f"Some key sections still lack evidence linkage: {', '.join(deficiencies)}.",
                evidence=", ".join(deficiencies)
                if deficiencies
                else str(
                    sum(
                        len(getattr(section, "source_refs", []) or [])
                        for section in support.section_by_code.values()
                    )
                ),
                diagnostics={"sections_missing_evidence": deficiencies},
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
                finding = "Business layer is present, but linkage to supporting application components is weak."
            evidence = relation_fragment or (
                ", ".join(overlap_tokens)
                if overlap_tokens
                else ", ".join(component.component_name for component in application_components[:8])
                if application_components
                else "application_components:none"
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
                finding = "Application layer is not clearly tied to technology nodes/services."
            evidence = relation_fragment or (
                ", ".join(overlap_tokens)
                if overlap_tokens
                else ", ".join(component.component_name for component in technology_components[:8])
                if technology_components
                else "technology_components:none"
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
                finding = "Data architecture does not clearly show source, owner, or consumer context for key data objects."
            return self.result(
                rule=rule,
                status=status,
                finding=finding,
                evidence=f"integrations:{len(support.integrations)}",
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
                    "Traceability from business task wording to architecture decisions is weak."
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
                    else str(getattr(context.solution, "business_task_id", "unknown"))
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
            finding="Unsupported consistency rule.",
            evidence=rule.code,
            diagnostics={"group": "consistency"},
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


def build_summary(
    status: ProtocolSummaryStatus, results: list[VerificationCheckResultPayload]
) -> str:
    failed = sum(1 for item in results if item.status == CheckResultStatus.FAILED)
    warnings = sum(1 for item in results if item.status == CheckResultStatus.WARNING)
    incomplete = sum(1 for item in results if item.status == CheckResultStatus.NOT_DETERMINED)
    group_counts: dict[str, dict[str, int]] = {}
    for item in results:
        group = item.rule_group or "other"
        bucket = group_counts.setdefault(group, {"failed": 0, "warnings": 0, "incomplete": 0})
        if item.status == CheckResultStatus.FAILED:
            bucket["failed"] += 1
        elif item.status == CheckResultStatus.WARNING:
            bucket["warnings"] += 1
        elif item.status == CheckResultStatus.NOT_DETERMINED:
            bucket["incomplete"] += 1
    group_summary = "; ".join(
        f"{group}: failed={values['failed']}, warnings={values['warnings']}, incomplete={values['incomplete']}"
        for group, values in sorted(group_counts.items())
    )
    base = f"Verification verdict: {status.value}. Failed checks: {failed}; warnings: {warnings}; incomplete: {incomplete}."
    return f"{base} Breakdown by rule group — {group_summary}." if group_summary else base
