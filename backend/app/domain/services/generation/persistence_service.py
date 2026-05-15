from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.db.enums import (
    GenerationRunStatus,
    SolutionListItemGroup,
    SolutionVersionStatus,
)
from app.db.models.generation import (
    BusinessTask,
    GenerationRun,
    SolutionArchitectureEntity,
    SolutionArchitectureRelation,
    SolutionComponent,
    SolutionComponentInterface,
    SolutionIntegration,
    SolutionListItem,
    SolutionRisk,
    SolutionSection,
    SolutionSectionAssessment,
    SolutionSectionSourceRef,
    SolutionVersion,
)
from app.db.repositories.generation import (
    SolutionVersionRepository,
)
from app.domain.architecture import derive_structured_architecture_model
from app.integrations.generation.contracts import (
    GenerationSolutionPayload,
    GenerationStructuredArchitectureModel,
)

logger = logging.getLogger(__name__)

TERMINAL_GENERATION_STATUSES = {
    GenerationRunStatus.COMPLETED,
    GenerationRunStatus.FAILED,
    GenerationRunStatus.CANCELED,
}


class SolutionPersistenceService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.solutions = SolutionVersionRepository(session)

    def persist(
        self, *, business_task: BusinessTask, run: GenerationRun, payload: GenerationSolutionPayload
    ) -> SolutionVersion:
        last_error: IntegrityError | None = None
        solution: SolutionVersion | None = None
        for _attempt in range(3):
            next_version_no = self.solutions.get_next_version_no(business_task.business_task_id)
            solution = SolutionVersion(
                business_task_id=business_task.business_task_id,
                generation_run_id=run.generation_run_id,
                version_no=next_version_no,
                solution_title=payload.solution_title,
                executive_summary=payload.executive_summary,
                status=SolutionVersionStatus.PUBLISHED,
            )
            self.session.add(solution)
            try:
                self.session.flush()
                break
            except IntegrityError as exc:
                last_error = exc
                self.session.rollback()
                expire_all = getattr(self.session, "expire_all", None)
                if callable(expire_all):
                    expire_all()
        else:
            raise ConflictError(
                "Concurrent solution version creation detected; please retry generation persistence",
                error_code="SOLUTION_VERSION_CONFLICT",
            ) from last_error
        if solution is None:
            raise ConflictError(
                "Concurrent solution version creation detected; please retry generation persistence",
                error_code="SOLUTION_VERSION_CONFLICT",
            ) from last_error

        section_map: dict[str, SolutionSection] = {}
        readiness_items = list(getattr(payload, "section_readiness", []) or [])
        for index, readiness_payload in enumerate(readiness_items, start=1):
            readiness_dict = (
                readiness_payload.model_dump()
                if hasattr(readiness_payload, "model_dump")
                else dict(readiness_payload)
            )
            self.session.add(
                SolutionSectionAssessment(
                    solution_version_id=solution.solution_version_id,
                    section_code=str(readiness_dict.get("section_code") or "unknown"),
                    heading=readiness_dict.get("heading"),
                    status=str(readiness_dict.get("status") or "unknown"),
                    score=float(readiness_dict.get("score") or 0.0),
                    observed_signal_groups=list(readiness_dict.get("observed_signal_groups") or []),
                    missing_signal_groups=list(readiness_dict.get("missing_signal_groups") or []),
                    reasons=list(readiness_dict.get("reasons") or []),
                    allowed_archimate_elements=list(
                        readiness_dict.get("allowed_archimate_elements") or []
                    ),
                    fallback_applied=bool(readiness_dict.get("fallback_applied")),
                    details={
                        "minimum_signal_count": readiness_dict.get("minimum_signal_count"),
                        "observed_signal_count": readiness_dict.get("observed_signal_count"),
                    },
                    sort_order=index,
                )
            )

        structured_model = getattr(payload, "structured_model", None)
        if structured_model is None or not list(getattr(structured_model, "entities", []) or []):
            structured_model = GenerationStructuredArchitectureModel.model_validate(
                derive_structured_architecture_model(payload)
            )
        if structured_model is not None:
            structured_model_dict = (
                structured_model.model_dump()
                if hasattr(structured_model, "model_dump")
                else dict(structured_model)
            )
            for index, entity in enumerate(
                list(structured_model_dict.get("entities") or []), start=1
            ):
                self.session.add(
                    SolutionArchitectureEntity(
                        solution_version_id=solution.solution_version_id,
                        entity_key=str(entity.get("entity_id") or f"entity:{index}"),
                        display_name=str(
                            entity.get("name") or entity.get("display_name") or f"Entity {index}"
                        ),
                        source_kind=entity.get("source_kind"),
                        section_code=entity.get("section_code"),
                        archimate_layer=entity.get("layer"),
                        archimate_element_code=entity.get("archimate_element_code"),
                        archimate_element_title=entity.get("archimate_element_title"),
                        normalized_flag=bool(entity.get("archimate_element_code")),
                        confidence=float(entity.get("confidence") or 0.0)
                        if entity.get("confidence") is not None
                        else None,
                        entity_metadata={
                            k: v
                            for k, v in entity.items()
                            if k
                            not in {
                                "entity_id",
                                "name",
                                "display_name",
                                "source_kind",
                                "section_code",
                                "layer",
                                "archimate_element_code",
                                "archimate_element_title",
                                "confidence",
                            }
                        },
                        sort_order=index,
                    )
                )
            for index, relation in enumerate(
                list(structured_model_dict.get("relations") or []), start=1
            ):
                self.session.add(
                    SolutionArchitectureRelation(
                        solution_version_id=solution.solution_version_id,
                        relation_key=str(relation.get("relation_id") or f"relation:{index}"),
                        relation_type=str(relation.get("relation_type") or "relation"),
                        source_entity_key=relation.get("source_entity_id"),
                        target_entity_key=relation.get("target_entity_id"),
                        section_code=relation.get("section_code"),
                        normalized_flag=bool(
                            relation.get("source_entity_id") and relation.get("target_entity_id")
                        ),
                        confidence=float(relation.get("confidence") or 0.0)
                        if relation.get("confidence") is not None
                        else None,
                        relation_metadata={
                            k: v
                            for k, v in relation.items()
                            if k
                            not in {
                                "relation_id",
                                "relation_type",
                                "source_entity_id",
                                "target_entity_id",
                                "section_code",
                                "confidence",
                            }
                        },
                        sort_order=index,
                    )
                )

        for index, section_payload in enumerate(payload.sections, start=1):
            section = SolutionSection(
                solution_version_id=solution.solution_version_id,
                section_code=section_payload.section_code,
                title=section_payload.title,
                body_markdown=section_payload.body_markdown,
                sort_order=index,
            )
            self.session.add(section)
            self.session.flush()
            section_map[section.section_code] = section
            for ref_index, source_ref in enumerate(section_payload.source_refs, start=1):
                self.session.add(
                    SolutionSectionSourceRef(
                        section_id=section.section_id,
                        fragment_id=source_ref.fragment_id,
                        document_id=source_ref.document_id,
                        quote_text=source_ref.quote_text,
                        sort_order=ref_index,
                    )
                )

        component_map: dict[str, SolutionComponent] = {}
        for index, component_payload in enumerate(payload.components, start=1):
            component = SolutionComponent(
                solution_version_id=solution.solution_version_id,
                component_name=component_payload.component_name,
                role_description=component_payload.role_description,
                technology_stack=component_payload.technology_stack,
                boundary_type=component_payload.boundary_type,
                external_flag=component_payload.external_flag,
                sort_order=index,
            )
            self.session.add(component)
            self.session.flush()
            component_map[component.component_name] = component
            for iface_index, iface_payload in enumerate(component_payload.interfaces, start=1):
                self.session.add(
                    SolutionComponentInterface(
                        component_id=component.component_id,
                        interface_name=iface_payload.interface_name,
                        protocol=iface_payload.protocol,
                        description=iface_payload.description,
                        sort_order=iface_index,
                    )
                )

        for index, integration_payload in enumerate(payload.integrations, start=1):
            self.session.add(
                SolutionIntegration(
                    solution_version_id=solution.solution_version_id,
                    from_component_id=component_map[
                        integration_payload.from_component
                    ].component_id,
                    to_component_id=component_map[integration_payload.to_component].component_id,
                    interaction=integration_payload.interaction,
                    protocol=integration_payload.protocol,
                    rationale=integration_payload.rationale,
                    sort_order=index,
                )
            )

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

        for index, risk_payload in enumerate(payload.risks, start=1):
            self.session.add(
                SolutionRisk(
                    solution_version_id=solution.solution_version_id,
                    title=risk_payload.title,
                    severity=risk_payload.severity,
                    description=risk_payload.description,
                    mitigation=risk_payload.mitigation,
                    sort_order=index,
                )
            )

        self.session.flush()
        self.session.refresh(solution)
        return solution
