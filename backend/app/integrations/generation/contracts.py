from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.enums import Severity
from app.domain.architecture import (
    REQUIRED_TOGAF_SECTION_CODES,
    normalize_architecture_boundary_type,
    normalize_togaf_section_code,
)

_REQUIRED_SECTION_CODES_TUPLE = tuple(REQUIRED_TOGAF_SECTION_CODES)

_SOURCE_REF_TYPED_VALUE_RE = re.compile(
    r"^(?:(?P<section>[a-z][a-z0-9_ -]*):)?(?P<kind>fragment|document)(?:_id)?\s*[:=#/]\s*(?P<identifier>.+)$",
    re.IGNORECASE,
)
_INTEGRATION_ARROW_RE = re.compile(
    r"^(?P<from>.+?)\s*(?:->|→|=>|↔|<->|to)\s*(?P<to>.+?)(?:\s*(?:via|over|using)\s+(?P<protocol>[A-Za-z0-9_./+-]+))?(?:\s*[:\-–—]\s*(?P<interaction>.+))?$",
    re.IGNORECASE,
)

_PLACEHOLDER_SOURCE_REF_IDS = {
    "uuid",
    "fragmentuuid",
    "documentuuid",
    "fragmentid",
    "documentid",
    "sourceid",
    "sourceref",
    "refid",
    "id",
    "placeholder",
    "example",
    "sample",
    "todo",
    "tbd",
    "unknown",
    "none",
    "null",
    "na",
    "n/a",
}


_SEVERITY_ALIAS_GROUPS: dict[Severity, set[str]] = {
    Severity.CRITICAL: {
        "critical",
        "crit",
        "high",
        "highest",
        "severe",
        "blocker",
        "urgent",
        "p0",
        "p1",
        "sev0",
        "sev1",
        "showstopper",
    },
    Severity.MAJOR: {
        "major",
        "medium",
        "moderate",
        "normal",
        "default",
        "important",
        "elevated",
        "p2",
        "sev2",
    },
    Severity.MINOR: {
        "minor",
        "low",
        "small",
        "limited",
        "p3",
        "sev3",
    },
    Severity.INFO: {
        "info",
        "informational",
        "informative",
        "notice",
        "none",
        "na",
        "n_a",
        "p4",
        "sev4",
    },
}


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned or None


_LOW_SIGNAL_RISK_MITIGATION_MARKERS = {
    "-",
    "--",
    "n/a",
    "na",
    "none",
    "todo",
    "tbd",
    "define mitigation plan",
    "mitigation plan",
    "review later",
    "определить план",
    "план смягчения",
    "уточнить позже",
    "нужно уточнить",
}


def _specific_risk_mitigation(title: str | None, description: str | None = None) -> str:
    anchor = title or description or "выявленный архитектурный риск"
    anchor = anchor[:120].rstrip(" .")
    return (
        f"Назначить владельца риска «{anchor}», зафиксировать конкретное действие, "
        "критерий проверки на архитектурном чекпоинте и условие отката, если мера не сработает."
    )


def _is_low_signal_risk_mitigation(value: object) -> bool:
    cleaned = _clean_text(value)
    if not cleaned:
        return True
    lowered = cleaned.lower()
    if len(cleaned) < 24:
        return True
    if lowered in _LOW_SIGNAL_RISK_MITIGATION_MARKERS:
        return True
    if any(
        marker in lowered
        for marker in (
            "define mitigation plan",
            "review later",
            "определить план",
            "уточнить позже",
        )
    ):
        return True
    return sum(1 for char in cleaned if char.isalpha()) < 12


def _normalize_token(value: str) -> str:
    normalized = "".join(char if char.isalnum() else "_" for char in value.strip().lower())
    return "_".join(part for part in normalized.split("_") if part)


def normalize_generation_section_code(value: object) -> str | object:
    cleaned = _clean_text(value)
    if not cleaned:
        return value
    normalized = normalize_togaf_section_code(cleaned)
    if isinstance(normalized, str):
        return normalized
    fallback = _normalize_token(cleaned)
    if fallback.endswith("_section"):
        fallback = fallback.removesuffix("_section")
    return fallback


