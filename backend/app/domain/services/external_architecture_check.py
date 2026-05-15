from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import (
    BusinessTaskStatus,
    GenerationRunStatus,
    SolutionListItemGroup,
    SolutionVersionStatus,
)
from app.db.models.generation import (
    BusinessTask,
    GenerationRun,
    SolutionArchitectureEntity,
    SolutionComponent,
    SolutionIntegration,
    SolutionListItem,
    SolutionRisk,
    SolutionSection,
    SolutionSectionAssessment,
    SolutionVersion,
)
from app.db.repositories.generation import SolutionVersionRepository
from app.domain.architecture import (
    REQUIRED_TOGAF_SECTION_CODES,
    TOGAF_SECTION_ORDER,
    assess_section_readiness,
    default_archimate_element_for_boundary,
    get_archimate_element,
    normalize_architecture_boundary_type,
    normalize_togaf_section_code,
    render_togaf_heading,
)
from app.domain.services.immutable_snapshot import freeze_snapshot
from app.domain.services.knowledge_bases import KnowledgeBaseService
from app.domain.services.knowledge_snapshot import build_knowledge_scope_snapshot
from app.domain.services.presenters import retention_policy_payload
from app.domain.services.principal_keys import principal_owner_key
from app.domain.services.publication import PublicationArtifactService
from app.domain.services.verification_core import VerificationRunService
from app.schemas.mvp import ExternalArchitectureCheckRequest
from app.schemas.verification import InternalVerificationRunStartRequest

_HEADING_RE = re.compile(r"^(?:#{1,6}\s*)?(?P<title>.+?)\s*$")
_ORDERED_HEADING_RE = re.compile(r"^\s*\d+(?:\.\d+)?[.)]?\s+(?P<title>.+?)\s*$")
_COMPONENT_BULLET_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(?P<name>[^:;,.]{3,120})(?:[:;-]\s*(?P<body>.+))?$")


@dataclass(slots=True)
class _SectionInput:
    section_code: str
    title: str
    body_markdown: str


@dataclass(slots=True)
class _ComponentInput:
    component_name: str
    role_description: str
    technology_stack: str | None
    boundary_type: str | None
    external_flag: bool


@dataclass(slots=True)
class _IntegrationInput:
    from_component: str
    to_component: str
    interaction: str
    protocol: str | None
    rationale: str | None


