from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from difflib import SequenceMatcher
from typing import Any

from app.core.exceptions import ValidationError
from app.db.enums import (
    GenerationRunStatus,
)
from app.domain.architecture import (
    REQUIRED_TOGAF_SECTION_CODES,
    normalize_architecture_boundary_type,
    validate_archimate_alignment,
)
from app.integrations.generation import (
    RetrievedFragment,
)
from app.integrations.generation.contracts import REQUIRED_SECTION_CODES, GenerationSolutionPayload

logger = logging.getLogger(__name__)

TERMINAL_GENERATION_STATUSES = {
    GenerationRunStatus.COMPLETED,
    GenerationRunStatus.FAILED,
    GenerationRunStatus.CANCELED,
}


class GenerationPostValidator:
    GENERIC_MARKERS = {
        "todo",
        "tbd",
        "lorem ipsum",
        "placeholder",
        "template",
        "шаблон",
        "пример заполнения",
        "нужно уточнить",
        "требует уточнения",
        "будет определено позже",
        "to be defined",
        "to be decided",
    }
    CRITICAL_SECTION_CODES = set(REQUIRED_TOGAF_SECTION_CODES)
    MIN_SECTION_BODY_LENGTH = 60
    ONLINE_PROTOCOL_MARKERS = {
        "http",
        "https",
        "rest",
        "grpc",
        "websocket",
        "graphql",
        "soap",
        "api",
    }
    OFFLINE_CONSTRAINT_MARKERS = {
        "без интегра",
        "только batch",
        "только пакет",
        "только оффлайн",
        "api не требуется",
        "api не нужен",
    }

    def _is_low_signal_text(self, value: str | None, *, min_length: int = 24) -> bool:
        if value is None:
            return True
        normalized = " ".join(value.strip().split())
        if len(normalized) < min_length:
            return True
        lowered = normalized.lower()
        if any(marker in lowered for marker in self.GENERIC_MARKERS):
            return True
        return sum(1 for char in normalized if char.isalpha()) < 8

    def validate(
        self,
        payload: GenerationSolutionPayload,
        retrieved_fragments: list[RetrievedFragment] | None = None,
    ) -> dict[str, Any]:
        component_names = [component.component_name for component in payload.components]
        component_name_set = set(component_names)
        section_code_counts: dict[str, int] = {}
        sections_by_code = {section.section_code: section for section in payload.sections}
        for section in payload.sections:
            section_code_counts[section.section_code] = (
                section_code_counts.get(section.section_code, 0) + 1
            )
        section_codes = set(section_code_counts)
        missing_sections = [code for code in REQUIRED_SECTION_CODES if code not in section_codes]
        unexpected_sections = sorted(section_codes - set(REQUIRED_SECTION_CODES))
        if missing_sections:
            raise ValidationError(
                f"Required sections are missing after validation: {', '.join(missing_sections)}",
                error_code="SOLUTION_REQUIRED_SECTIONS_MISSING",
            )
        if unexpected_sections:
            raise ValidationError(
                f"Unexpected sections are not allowed in canonical TOGAF mode: {', '.join(unexpected_sections)}",
                error_code="SOLUTION_UNEXPECTED_SECTIONS",
            )
        if len(component_name_set) != len(payload.components):
            raise ValidationError(
                "Duplicate component names are not allowed",
                error_code="SOLUTION_COMPONENT_DUPLICATES",
            )
        for integration in payload.integrations:
            if (
                integration.from_component not in component_name_set
                or integration.to_component not in component_name_set
            ):
                raise ValidationError(
                    "Integration refers to an unknown component",
                    error_code="SOLUTION_INTEGRATION_COMPONENT_MISMATCH",
                )
        if not payload.assumptions:
            raise ValidationError(
                "Нужно указать хотя бы одно допущение.",
                error_code="SOLUTION_ASSUMPTIONS_REQUIRED",
            )
        if not payload.next_steps:
            raise ValidationError(
                "Нужно указать хотя бы один следующий шаг.",
                error_code="SOLUTION_NEXT_STEPS_REQUIRED",
            )
        if len(payload.executive_summary.strip()) < 80:
            raise ValidationError(
                "Краткое резюме решения слишком короткое для публикации.",
                error_code="SOLUTION_EXECUTIVE_SUMMARY_TOO_SHORT",
            )
        if self._is_low_signal_text(payload.executive_summary, min_length=80):
            raise ValidationError(
                "Краткое резюме решения слишком общее для публикации.",
                error_code="SOLUTION_EXECUTIVE_SUMMARY_GENERIC",
            )
        if any(marker in payload.solution_title.lower() for marker in self.GENERIC_MARKERS):
            raise ValidationError(
                "Название решения содержит шаблонный текст.",
                error_code="SOLUTION_TITLE_PLACEHOLDER",
            )
        if self._is_low_signal_text(payload.solution_title, min_length=12):
            raise ValidationError(
                "Название решения слишком общее для публикации.",
                error_code="SOLUTION_TITLE_GENERIC",
            )
        weak_assumptions = [
            item for item in payload.assumptions if self._is_low_signal_text(item, min_length=12)
        ]
        if weak_assumptions:
            raise ValidationError(
                "Допущения должны быть конкретными и не шаблонными.",
                error_code="SOLUTION_ASSUMPTIONS_GENERIC",
            )
        weak_next_steps = [
            item for item in payload.next_steps if self._is_low_signal_text(item, min_length=12)
        ]
        if weak_next_steps:
            raise ValidationError(
                "Следующие шаги должны быть конкретными и исполнимыми.",
                error_code="SOLUTION_NEXT_STEPS_GENERIC",
            )

        retrieved_fragment_ids = {
            item.fragment_id for item in (retrieved_fragments or []) if item.fragment_id
        }
        retrieved_document_ids = {
            item.document_id for item in (retrieved_fragments or []) if item.document_id
        }
        source_backed_sections = 0
        sections_without_refs: list[str] = []
        grounded_sections = 0
        evidence_links = 0
        hallucinated_refs: list[str] = []
        duplicate_section_bodies: dict[str, list[str]] = {}
        seen_section_bodies: list[tuple[str, str]] = []
        repeated_section_codes: list[str] = []
        section_reference_summary: list[dict[str, Any]] = []
        for section in payload.sections:
            body = section.body_markdown.strip()
            if len(body) < self.MIN_SECTION_BODY_LENGTH:
                raise ValidationError(
                    f"Section '{section.section_code}' is too short for publication",
                    error_code="SOLUTION_SECTION_TOO_SHORT",
                )
            if self._is_low_signal_text(body, min_length=self.MIN_SECTION_BODY_LENGTH):
                raise ValidationError(
                    f"Section '{section.section_code}' is too generic for publication",
                    error_code="SOLUTION_SECTION_GENERIC",
                )
            lowered = body.lower()
            if any(marker in lowered for marker in self.GENERIC_MARKERS):
                raise ValidationError(
                    f"Section '{section.section_code}' contains placeholder content",
                    error_code="SOLUTION_PLACEHOLDER_CONTENT",
                )
            normalized_body = self._normalize_section_body_for_duplicate_check(body)
            duplicate_with: str | None = None
            for existing_section_code, existing_body in seen_section_bodies:
                if self._are_effectively_duplicate_bodies(existing_body, normalized_body):
                    duplicate_with = existing_section_code
                    break
            if duplicate_with is not None:
                duplicate_section_bodies.setdefault(duplicate_with, []).append(section.section_code)
            else:
                seen_section_bodies.append((section.section_code, normalized_body))
            if (
                section_code_counts.get(section.section_code, 0) > 1
                and section.section_code not in repeated_section_codes
            ):
                repeated_section_codes.append(section.section_code)
            if section.source_refs:
                source_backed_sections += 1
                evidence_links += len(section.source_refs)
                self._validate_source_refs(
                    section=section,
                    retrieved_fragment_ids=retrieved_fragment_ids,
                    retrieved_document_ids=retrieved_document_ids,
                    hallucinated_refs=hallucinated_refs,
                )
                if self._is_grounded(section, retrieved_fragment_ids, retrieved_document_ids):
                    grounded_sections += 1
            elif section.section_code in self.CRITICAL_SECTION_CODES and self._has_section_evidence(
                section, retrieved_fragments or []
            ):
                sections_without_refs.append(section.section_code)
            section_reference_summary.append(
                {
                    "section_code": section.section_code,
                    "source_ref_count": len(section.source_refs or []),
                    "has_grounded_ref": self._is_grounded(
                        section, retrieved_fragment_ids, retrieved_document_ids
                    ),
                }
            )
        if repeated_section_codes:
            raise ValidationError(
                f"Duplicate section codes are not allowed: {', '.join(sorted(repeated_section_codes))}",
                error_code="SOLUTION_SECTION_DUPLICATES",
            )
        if duplicate_section_bodies:
            raise ValidationError(
                "Multiple sections contain effectively duplicate body content",
                error_code="SOLUTION_DUPLICATE_SECTION_CONTENT",
            )
        if sections_without_refs:
            raise ValidationError(
                "Critical solution sections must include source refs",
                error_code="SOLUTION_SOURCE_REFS_REQUIRED",
            )
        if hallucinated_refs:
            raise ValidationError(
                f"Решение ссылается на фрагменты, которые не были получены из базы знаний: {', '.join(hallucinated_refs[:8])}",
                error_code="SOLUTION_HALLUCINATED_SOURCE_REF",
            )
        if not payload.risks:
            raise ValidationError(
                "Нужно указать хотя бы один риск.",
                error_code="SOLUTION_RISKS_REQUIRED",
            )
        for component in payload.components:
            if self._is_low_signal_text(component.role_description, min_length=20):
                raise ValidationError(
                    "Описание роли компонента должно быть конкретным.",
                    error_code="SOLUTION_COMPONENT_ROLE_GENERIC",
                )
        for integration in payload.integrations:
            if self._is_low_signal_text(integration.rationale, min_length=16):
                raise ValidationError(
                    "Каждая интеграция должна содержать конкретное обоснование.",
                    error_code="SOLUTION_INTEGRATION_RATIONALE_REQUIRED",
                )
        for risk in payload.risks:
            if self._is_low_signal_text(risk.description, min_length=16):
                raise ValidationError(
                    "Описание риска должно быть конкретным.",
                    error_code="SOLUTION_RISK_DESCRIPTION_GENERIC",
                )
            if self._is_low_signal_text(risk.mitigation, min_length=12):
                raise ValidationError(
                    "Меры по риску должны быть конкретными.",
                    error_code="SOLUTION_RISK_MITIGATION_REQUIRED",
                )

        required_section_sequence = [
            section.section_code
            for section in payload.sections
            if section.section_code in REQUIRED_SECTION_CODES
        ]
        if required_section_sequence != REQUIRED_SECTION_CODES:
            raise ValidationError(
                "Разделы решения должны идти в каноническом порядке TOGAF.",
                error_code="SOLUTION_SECTION_ORDER_INVALID",
            )

        architecture_section_codes = [
            "business_architecture",
            "data_architecture",
            "application_architecture",
            "technology_architecture",
        ]
        archimate_alignment: list[dict[str, Any]] = []
        for section_code in architecture_section_codes:
            architecture_section = sections_by_code.get(section_code)
            alignment = validate_archimate_alignment(
                section_code,
                architecture_section.body_markdown if architecture_section is not None else None,
            )
            archimate_alignment.append(alignment)
            if alignment.get("disallowed_element_codes"):
                raise ValidationError(
                    f"Section '{section_code}' contains ArchiMate elements outside the allowed whitelist",
                    error_code="SOLUTION_SECTION_ARCHIMATE_VIOLATION",
                )
            if not alignment.get("has_allowed_content"):
                raise ValidationError(
                    f"Section '{section_code}' does not expose allowed ArchiMate 3.2 objects",
                    error_code="SOLUTION_SECTION_ARCHIMATE_GAP",
                )

        invalid_component_boundaries: list[str] = []
        component_mentions_by_section: dict[str, list[str]] = {
            code: [] for code in architecture_section_codes
        }
        for component in payload.components:
            normalized_boundary = normalize_architecture_boundary_type(component.boundary_type)
            if normalized_boundary not in architecture_section_codes:
                invalid_component_boundaries.append(component.component_name)
                continue
            section_text = self._section_body_lower(sections_by_code, normalized_boundary)
            if component.component_name.lower() in section_text:
                component_mentions_by_section[normalized_boundary].append(component.component_name)
        if invalid_component_boundaries:
            raise ValidationError(
                "Every component must be assigned to a canonical TOGAF architecture subsection",
                error_code="SOLUTION_COMPONENT_BOUNDARY_INVALID",
            )

        missing_component_mentions = [
            component.component_name
            for component in payload.components
            if component.component_name
            not in component_mentions_by_section.get(
                normalize_architecture_boundary_type(component.boundary_type) or "", []
            )
        ]
        if len(missing_component_mentions) == len(component_names):
            raise ValidationError(
                "Architecture subsections do not describe the declared component model",
                error_code="SOLUTION_COMPONENT_SECTION_INCOMPLETE",
            )

        data_section = self._section_body_lower(sections_by_code, "data_architecture")
        application_section = self._section_body_lower(sections_by_code, "application_architecture")
        if payload.integrations:
            topology_text = " ".join(part for part in [data_section, application_section] if part)
            if not topology_text:
                raise ValidationError(
                    "Data/Application architecture sections are required when integrations exist",
                    error_code="SOLUTION_INTEGRATIONS_SECTION_REQUIRED",
                )
            integration_mentions = 0
            section_signal_tokens = self._section_signal_tokens(topology_text)
            for integration in payload.integrations:
                component_tokens = {
                    integration.from_component.lower(),
                    integration.to_component.lower(),
                }
                component_tokens.discard("")
                signal_tokens = self._integration_signal_tokens(integration)
                if component_tokens and all(token in topology_text for token in component_tokens):
                    integration_mentions += 1
                    continue
                if signal_tokens and signal_tokens.intersection(section_signal_tokens):
                    integration_mentions += 1
                    continue
                if self._has_generic_integration_topology_signal(topology_text):
                    integration_mentions += 1
            if integration_mentions == 0:
                raise ValidationError(
                    "Data/Application architecture sections do not explain the declared integration topology",
                    error_code="SOLUTION_INTEGRATIONS_SECTION_INCOMPLETE",
                )

        additional_section = self._section_body_lower(sections_by_code, "additional_information")
        if not additional_section:
            raise ValidationError(
                "Additional information section is required for publication",
                error_code="SOLUTION_ADDITIONAL_SECTION_REQUIRED",
            )
        contradiction_reasons = self._detect_cross_section_contradictions(
            payload=payload, sections_by_code=sections_by_code
        )
        if contradiction_reasons:
            raise ValidationError(
                f"Solution contains internal contradictions: {'; '.join(contradiction_reasons)}",
                error_code="SOLUTION_INTERNAL_CONTRADICTION",
            )

        section_readiness = list(getattr(payload, "section_readiness", []) or [])
        if not section_readiness:
            raise ValidationError(
                "Section readiness assessment must be present for every required TOGAF section",
                error_code="SOLUTION_SECTION_READINESS_REQUIRED",
            )
        if len(section_readiness) < len(REQUIRED_SECTION_CODES):
            raise ValidationError(
                "Section readiness assessment must cover every required TOGAF section",
                error_code="SOLUTION_SECTION_READINESS_INCOMPLETE",
            )
        structured_model = getattr(payload, "structured_model", None)
        if structured_model is None:
            raise ValidationError(
                "Structured architecture model is required for ArchiMate 3.2 validation",
                error_code="SOLUTION_STRUCTURED_MODEL_REQUIRED",
            )
        entity_count = len(getattr(structured_model, "entities", []) or [])
        relation_count = len(getattr(structured_model, "relations", []) or [])
        section_summary_count = len(getattr(structured_model, "section_summaries", []) or [])
        if entity_count < len(payload.components) + len(REQUIRED_SECTION_CODES):
            raise ValidationError(
                "Structured architecture model must include all declared components and TOGAF sections",
                error_code="SOLUTION_STRUCTURED_MODEL_INCOMPLETE",
            )
        if section_summary_count < len(REQUIRED_SECTION_CODES):
            raise ValidationError(
                "Structured architecture model must summarize every required TOGAF section",
                error_code="SOLUTION_STRUCTURED_MODEL_SECTIONS_INCOMPLETE",
            )
        if payload.integrations and relation_count < len(payload.integrations):
            raise ValidationError(
                "Structured architecture model must include all declared architecture relations",
                error_code="SOLUTION_STRUCTURED_MODEL_RELATIONS_INCOMPLETE",
            )
        if payload.components and not relation_count:
            raise ValidationError(
                "Structured architecture model must include at least one relation between architecture objects",
                error_code="SOLUTION_STRUCTURED_MODEL_RELATIONS_REQUIRED",
            )
        citation_coverage = round(source_backed_sections / max(len(payload.sections), 1), 3)
        groundedness_score = round(grounded_sections / max(source_backed_sections, 1), 3)
        if retrieved_fragments and source_backed_sections > 0 and groundedness_score < 0.75:
            raise ValidationError(
                "Generated solution is insufficiently grounded in retrieved evidence",
                error_code="SOLUTION_GROUNDEDNESS_TOO_LOW",
            )
        readiness_status_counts: dict[str, int] = {}
        fallback_sections = []
        for item in section_readiness:
            status_value = getattr(item, "status", "unknown")
            readiness_status_counts[status_value] = readiness_status_counts.get(status_value, 0) + 1
            if getattr(item, "fallback_applied", False):
                fallback_sections.append(getattr(item, "section_code", "unknown"))
        serialized_section_readiness: list[Any] = []
        for item in section_readiness:
            serialized_section_readiness.append(
                item.model_dump() if hasattr(item, "model_dump") else item
            )
        return {
            "required_section_count": len(REQUIRED_SECTION_CODES),
            "component_count": len(payload.components),
            "integration_count": len(payload.integrations),
            "risk_count": len(payload.risks),
            "assumption_count": len(payload.assumptions),
            "next_step_count": len(payload.next_steps),
            "source_backed_sections": source_backed_sections,
            "sections_without_evidence": sections_without_refs,
            "citation_coverage": citation_coverage,
            "grounded_sections": grounded_sections,
            "groundedness_score": groundedness_score,
            "evidence_link_count": evidence_links,
            "hallucinated_ref_count": len(hallucinated_refs),
            "duplicate_section_group_count": len(duplicate_section_bodies),
            "integration_rationale_present": any(
                bool((item.rationale or "").strip()) for item in payload.integrations
            ),
            "risk_mitigation_present": any(
                bool((risk.mitigation or "").strip()) for risk in payload.risks
            ),
            "missing_component_mentions": missing_component_mentions,
            "contradiction_count": len(contradiction_reasons),
            "section_reference_summary": section_reference_summary,
            "section_order_valid": required_section_sequence == REQUIRED_SECTION_CODES,
            "archimate_alignment": archimate_alignment,
            "invalid_component_boundaries": invalid_component_boundaries,
            "section_readiness": serialized_section_readiness,
            "section_readiness_status_counts": readiness_status_counts,
            "fallback_sections": fallback_sections,
            "structured_model_summary": {
                "version": getattr(structured_model, "version", None)
                if structured_model is not None
                else None,
                "entity_count": len(getattr(structured_model, "entities", []) or [])
                if structured_model is not None
                else 0,
                "relation_count": len(getattr(structured_model, "relations", []) or [])
                if structured_model is not None
                else 0,
                "section_count": len(getattr(structured_model, "section_summaries", []) or [])
                if structured_model is not None
                else 0,
            },
        }

    def _detect_cross_section_contradictions(
        self, *, payload: GenerationSolutionPayload, sections_by_code: dict[str, Any]
    ) -> list[str]:
        contradictions: list[str] = []
        assumption_text = " ".join(payload.assumptions).lower()
        protocols = " ".join(
            (integration.protocol or "").lower() for integration in payload.integrations
        )
        if any(marker in assumption_text for marker in self.OFFLINE_CONSTRAINT_MARKERS) and any(
            marker in protocols for marker in self.ONLINE_PROTOCOL_MARKERS
        ):
            contradictions.append(
                "assumptions describe offline/no-API mode while integrations use synchronous online protocols"
            )
        application_section = self._section_body_lower(sections_by_code, "application_architecture")
        data_section = self._section_body_lower(sections_by_code, "data_architecture")
        declared_external = any(component.external_flag for component in payload.components)
        if "только внутрен" in assumption_text and declared_external:
            contradictions.append(
                "assumptions describe internal-only contour while external components are declared"
            )
        if payload.integrations and not (application_section or data_section):
            contradictions.append(
                "integrations exist but data/application architecture sections are empty"
            )
        if (
            payload.components
            and not application_section
            and not any(
                normalize_architecture_boundary_type(component.boundary_type)
                != "application_architecture"
                for component in payload.components
            )
        ):
            contradictions.append(
                "application components exist but application architecture section is empty"
            )
        return contradictions

    @staticmethod
    def _section_body_lower(sections_by_code: Mapping[str, Any], section_code: str) -> str:
        section = sections_by_code.get(section_code)
        if section is None:
            return ""
        return str(getattr(section, "body_markdown", "") or "").lower()

    @staticmethod
    def _has_section_evidence(section, retrieved_fragments: list[RetrievedFragment]) -> bool:
        section_code = str(getattr(section, "section_code", "") or "")
        section_text = str(getattr(section, "body_markdown", "") or "")
        if not section_code or not retrieved_fragments:
            return False

        for fragment in retrieved_fragments:
            metadata = getattr(fragment, "metadata", {}) or {}
            section_tags = GenerationPostValidator._metadata_string_set(
                metadata.get("section_tags")
            )
            architecture_layers = GenerationPostValidator._metadata_string_set(
                metadata.get("architecture_layers")
            )
            if section_code in section_tags or section_code in architecture_layers:
                return True

        section_tokens = {
            token
            for token in re.sub(r"[^\w\s]", " ", section_text.casefold()).split()
            if len(token) >= 4
        }
        if not section_tokens:
            return False
        generic_tokens = {
            token
            for token in re.sub(r"[^\w\s]", " ", section_code.casefold()).split("_")
            if len(token) >= 4
        }
        meaningful_section_tokens = section_tokens - generic_tokens
        for fragment in retrieved_fragments:
            fragment_text = " ".join(
                part
                for part in (
                    getattr(fragment, "title", None),
                    getattr(fragment, "content", None),
                )
                if part
            )
            fragment_tokens = {
                token
                for token in re.sub(r"[^\w\s]", " ", fragment_text.casefold()).split()
                if len(token) >= 4
            }
            if len(meaningful_section_tokens & fragment_tokens) >= 3:
                return True
        return False

    @staticmethod
    def _metadata_string_set(value: Any) -> set[str]:
        if isinstance(value, str):
            return {value} if value else set()
        if isinstance(value, list | tuple | set):
            return {str(item) for item in value if item}
        return set()

    @staticmethod
    def _validate_source_refs(
        *,
        section,
        retrieved_fragment_ids: set[str],
        retrieved_document_ids: set[str],
        hallucinated_refs: list[str],
    ) -> None:
        retrieval_available = bool(retrieved_fragment_ids or retrieved_document_ids)
        for ref in section.source_refs or []:
            if ref.fragment_id and (
                not retrieval_available or ref.fragment_id not in retrieved_fragment_ids
            ):
                hallucinated_refs.append(f"{section.section_code}:fragment:{ref.fragment_id}")
            if ref.document_id and (
                not retrieval_available or ref.document_id not in retrieved_document_ids
            ):
                hallucinated_refs.append(f"{section.section_code}:document:{ref.document_id}")
            if ref.quote_text and len(ref.quote_text.strip()) < 8:
                hallucinated_refs.append(f"{section.section_code}:quote_too_short")

    @staticmethod
    def _has_generic_integration_topology_signal(section_text: str) -> bool:
        generic_tokens = {
            "retrieval",
            "publication",
            "provider",
            "adapter",
            "gateway",
            "orchestration",
            "integration",
            "integrations",
            "workflow",
            "pipeline",
            "exchange",
            "api",
        }
        section_tokens = GenerationPostValidator._section_signal_tokens(section_text)
        return len(section_tokens.intersection(generic_tokens)) >= 2

    @staticmethod
    def _normalize_section_body_for_duplicate_check(value: str) -> str:
        normalized = value.casefold()
        normalized = re.sub(r"```.*?```", " ", normalized, flags=re.DOTALL)
        normalized = re.sub(r"[`*_>#-]+", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    @classmethod
    def _are_effectively_duplicate_bodies(cls, left: str, right: str) -> bool:
        if not left or not right:
            return False
        if left == right:
            return True

        shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
        if len(shorter) < 120:
            return False

        if shorter in longer:
            extra_length = len(longer) - len(shorter)
            if extra_length <= max(32, int(len(shorter) * 0.05)):
                return True

        similarity_ratio = SequenceMatcher(a=left, b=right).ratio()
        return similarity_ratio >= 0.98

    @staticmethod
    def _section_signal_tokens(section_text: str) -> set[str]:
        normalized = section_text.lower()
        for punctuation in ",.;:!?()[]{}<>/|-_":
            normalized = normalized.replace(punctuation, " ")
        return {token for token in normalized.split() if len(token) >= 3}

    @staticmethod
    def _integration_signal_tokens(integration) -> set[str]:
        stop_tokens = {
            "internal",
            "orchestration",
            "bounded",
            "runtime",
            "inside",
            "within",
            "adapter",
            "service",
            "system",
            "module",
            "component",
            "components",
            "integration",
            "integrations",
            "provider",
        }
        collected: set[str] = set()
        for raw_value in (
            integration.interaction or "",
            integration.protocol or "",
            integration.rationale or "",
        ):
            normalized = raw_value.lower()
            for punctuation in ",.;:!?()[]{}<>/|-_":
                normalized = normalized.replace(punctuation, " ")
            for token in normalized.split():
                if len(token) < 6:
                    continue
                if token in stop_tokens:
                    continue
                collected.add(token)
        return collected

    @staticmethod
    def _is_grounded(
        section, retrieved_fragment_ids: set[str], retrieved_document_ids: set[str]
    ) -> bool:
        refs = section.source_refs or []
        for ref in refs:
            if ref.fragment_id and ref.fragment_id in retrieved_fragment_ids:
                return True
            if (
                ref.document_id
                and ref.document_id in retrieved_document_ids
                and ref.quote_text
                and len(ref.quote_text.strip()) >= 8
            ):
                return True
        return False