def _normalize_bool_like(value: object) -> bool | object:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return bool(value)
    cleaned = _clean_text(value)
    if not cleaned:
        return value
    normalized = _normalize_token(cleaned)
    if normalized in {"true", "yes", "y", "1", "external", "public", "outside", "third_party"}:
        return True
    if normalized in {
        "false",
        "no",
        "n",
        "0",
        "internal",
        "private",
        "inside",
        "inhouse",
        "in_house",
    }:
        return False
    return value


def _looks_like_placeholder_source_ref_id(value: object) -> bool:
    cleaned = _clean_text(value)
    if not cleaned:
        return True
    normalized = (
        re.sub(r"[\s<>{}\[\]()\"'`]+", "", cleaned).casefold().replace("-", "").replace("_", "")
    )
    return normalized in _PLACEHOLDER_SOURCE_REF_IDS


def _parse_source_ref_value(
    value: object, *, preferred_target: str | None = None
) -> dict[str, str] | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    cleaned = cleaned.strip("[]{}()<>\"'`")
    if _looks_like_placeholder_source_ref_id(cleaned):
        return None
    match = _SOURCE_REF_TYPED_VALUE_RE.match(cleaned)
    if match:
        identifier = match.group("identifier").strip("[]{}()<>\"'` ")
        if _looks_like_placeholder_source_ref_id(identifier):
            return None
        target_key = (
            "fragment_id" if match.group("kind").casefold() == "fragment" else "document_id"
        )
        return {target_key: identifier}
    if preferred_target in {"fragment_id", "document_id"}:
        return {preferred_target: cleaned}
    return {"fragment_id": cleaned}


def _parse_integration_string(value: object) -> dict[str, str] | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    match = _INTEGRATION_ARROW_RE.match(cleaned)
    if not match:
        return None
    from_component = _clean_text(match.group("from"))
    to_component = _clean_text(match.group("to"))
    protocol = _clean_text(match.group("protocol"))
    interaction = _clean_text(match.group("interaction"))
    if not from_component or not to_component:
        return None
    payload: dict[str, str] = {
        "from_component": from_component,
        "to_component": to_component,
        "interaction": interaction
        or "Coordinates integration flow between the declared components.",
    }
    if protocol:
        payload["protocol"] = protocol
    return payload


def coerce_generation_risk_severity(value: object) -> Severity | object:
    if isinstance(value, Severity):
        return value

    if isinstance(value, int | float) and not isinstance(value, bool):
        numeric_value = int(value)
        numeric_mapping = {
            1: Severity.CRITICAL,
            2: Severity.MAJOR,
            3: Severity.MINOR,
            4: Severity.INFO,
        }
        return numeric_mapping.get(numeric_value, value)

    if not isinstance(value, str):
        return value

    cleaned = value.strip().lower()
    if not cleaned:
        return value

    normalized = "".join(char if char.isalnum() else "_" for char in cleaned)
    normalized = "_".join(part for part in normalized.split("_") if part)
    if not normalized:
        return value

    if normalized in Severity._value2member_map_:
        return Severity(normalized)

    for severity, aliases in _SEVERITY_ALIAS_GROUPS.items():
        if normalized in aliases:
            return severity

    tokens = {token for token in normalized.split("_") if token}
    for severity, aliases in _SEVERITY_ALIAS_GROUPS.items():
        if tokens & aliases:
            return severity

    return value


REQUIRED_SECTION_CODES = list(REQUIRED_TOGAF_SECTION_CODES)


