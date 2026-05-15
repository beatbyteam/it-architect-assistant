from __future__ import annotations

from typing import Any

from app.core.security import AuthPrincipal
from app.domain.services.presenters import (
    retention_policy_payload,
)


def get_solution_model_payload(
    service, solution_version_id: str, principal: AuthPrincipal, *, solution_query_service_factory
) -> dict[str, Any]:
    solution = solution_query_service_factory(service.session).get_solution(
        solution_version_id, principal
    )
    return {
        "solution_version_id": str(solution.solution_version_id),
        "architecture_model": service._build_architecture_model_payload(solution),
    }


def get_solution_section_assessments_payload(
    service, solution_version_id: str, principal: AuthPrincipal, *, solution_query_service_factory
) -> dict[str, Any]:
    solution = solution_query_service_factory(service.session).get_solution(
        solution_version_id, principal
    )
    return {
        "solution_version_id": str(solution.solution_version_id),
        "section_assessments": service._build_section_assessments_payload(solution),
    }


def get_solution_rendered_payload(
    service, solution_version_id: str, principal: AuthPrincipal, *, solution_query_service_factory
) -> dict[str, Any]:
    solution = solution_query_service_factory(service.session).get_solution(
        solution_version_id, principal
    )
    rendered = solution_query_service_factory(service.session).get_solution_view(
        solution_version_id, principal
    )
    return {
        "solution_version_id": str(solution.solution_version_id),
        "state": service.map_solution_state(solution.status),
        "published_at": rendered["published_at"],
        "rendered_html": rendered["rendered_html"],
        "publication_artifact_id": rendered.get("publication_artifact_id"),
        "publication_revision_no": rendered.get("publication_revision_no"),
        "artifact_state": rendered.get("artifact_state"),
        "version_hash": rendered.get("version_hash"),
        "publication_history": service._list_publication_revisions(
            target_type="solution_version", target_id=str(solution.solution_version_id)
        ),
        "retention_policy": retention_policy_payload(target_type="solution_version"),
        "snapshot_summary": service._build_snapshot_summary(
            getattr(solution.generation_run, "input_snapshot", None)
        ),
        "explainability": service._build_solution_explainability(solution),
    }


def get_solution_payload(
    service, solution_version_id: str, principal: AuthPrincipal, *, solution_query_service_factory
) -> dict[str, Any]:
    solution = solution_query_service_factory(service.session).get_solution(
        solution_version_id, principal
    )
    verification_runs = sorted(
        solution.verification_runs, key=lambda row: row.started_at, reverse=True
    )
    current_publication = service.publication_artifacts.get_current(
        target_type="solution_version", target_id=str(solution.solution_version_id)
    )
    return {
        "solution_version_id": str(solution.solution_version_id),
        "generation_run_id": str(solution.generation_run_id),
        "task_id": str(solution.business_task_id),
        "state": service.map_solution_state(solution.status),
        "published_at": solution.published_at,
        "solution_title": solution.solution_title,
        "executive_summary": solution.executive_summary,
        "sections": [
            {
                "section_id": str(section.section_id),
                "section_code": section.section_code,
                "title": section.title,
                "body_markdown": section.body_markdown,
                "sort_order": section.sort_order,
                "source_refs": [
                    service._serialize_solution_source_ref(ref)
                    for ref in sorted(section.source_refs, key=lambda row: row.sort_order)
                ],
            }
            for section in sorted(solution.sections, key=lambda row: row.sort_order)
        ],
        "section_assessments": service._build_section_assessments_payload(solution),
        "architecture_model": service._build_architecture_model_payload(solution),
        "components": [
            {
                "component_id": str(component.component_id),
                "component_name": component.component_name,
                "role_description": component.role_description,
                "technology_stack": component.technology_stack,
                "boundary_type": component.boundary_type,
                "external_flag": component.external_flag,
                "sort_order": component.sort_order,
                "interfaces": [
                    {
                        "interface_id": str(interface.interface_id),
                        "interface_name": interface.interface_name,
                        "protocol": interface.protocol,
                        "description": interface.description,
                        "sort_order": interface.sort_order,
                    }
                    for interface in sorted(component.interfaces, key=lambda row: row.sort_order)
                ],
            }
            for component in sorted(solution.components, key=lambda row: row.sort_order)
        ],
        "integrations": [
            {
                "integration_id": str(item.integration_id),
                "interaction": item.interaction,
                "protocol": item.protocol,
                "rationale": item.rationale,
                "sort_order": item.sort_order,
            }
            for item in sorted(solution.integrations, key=lambda row: row.sort_order)
        ],
        "list_items": [
            {
                "solution_list_item_id": str(item.solution_list_item_id),
                "item_group": getattr(item.item_group, "value", item.item_group),
                "item_text": item.item_text,
                "sort_order": item.sort_order,
            }
            for item in sorted(solution.list_items, key=lambda row: row.sort_order)
        ],
        "risks": [
            {
                "risk_id": str(risk.risk_id),
                "title": risk.title,
                "severity": getattr(risk.severity, "value", risk.severity),
                "description": risk.description,
                "mitigation": risk.mitigation,
                "sort_order": risk.sort_order,
            }
            for risk in sorted(solution.risks, key=lambda row: row.sort_order)
        ],
        "knowledge_version_id": str(solution.generation_run.knowledge_version_id),
        "publication_artifact_id": str(current_publication.published_artifact_id)
        if current_publication
        else None,
        "publication_revision_no": current_publication.revision_no if current_publication else None,
        "artifact_state": current_publication.state if current_publication else None,
        "version_hash": current_publication.version_hash if current_publication else None,
        "publication_history": service._list_publication_revisions(
            target_type="solution_version", target_id=str(solution.solution_version_id)
        ),
        "retention_policy": retention_policy_payload(target_type="solution_version"),
        "snapshot_summary": service._build_snapshot_summary(
            getattr(solution.generation_run, "input_snapshot", None)
        ),
        "knowledge_scope": service._extract_knowledge_scope(
            getattr(solution.generation_run, "input_snapshot", None),
            fallback_version_id=str(solution.generation_run.knowledge_version_id),
        ),
        "verification_runs": [
            {
                "verification_run_id": str(run.verification_run_id),
                "state": service.map_verification_run_state(run.status),
                "knowledge_version_id": str(run.knowledge_version_id),
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "protocol_id": str(run.protocol.verification_protocol_id) if run.protocol else None,
            }
            for run in verification_runs
        ],
        "explainability": service._build_solution_explainability(solution),
    }