class ExternalArchitectureCheckService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.solutions = SolutionVersionRepository(session)
        self.publication_artifacts = PublicationArtifactService(session)

    def import_and_start_check(
        self, payload: ExternalArchitectureCheckRequest, principal: AuthPrincipal
    ) -> dict[str, Any]:
        owner_key = principal_owner_key(principal)
        knowledge_scope = self._effective_knowledge_scope(principal)
        active_version = knowledge_scope.selected_generation_version()
        if active_version is None:
            raise ValidationError(
                "Active knowledge version is required for external architecture verification",
                error_code="ACTIVE_KNOWLEDGE_VERSION_MISSING",
            )

        knowledge_snapshot = build_knowledge_scope_snapshot(
            mandatory_version=knowledge_scope.mandatory_version,
            selected_user_version=knowledge_scope.selected_user_version,
        )
        sections = self._materialize_sections(payload)
        components = self._materialize_components(payload, sections)
        integrations = self._materialize_integrations(payload, components)
        now = datetime.now(UTC)

        task = self._consume_draft_task(payload, owner_key)
        if task is None:
            task = BusinessTask(
                created_by_user_id=owner_key,
                title=payload.title,
                task_text=payload.architecture_text,
                task_metadata={
                    "source": "external_architecture",
                    "verification_only": True,
                    "original_document_ref": payload.source_ref,
                },
                status=BusinessTaskStatus.COMPLETED,
            )
        else:
            task.title = payload.title
            task.task_text = payload.architecture_text
            task.task_metadata = {
                **dict(task.task_metadata or {}),
                "source": "external_architecture",
                "verification_only": True,
                "original_document_ref": payload.source_ref,
            }
            task.status = BusinessTaskStatus.COMPLETED
            task.updated_at = now
        self.session.add(task)
        self.session.flush()

        input_snapshot = freeze_snapshot(
            {
                "operation": "external_architecture_import",
                "source": "manual_external_architecture",
                "title": payload.title,
                "source_ref": payload.source_ref,
                "architecture_text_length": len(payload.architecture_text),
                "section_codes": [section.section_code for section in sections],
                "component_count": len(components),
                "integration_count": len(integrations),
                "knowledge_version_id": str(active_version.knowledge_version_id),
                "knowledge_version_ids": list(
                    knowledge_snapshot.get("effective_version_ids") or []
                ),
                "knowledge_snapshot": knowledge_snapshot,
                "retention_policy": retention_policy_payload(target_type="solution_version"),
            },
            snapshot_type="external_architecture_import",
        )
        generation_run = GenerationRun(
            business_task_id=task.business_task_id,
            knowledge_version_id=active_version.knowledge_version_id,
            started_by_user_id=owner_key,
            status=GenerationRunStatus.COMPLETED,
            current_stage="completed",
            correlation_id=payload.correlation_id or payload.idempotency_key,
            prompt_version="external-architecture-import.v1",
            started_at=now,
            finished_at=now,
            input_snapshot=input_snapshot,
            diagnostics={
                "source": "external_architecture",
                "verification_only": True,
                "status": "completed",
                "section_codes": [section.section_code for section in sections],
                "component_count": len(components),
                "integration_count": len(integrations),
                "quality_outcomes": {"llm_generation_used": False},
            },
        )
        self.session.add(generation_run)
        self.session.flush()

        solution = SolutionVersion(
            business_task_id=task.business_task_id,
            generation_run_id=generation_run.generation_run_id,
            version_no=self.solutions.get_next_version_no(task.business_task_id),
            solution_title=payload.title,
            executive_summary=self._executive_summary(payload.architecture_text),
            status=SolutionVersionStatus.PUBLISHED,
            published_at=now,
        )
        self.session.add(solution)
        self.session.flush()
        self._persist_sections(solution, sections, payload.architecture_text)
        component_map = self._persist_components(solution, components)
        self._persist_integrations(solution, integrations, component_map)
        self._persist_risks_and_lists(solution, payload)
        self._persist_architecture_entities(solution, components, sections)
        self.session.flush()

        rendered_html = self._render_imported_solution_html(
            solution=solution,
            sections=sections,
            components=components,
            integrations=integrations,
            source_ref=payload.source_ref,
        )
        artifact = self.publication_artifacts.publish(
            artifact_type="external_architecture_view",
            target_type="solution_version",
            target_id=str(solution.solution_version_id),
            rendered_html=rendered_html,
            rendered_markdown=None,
            created_by_user_id=owner_key,
            published_at=now,
            metadata={
                "solution_version_id": str(solution.solution_version_id),
                "generation_run_id": str(generation_run.generation_run_id),
                "source": "external_architecture",
                "llm_generation_used": False,
            },
        )
        solution.rendered_html = rendered_html
        self.session.add(solution)
        self.session.commit()

        verification_run = VerificationRunService(self.session, self.settings).start_run(
            InternalVerificationRunStartRequest(
                solution_version_id=str(solution.solution_version_id),
                validation_scope="full",
                knowledge_document_ids=payload.knowledge_document_ids,
                correlation_id=payload.correlation_id or payload.idempotency_key,
                idempotency_key=payload.idempotency_key,
            ),
            principal,
        )
        protocol_id = (
            str(verification_run.protocol.verification_protocol_id)
            if verification_run.protocol is not None
            else None
        )
        return {
            "task_id": str(task.business_task_id),
            "solution_version_id": str(solution.solution_version_id),
            "generation_run_id": str(generation_run.generation_run_id),
            "publication_artifact_id": str(artifact.published_artifact_id),
            "verification_run_id": str(verification_run.verification_run_id),
            "protocol_id": protocol_id,
            "verification_state": getattr(verification_run.status, "value", verification_run.status),
            "summary_status": getattr(
                verification_run.protocol.summary_status,
                "value",
                verification_run.protocol.summary_status,
            )
            if verification_run.protocol is not None
            else None,
            "knowledge_version_id": str(active_version.knowledge_version_id),
        }

    def _consume_draft_task(
        self,
        payload: ExternalArchitectureCheckRequest,
        owner_key: str,
    ) -> BusinessTask | None:
        if not payload.draft_task_id:
            return None
        task = self.session.scalar(
            select(BusinessTask).where(BusinessTask.business_task_id == payload.draft_task_id)
        )
        if task is None:
            raise NotFoundError("BusinessTask", payload.draft_task_id)
        if str(task.created_by_user_id) != owner_key:
            raise AuthorizationError("Access denied to the requested architecture draft")
        metadata = dict(task.task_metadata or {})
        if metadata.get("source") != "external_architecture" or metadata.get("verification_only") is not True:
            raise ConflictError(
                "Business task is not an external architecture draft",
                error_code="EXTERNAL_ARCHITECTURE_DRAFT_SCOPE_ERROR",
            )
        if task.status != BusinessTaskStatus.DRAFT or task.generation_runs:
            raise ConflictError(
                "External architecture draft cannot be checked in its current state",
                error_code="EXTERNAL_ARCHITECTURE_DRAFT_NOT_EDITABLE",
            )
        return task

    def _effective_knowledge_scope(self, principal: AuthPrincipal):
        scope_service = KnowledgeBaseService(self.session)
        try:
            return scope_service.get_effective_scope(principal)
        except TypeError:
            return scope_service.get_effective_scope()

    def _materialize_sections(
        self, payload: ExternalArchitectureCheckRequest
    ) -> list[_SectionInput]:
        explicit_sections = [
            _SectionInput(
                section_code=str(normalize_togaf_section_code(item.section_code)),
                title=item.title or render_togaf_heading(str(normalize_togaf_section_code(item.section_code))),
                body_markdown=item.body_markdown,
            )
            for item in payload.sections
            if str(normalize_togaf_section_code(item.section_code)) in REQUIRED_TOGAF_SECTION_CODES
        ]
        if explicit_sections:
            return self._dedupe_and_order_sections(explicit_sections)
        parsed_sections = self._parse_markdown_sections(payload.architecture_text)
        if parsed_sections:
            return parsed_sections
        return [
            _SectionInput(
                section_code="it_architecture_content",
                title=render_togaf_heading("it_architecture_content"),
                body_markdown=payload.architecture_text,
            )
        ]

    def _parse_markdown_sections(self, text: str) -> list[_SectionInput]:
        current_code: str | None = None
        current_title: str | None = None
        current_body: list[str] = []
        parsed: list[_SectionInput] = []
        preamble: list[str] = []

        def flush() -> None:
            nonlocal current_code, current_title, current_body
            if current_code is None:
                return
            body = "\n".join(current_body).strip()
            if body:
                parsed.append(
                    _SectionInput(
                        section_code=current_code,
                        title=current_title or render_togaf_heading(current_code),
                        body_markdown=body,
                    )
                )
            current_code = None
            current_title = None
            current_body = []

        for raw_line in text.splitlines():
            line = raw_line.strip()
            heading = self._normalize_heading(line)
            if heading in REQUIRED_TOGAF_SECTION_CODES:
                if current_code is None and preamble:
                    parsed.append(
                        _SectionInput(
                            section_code="general_information",
                            title=render_togaf_heading("general_information"),
                            body_markdown="\n".join(preamble).strip(),
                        )
                    )
                    preamble = []
                flush()
                current_code = heading
                current_title = render_togaf_heading(heading)
                continue
            if current_code is None:
                preamble.append(raw_line)
            else:
                current_body.append(raw_line)
        flush()
        return self._dedupe_and_order_sections(parsed)

    @staticmethod
    def _normalize_heading(line: str) -> str | None:
        if not line:
            return None
        match = _HEADING_RE.match(line)
        if match is None:
            return None
        title = match.group("title").strip("#* ")
        ordered = _ORDERED_HEADING_RE.match(title)
        if ordered is not None:
            title = ordered.group("title")
        normalized = normalize_togaf_section_code(title)
        if isinstance(normalized, str) and normalized in REQUIRED_TOGAF_SECTION_CODES:
            return normalized
        return None

    @staticmethod
    def _dedupe_and_order_sections(sections: list[_SectionInput]) -> list[_SectionInput]:
        by_code: dict[str, _SectionInput] = {}
        for section in sections:
            if section.section_code in by_code:
                existing = by_code[section.section_code]
                by_code[section.section_code] = _SectionInput(
                    section_code=section.section_code,
                    title=existing.title,
                    body_markdown=f"{existing.body_markdown}\n\n{section.body_markdown}".strip(),
                )
            else:
                by_code[section.section_code] = section
        return sorted(
            by_code.values(),
            key=lambda item: TOGAF_SECTION_ORDER.get(item.section_code, 10_000),
        )

    def _materialize_components(
        self, payload: ExternalArchitectureCheckRequest, sections: list[_SectionInput]
    ) -> list[_ComponentInput]:
        components = [
            _ComponentInput(
                component_name=item.component_name,
                role_description=item.role_description,
                technology_stack=item.technology_stack,
                boundary_type=normalize_architecture_boundary_type(item.boundary_type)
                or item.boundary_type,
                external_flag=item.external_flag,
            )
            for item in payload.components
        ]
        if components:
            return components
        return self._infer_components_from_sections(sections)

    def _infer_components_from_sections(self, sections: list[_SectionInput]) -> list[_ComponentInput]:
        components: list[_ComponentInput] = []
        target_codes = {"application_architecture", "technology_architecture"}
        for section in sections:
            if section.section_code not in target_codes:
                continue
            for line in section.body_markdown.splitlines():
                match = _COMPONENT_BULLET_RE.match(line)
                if match is None:
                    continue
                name = " ".join(match.group("name").split())
                if len(name) < 3 or len(name.split()) > 8:
                    continue
                body = " ".join((match.group("body") or "").split())
                components.append(
                    _ComponentInput(
                        component_name=name[:200],
                        role_description=body
                        or f"Imported architecture component: {name}.",
                        technology_stack=None,
                        boundary_type=section.section_code,
                        external_flag=False,
                    )
                )
                if len(components) >= 20:
                    return self._dedupe_components(components)
        return self._dedupe_components(components)

    @staticmethod
    def _dedupe_components(components: list[_ComponentInput]) -> list[_ComponentInput]:
        by_name: dict[str, _ComponentInput] = {}
        for component in components:
            key = component.component_name.casefold()
            by_name.setdefault(key, component)
        return list(by_name.values())

    def _materialize_integrations(
        self, payload: ExternalArchitectureCheckRequest, components: list[_ComponentInput]
    ) -> list[_IntegrationInput]:
        known_names = {component.component_name.casefold() for component in components}
        integrations: list[_IntegrationInput] = []
        for item in payload.integrations:
            if item.from_component.casefold() not in known_names or item.to_component.casefold() not in known_names:
                continue
            integrations.append(
                _IntegrationInput(
                    from_component=item.from_component,
                    to_component=item.to_component,
                    interaction=item.interaction,
                    protocol=item.protocol,
                    rationale=item.rationale,
                )
            )
        return integrations

    def _persist_sections(
        self, solution: SolutionVersion, sections: list[_SectionInput], architecture_text: str
    ) -> None:
        for index, section in enumerate(sections, start=1):
            section_row = SolutionSection(
                solution_version_id=solution.solution_version_id,
                section_code=section.section_code,
                title=section.title,
                body_markdown=section.body_markdown,
                sort_order=index,
            )
            self.session.add(section_row)
            readiness = assess_section_readiness(
                section.section_code,
                task_text=architecture_text,
                section_body=section.body_markdown,
            )
            self.session.add(
                SolutionSectionAssessment(
                    solution_version_id=solution.solution_version_id,
                    section_code=section.section_code,
                    heading=readiness.get("heading"),
                    status=str(readiness.get("status") or "unknown"),
                    score=float(readiness.get("score") or 0.0),
                    observed_signal_groups=list(readiness.get("observed_signal_groups") or []),
                    missing_signal_groups=list(readiness.get("missing_signal_groups") or []),
                    reasons=list(readiness.get("reasons") or []),
                    allowed_archimate_elements=list(readiness.get("allowed_archimate_elements") or []),
                    fallback_applied=False,
                    details={
                        "source": "external_architecture",
                        "minimum_signal_count": readiness.get("minimum_signal_count"),
                        "observed_signal_count": readiness.get("observed_signal_count"),
                    },
                    sort_order=index,
                )
            )

    def _persist_components(
        self, solution: SolutionVersion, components: list[_ComponentInput]
    ) -> dict[str, SolutionComponent]:
        component_map: dict[str, SolutionComponent] = {}
        for index, component in enumerate(components, start=1):
            row = SolutionComponent(
                solution_version_id=solution.solution_version_id,
                component_name=component.component_name,
                role_description=component.role_description,
                technology_stack=component.technology_stack,
                boundary_type=component.boundary_type,
                external_flag=component.external_flag,
                sort_order=index,
            )
            self.session.add(row)
            self.session.flush()
            component_map[component.component_name.casefold()] = row
        return component_map

    def _persist_integrations(
        self,
        solution: SolutionVersion,
        integrations: list[_IntegrationInput],
        component_map: dict[str, SolutionComponent],
    ) -> None:
        for index, integration in enumerate(integrations, start=1):
            from_component = component_map.get(integration.from_component.casefold())
            to_component = component_map.get(integration.to_component.casefold())
            if from_component is None or to_component is None:
                continue
            self.session.add(
                SolutionIntegration(
                    solution_version_id=solution.solution_version_id,
                    from_component_id=from_component.component_id,
                    to_component_id=to_component.component_id,
                    interaction=integration.interaction,
                    protocol=integration.protocol,
                    rationale=integration.rationale,
                    sort_order=index,
                )
            )

    def _persist_risks_and_lists(
        self, solution: SolutionVersion, payload: ExternalArchitectureCheckRequest
    ) -> None:
        for index, item_text in enumerate(payload.assumptions, start=1):
            self.session.add(
                SolutionListItem(
                    solution_version_id=solution.solution_version_id,
                    item_group=SolutionListItemGroup.ASSUMPTION,
                    item_text=item_text,
                    sort_order=index,
                )
            )
        for index, item_text in enumerate(payload.next_steps, start=1):
            self.session.add(
                SolutionListItem(
                    solution_version_id=solution.solution_version_id,
                    item_group=SolutionListItemGroup.NEXT_STEP,
                    item_text=item_text,
                    sort_order=index,
                )
            )
        for index, risk in enumerate(payload.risks, start=1):
            self.session.add(
                SolutionRisk(
                    solution_version_id=solution.solution_version_id,
                    title=risk.title,
                    severity=risk.severity,
                    description=risk.description,
                    mitigation=risk.mitigation,
                    sort_order=index,
                )
            )

    def _persist_architecture_entities(
        self,
        solution: SolutionVersion,
        components: list[_ComponentInput],
        sections: list[_SectionInput],
    ) -> None:
        sort_order = 1
        for component in components:
            boundary = normalize_architecture_boundary_type(component.boundary_type)
            element_code = default_archimate_element_for_boundary(
                boundary, component.role_description
            )
            element = get_archimate_element(element_code) if element_code else None
            self.session.add(
                SolutionArchitectureEntity(
                    solution_version_id=solution.solution_version_id,
                    entity_key=f"external-component:{sort_order}",
                    display_name=component.component_name,
                    source_kind="external_component",
                    section_code=boundary,
                    archimate_layer=element.layer if element else None,
                    archimate_element_code=element_code,
                    archimate_element_title=element.title if element else None,
                    normalized_flag=bool(element_code),
                    confidence=0.55 if element_code else 0.25,
                    entity_metadata={
                        "source": "external_architecture",
                        "technology_stack": component.technology_stack,
                    },
                    sort_order=sort_order,
                )
            )
            sort_order += 1
        for section in sections:
            self.session.add(
                SolutionArchitectureEntity(
                    solution_version_id=solution.solution_version_id,
                    entity_key=f"external-section:{section.section_code}",
                    display_name=section.title,
                    source_kind="external_section",
                    section_code=section.section_code,
                    archimate_layer=None,
                    archimate_element_code=None,
                    archimate_element_title=None,
                    normalized_flag=False,
                    confidence=1.0,
                    entity_metadata={
                        "source": "external_architecture",
                        "body_length": len(section.body_markdown),
                    },
                    sort_order=sort_order,
                )
            )
            sort_order += 1

    @staticmethod
    def _executive_summary(text: str) -> str:
        collapsed = " ".join(text.split())
        return collapsed[:1200] if len(collapsed) > 1200 else collapsed

    @staticmethod
    def _render_imported_solution_html(
        *,
        solution: SolutionVersion,
        sections: list[_SectionInput],
        components: list[_ComponentInput],
        integrations: list[_IntegrationInput],
        source_ref: str | None,
    ) -> str:
        section_html = "".join(
            f"<h2>{escape(section.title)}</h2><pre>{escape(section.body_markdown)}</pre>"
            for section in sections
        )
        component_rows = "".join(
            "<tr>"
            f"<td>{escape(component.component_name)}</td>"
            f"<td>{escape(component.boundary_type or '')}</td>"
            f"<td>{escape(component.role_description)}</td>"
            "</tr>"
            for component in components
        )
        integration_rows = "".join(
            "<tr>"
            f"<td>{escape(integration.from_component)}</td>"
            f"<td>{escape(integration.to_component)}</td>"
            f"<td>{escape(integration.protocol or '')}</td>"
            f"<td>{escape(integration.interaction)}</td>"
            "</tr>"
            for integration in integrations
        )
        return (
            "<html><body>"
            f"<h1>{escape(solution.solution_title)}</h1>"
            "<p><strong>Source:</strong> external architecture import</p>"
            + (f"<p><strong>Reference:</strong> {escape(source_ref)}</p>" if source_ref else "")
            + f"<p>{escape(solution.executive_summary)}</p>"
            + (
                "<h2>Imported components</h2><table border='1' cellpadding='6' cellspacing='0'>"
                "<thead><tr><th>Name</th><th>Layer</th><th>Description</th></tr></thead>"
                f"<tbody>{component_rows}</tbody></table>"
                if component_rows
                else ""
            )
            + (
                "<h2>Imported integrations</h2><table border='1' cellpadding='6' cellspacing='0'>"
                "<thead><tr><th>From</th><th>To</th><th>Protocol</th><th>Interaction</th></tr></thead>"
                f"<tbody>{integration_rows}</tbody></table>"
                if integration_rows
                else ""
            )
            + section_html
            + "</body></html>"
        )