class GenerationSourceRef(BaseModel):
    fragment_id: str | None = None
    document_id: str | None = None
    quote_text: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, value: object) -> object:
        if isinstance(value, str):
            parsed = _parse_source_ref_value(value)
            return parsed or {}
        if not isinstance(value, dict):
            return value
        patched = dict(value)
        parsed_fragment = _parse_source_ref_value(
            patched.get("fragment_id"), preferred_target="fragment_id"
        )
        parsed_document = _parse_source_ref_value(
            patched.get("document_id"), preferred_target="document_id"
        )
        patched["fragment_id"] = parsed_fragment.get("fragment_id") if parsed_fragment else None
        patched["document_id"] = parsed_document.get("document_id") if parsed_document else None
        alias_map = (
            ("fragment_uuid", "fragment_id"),
            ("fragment_ref", "fragment_id"),
            ("fragment", "fragment_id"),
            ("source_ref", "fragment_id"),
            ("source_id", "fragment_id"),
            ("ref", "fragment_id"),
            ("id", "fragment_id"),
            ("document_uuid", "document_id"),
            ("document_ref", "document_id"),
            ("document", "document_id"),
        )
        for alias_key, target_key in alias_map:
            if patched.get(target_key):
                continue
            parsed_alias = _parse_source_ref_value(
                patched.get(alias_key), preferred_target=target_key
            )
            if parsed_alias is not None:
                patched[target_key] = parsed_alias.get(target_key)
        quote = _clean_text(
            patched.get("quote_text")
            or patched.get("quote")
            or patched.get("excerpt")
            or patched.get("snippet")
            or patched.get("text")
        )
        if quote:
            patched["quote_text"] = quote
        return patched

    @model_validator(mode="after")
    def validate_target(self) -> GenerationSourceRef:
        if not self.fragment_id and not self.document_id:
            raise ValueError("source ref must include fragment_id or document_id")
        return self


