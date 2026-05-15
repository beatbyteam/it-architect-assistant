from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.exceptions import AuthorizationError
from app.core.security import AuthPrincipal
from app.db.enums import (
    GenerationRunStatus,
    VerificationProtocolStatus,
    VerificationRunStatus,
)
from app.db.models.generation import (
    SolutionVersion,
)
from app.db.models.verification import (
    VerificationRun,
)


def map_generation_state(status: Any) -> str:
    value = getattr(status, "value", status)
    if value == GenerationRunStatus.CREATED.value:
        return GenerationRunStatus.QUEUED.value
    return value


def map_solution_state(status: Any) -> str:
    return getattr(status, "value", status)


def map_verification_run_state(status: Any) -> str:
    value = getattr(status, "value", status)
    if value == VerificationRunStatus.CREATED.value:
        return VerificationRunStatus.QUEUED.value
    return value


def map_protocol_state(status: Any, summary_status: Any) -> str:
    protocol_state = getattr(status, "value", status)
    summary_value = getattr(summary_status, "value", summary_status)
    if (
        protocol_state == VerificationProtocolStatus.PUBLISHED.value
        and summary_value == "incomplete"
    ):
        return VerificationProtocolStatus.INCOMPLETE.value
    return protocol_state


def list_solutions(
    service,
    principal: AuthPrincipal,
    *,
    verification_query_service_factory,
    task_id: str | None = None,
    state: str | None = None,
    knowledge_version_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    batch_size = max(limit, 50)
    offset = 0
    rows: list[dict[str, Any]] = []
    try:
        verification_query = verification_query_service_factory(
            service.session, getattr(service, "settings", None)
        )
    except TypeError:
        verification_query = verification_query_service_factory(service.session)
    while len(rows) < limit:
        statement = (
            select(SolutionVersion)
            .options(
                selectinload(SolutionVersion.business_task),
                selectinload(SolutionVersion.generation_run),
                selectinload(SolutionVersion.verification_runs).selectinload(
                    VerificationRun.protocol
                ),
            )
            .order_by(SolutionVersion.created_at.desc())
            .offset(offset)
            .limit(batch_size)
        )
        items = list(service.session.scalars(statement))
        if not items:
            break
        for solution in items:
            try:
                verification_query._ensure_solution_access(solution, principal)
            except AuthorizationError:
                continue
            if task_id is not None and str(solution.business_task_id) != task_id:
                continue
            mapped_state = service.map_solution_state(solution.status)
            if state is not None and mapped_state != state:
                continue
            version_id = (
                str(solution.generation_run.knowledge_version_id)
                if solution.generation_run
                else None
            )
            if knowledge_version_id is not None and version_id != knowledge_version_id:
                continue
            latest_run = (
                sorted(solution.verification_runs, key=lambda row: row.started_at, reverse=True)[0]
                if solution.verification_runs
                else None
            )
            rows.append(
                {
                    "solution_version_id": str(solution.solution_version_id),
                    "task_id": str(solution.business_task_id),
                    "generation_run_id": str(solution.generation_run_id),
                    "knowledge_version_id": version_id,
                    "state": mapped_state,
                    "solution_title": solution.solution_title,
                    "published_at": solution.published_at,
                    "created_at": solution.created_at,
                    "verification_run_count": len(solution.verification_runs),
                    "latest_verification_state": service.map_verification_run_state(
                        latest_run.status
                    )
                    if latest_run
                    else None,
                    "latest_protocol_id": str(latest_run.protocol.verification_protocol_id)
                    if latest_run and latest_run.protocol
                    else None,
                }
            )
            if len(rows) >= limit:
                break
        offset += len(items)
        if len(items) < batch_size:
            break
    return rows


def list_protocols(
    service,
    principal: AuthPrincipal,
    *,
    verification_query_service_factory,
    solution_version_id: str | None = None,
    summary_status: str | None = None,
    knowledge_version_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    try:
        verification_query = verification_query_service_factory(
            service.session, getattr(service, "settings", None)
        )
    except TypeError:
        verification_query = verification_query_service_factory(service.session)
    items = verification_query.list_protocols(
        principal=principal,
        summary_status=summary_status,
        solution_version_id=solution_version_id,
        knowledge_version_id=knowledge_version_id,
        limit=limit,
    )
    rows: list[dict[str, Any]] = []
    for item in items:
        protocol = verification_query.get_protocol(str(item["verification_protocol_id"]), principal)
        rows.append(
            {
                "protocol_id": str(protocol.verification_protocol_id),
                "verification_run_id": str(protocol.verification_run_id),
                "solution_version_id": str(protocol.verification_run.solution_version_id),
                "knowledge_version_id": str(protocol.verification_run.knowledge_version_id),
                "created_at": protocol.issued_at,
                "state": service.map_protocol_state(protocol.status, protocol.summary_status),
                "summary_status": getattr(
                    protocol.summary_status, "value", protocol.summary_status
                ),
                "summary_text": protocol.summary_text,
                "basis_document_count": len(protocol.basis_documents)
                if protocol.basis_documents
                else len(service._materialize_basis_documents(protocol)),
                "finding_count": len(protocol.check_results),
                "has_blockers": any(
                    getattr(row.status, "value", row.status) in {"failed", "not_determined"}
                    for row in protocol.check_results
                ),
            }
        )
    return rows