class GenerationSection(BaseModel):
    section_code: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=300)
    body_markdown: str = Field(min_length=1)
    source_refs: list[GenerationSourceRef] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_section(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        patched = dict(value)
        if "title" not in patched or not _clean_text(patched.get("title")):
            title = _clean_text(
                patched.get("name")
                or patched.get("heading")
                or patched.get("label")
                or patched.get("section_code")
            )
            if title:
                patched["title"] = title
        if "body_markdown" not in patched or not _clean_text(patched.get("body_markdown")):
            body = _clean_text(
                patched.get("body")
                or patched.get("content")
                or patched.get("markdown")
                or patched.get("text")
                or patched.get("description")
                or patched.get("details")
                or patched.get("summary")
            )
            if body:
                patched["body_markdown"] = body
        section_code = (
            patched.get("section_code")
            or patched.get("code")
            or patched.get("name")
            or patched.get("title")
        )
        patched["section_code"] = normalize_generation_section_code(section_code)
        source_refs = patched.get("source_refs")
        if source_refs is None:
            for alias in ("references", "citations", "evidence", "source_ref"):
                if alias in patched:
                    source_refs = patched.get(alias)
                    break
        if source_refs is not None and not isinstance(source_refs, list):
            patched["source_refs"] = [source_refs]
        return patched

    @field_validator("section_code", mode="before")
    @classmethod
    def normalize_section_code(cls, value: object) -> object:
        return normalize_generation_section_code(value)

    @field_validator("title", "body_markdown", mode="before")
    @classmethod
    def clean_text_fields(cls, value: object) -> object:
        return _clean_text(value) or value


class GenerationComponentInterface(BaseModel):
    interface_name: str = Field(min_length=1, max_length=200)
    protocol: str | None = Field(default=None, max_length=100)
    description: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_interface(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = _clean_text(value)
            return {"interface_name": cleaned} if cleaned else value
        if not isinstance(value, dict):
            return value
        patched = dict(value)
        if "interface_name" not in patched:
            patched["interface_name"] = _clean_text(
                patched.get("name")
                or patched.get("title")
                or patched.get("interface")
                or patched.get("endpoint")
            )
        if "protocol" not in patched:
            protocol = _clean_text(patched.get("transport") or patched.get("type"))
            if protocol:
                patched["protocol"] = protocol
        if "description" not in patched:
            description = _clean_text(
                patched.get("details") or patched.get("purpose") or patched.get("summary")
            )
            if description:
                patched["description"] = description
        return patched

    @field_validator("interface_name", "protocol", "description", mode="before")
    @classmethod
    def clean_optional_text(cls, value: object) -> object:
        return _clean_text(value) if value is not None else None


class GenerationComponent(BaseModel):
    component_name: str = Field(min_length=1, max_length=200)
    role_description: str = Field(min_length=1)
    technology_stack: str | None = None
    boundary_type: str | None = Field(default=None, max_length=100)
    external_flag: bool = False
    interfaces: list[GenerationComponentInterface] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_component(cls, value: object) -> object:
        if isinstance(value, str):
            component_name = _clean_text(value)
            if component_name:
                return {
                    "component_name": component_name,
                    "role_description": f"Компонент {component_name} участвует в реализации архитектурного решения и требует дальнейшей детализации.",
                    "interfaces": [],
                }
            return value
        if not isinstance(value, dict):
            return value
        patched = dict(value)
        if "component_name" not in patched:
            patched["component_name"] = _clean_text(
                patched.get("component_code") or patched.get("name") or patched.get("title")
            )
        if "role_description" not in patched:
            role_description = _clean_text(
                patched.get("description")
                or patched.get("role")
                or patched.get("purpose")
                or patched.get("responsibility")
            )
            if role_description:
                patched["role_description"] = role_description
        if "boundary_type" not in patched:
            boundary_type = _clean_text(
                patched.get("boundary") or patched.get("layer") or patched.get("scope")
            )
            if boundary_type:
                patched["boundary_type"] = boundary_type
        if "external_flag" not in patched:
            normalized_external = _normalize_bool_like(
                patched.get("is_external") if "is_external" in patched else patched.get("external")
            )
            if isinstance(normalized_external, bool):
                patched["external_flag"] = normalized_external
        technology_stack = patched.get("technology_stack")
        if technology_stack is None:
            technology_stack = patched.get("stack") or patched.get("technologies")
        if isinstance(technology_stack, list):
            stack_items = [
                cleaned_item
                for item in technology_stack
                if (cleaned_item := _clean_text(str(item)))
            ]
            patched["technology_stack"] = ", ".join(stack_items) or None
        elif isinstance(technology_stack, str):
            patched["technology_stack"] = _clean_text(technology_stack)
        interfaces = patched.get("interfaces")
        if interfaces is None:
            interfaces = (
                patched.get("interface") or patched.get("endpoints") or patched.get("apis") or []
            )
        patched["interfaces"] = (
            interfaces if isinstance(interfaces, list) else [interfaces] if interfaces else []
        )
        return patched

    @field_validator("component_name", "role_description", "technology_stack", mode="before")
    @classmethod
    def clean_component_text(cls, value: object) -> object:
        return _clean_text(value) if value is not None else None

    @field_validator("boundary_type", mode="before")
    @classmethod
    def normalize_boundary_type(cls, value: object) -> object:
        normalized = normalize_architecture_boundary_type(value)
        return normalized or (_clean_text(value) if value is not None else None)

    @field_validator("external_flag", mode="before")
    @classmethod
    def normalize_external_flag(cls, value: object) -> object:
        return _normalize_bool_like(value)


class GenerationIntegration(BaseModel):
    from_component: str = Field(min_length=1, max_length=200)
    to_component: str = Field(min_length=1, max_length=200)
    interaction: str = Field(min_length=1)
    protocol: str | None = Field(default=None, max_length=100)
    rationale: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_integration(cls, value: object) -> object:
        if isinstance(value, str):
            parsed = _parse_integration_string(value)
            return parsed or value
        if not isinstance(value, dict):
            return value
        patched = dict(value)
        if "from_component" not in patched:
            patched["from_component"] = _clean_text(
                patched.get("source")
                or patched.get("from")
                or patched.get("producer")
                or patched.get("caller")
                or patched.get("client")
            )
        if "to_component" not in patched:
            patched["to_component"] = _clean_text(
                patched.get("target")
                or patched.get("to")
                or patched.get("consumer")
                or patched.get("callee")
                or patched.get("server")
                or patched.get("destination")
            )
        if "interaction" not in patched:
            interaction = _clean_text(
                patched.get("interaction")
                or patched.get("description")
                or patched.get("flow")
                or patched.get("purpose")
                or patched.get("details")
                or patched.get("summary")
            )
            if interaction:
                patched["interaction"] = interaction
        if "protocol" not in patched:
            protocol = _clean_text(patched.get("transport") or patched.get("type"))
            if protocol:
                patched["protocol"] = protocol
        if "rationale" not in patched:
            rationale = _clean_text(
                patched.get("reason") or patched.get("justification") or patched.get("why")
            )
            if rationale:
                patched["rationale"] = rationale
        return patched

    @field_validator(
        "from_component", "to_component", "interaction", "protocol", "rationale", mode="before"
    )
    @classmethod
    def clean_integration_text(cls, value: object) -> object:
        return _clean_text(value) if value is not None else None


class GenerationRisk(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    severity: Severity
    description: str = Field(min_length=1)
    mitigation: str | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_severity_aliases(cls, value: object) -> object:
        if isinstance(value, str):
            description = _clean_text(value)
            if description:
                return {
                    "title": description[:80],
                    "severity": Severity.MAJOR,
                    "description": description,
                    "mitigation": _specific_risk_mitigation(description[:80], description),
                }
            return value
        if not isinstance(value, dict):
            return value

        patched = dict(value)
        severity_value = patched.get("severity")
        if not isinstance(severity_value, Severity):
            severity_normalized = coerce_generation_risk_severity(severity_value)
            if isinstance(severity_normalized, Severity):
                patched["severity"] = severity_normalized
        if (
            isinstance(patched.get("severity"), str)
            and patched["severity"].strip()
            or isinstance(patched.get("severity"), Severity)
        ):
            pass
        else:
            for alias in (
                "severity_level",
                "risk_severity",
                "risk_level",
                "criticality",
                "priority",
                "impact_level",
                "impact",
                "level",
            ):
                if alias not in patched:
                    continue
                normalized = coerce_generation_risk_severity(patched.get(alias))
                if isinstance(normalized, Severity):
                    patched["severity"] = normalized
                    break
                if isinstance(normalized, str) and normalized in Severity._value2member_map_:
                    patched["severity"] = Severity(normalized)
                    break
        if "description" not in patched:
            description = _clean_text(
                patched.get("risk")
                or patched.get("risk_description")
                or patched.get("risk_details")
                or patched.get("risk_summary")
                or patched.get("description_text")
                or patched.get("text")
                or patched.get("limitation")
                or patched.get("constraint")
                or patched.get("issue")
                or patched.get("problem")
                or patched.get("open_question")
                or patched.get("details")
                or patched.get("summary")
                or patched.get("body")
            )
            if description:
                patched["description"] = description
        if "title" not in patched:
            title = _clean_text(
                patched.get("name")
                or patched.get("label")
                or patched.get("risk_title")
                or patched.get("risk_name")
                or patched.get("risk_label")
                or patched.get("limitation")
                or patched.get("constraint")
                or patched.get("issue")
            )
            if title:
                patched["title"] = title
        if "description" not in patched:
            title_description = _clean_text(patched.get("title"))
            if title_description:
                patched["description"] = (
                    f"Архитектурный риск «{title_description}» может повлиять на объём, "
                    "сроки, качество или проектные решения, если им не управлять явно."
                )
        if "mitigation" not in patched:
            mitigation = _clean_text(
                patched.get("action")
                or patched.get("response")
                or patched.get("plan")
                or patched.get("mitigate")
                or patched.get("mitigation_plan")
                or patched.get("mitigation_strategy")
                or patched.get("mitigation_steps")
                or patched.get("mitigation_actions")
                or patched.get("risk_mitigation")
                or patched.get("risk_response")
                or patched.get("response_plan")
                or patched.get("control")
                or patched.get("controls")
            )
            if mitigation:
                patched["mitigation"] = mitigation
        if _is_low_signal_risk_mitigation(patched.get("mitigation")):
            patched["mitigation"] = _specific_risk_mitigation(
                _clean_text(patched.get("title")),
                _clean_text(patched.get("description")),
            )
        return patched

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, value: object) -> object:
        return coerce_generation_risk_severity(value)

    @field_validator("title", "description", "mitigation", mode="before")
    @classmethod
    def clean_risk_text(cls, value: object) -> object:
        return _clean_text(value) if value is not None else None


class GenerationSectionReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_code: str = Field(min_length=1, max_length=50)
    heading: str | None = Field(default=None, max_length=300)
    status: str = Field(min_length=1, max_length=30)
    score: float = Field(ge=0.0, le=1.0)
    observed_signal_groups: list[str] = Field(default_factory=list)
    missing_signal_groups: list[str] = Field(default_factory=list)
    minimum_signal_count: int = Field(default=0, ge=0)
    observed_signal_count: int = Field(default=0, ge=0)
    reasons: list[str] = Field(default_factory=list)
    allowed_archimate_elements: list[str] = Field(default_factory=list)
    fallback_applied: bool = False
    archimate_alignment_applied: bool = False


class GenerationStructuredArchitectureModel(BaseModel):
    version: str = Field(default="sectioned-architecture-model.v1", min_length=1, max_length=100)
    entities: list[dict[str, Any]] = Field(default_factory=list)
    relations: list[dict[str, Any]] = Field(default_factory=list)
    section_summaries: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class GenerationSolutionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    solution_title: str = Field(min_length=1, max_length=300)
    executive_summary: str = Field(min_length=1)
    sections: list[GenerationSection] = Field(min_length=1)
    components: list[GenerationComponent] = Field(min_length=1)
    integrations: list[GenerationIntegration] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    risks: list[GenerationRisk] = Field(default_factory=list)
    section_readiness: list[GenerationSectionReadiness] = Field(default_factory=list)
    structured_model: GenerationStructuredArchitectureModel | None = None

    @field_validator("solution_title", "executive_summary", mode="before")
    @classmethod
    def clean_payload_text(cls, value: object) -> object:
        return _clean_text(value) or value

    @field_validator("assumptions", "next_steps", mode="before")
    @classmethod
    def normalize_string_lists(cls, value: object) -> object:
        if value is None:
            return []
        if isinstance(value, list):
            return [
                item
                for item in (
                    (_clean_text(item) if isinstance(item, str) else item) for item in value
                )
                if item not in {None, ""}
            ]
        if isinstance(value, tuple):
            return [
                item
                for item in (
                    (_clean_text(item) if isinstance(item, str) else item) for item in value
                )
                if item not in {None, ""}
            ]
        if isinstance(value, str):
            cleaned = _clean_text(value)
            return [cleaned] if cleaned else []
        return value

    @model_validator(mode="after")
    def validate_required_sections(self) -> GenerationSolutionPayload:
        section_codes = [section.section_code for section in self.sections]
        missing = [code for code in REQUIRED_SECTION_CODES if code not in section_codes]
        unexpected = [code for code in section_codes if code not in REQUIRED_SECTION_CODES]
        duplicates = sorted({code for code in section_codes if section_codes.count(code) > 1})
        if missing:
            raise ValueError(f"missing required sections: {', '.join(missing)}")
        if unexpected:
            raise ValueError(
                f"unexpected sections are not allowed in canonical TOGAF mode: {', '.join(unexpected)}"
            )
        if duplicates:
            raise ValueError(
                f"duplicate sections are not allowed in canonical TOGAF mode: {', '.join(duplicates)}"
            )
        if section_codes != REQUIRED_SECTION_CODES:
            raise ValueError(
                "sections must follow the canonical TOGAF order without extra sections"
            )
        return self
