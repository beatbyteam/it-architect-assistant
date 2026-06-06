from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.exceptions import NotFoundError
from app.core.security import AuthPrincipal
from app.db.enums import (
    BusinessTaskStatus,
    ClarificationRequestStatus,
)
from app.db.models.generation import (
    BusinessTask,
)
from app.domain.services.presenters import (
    build_next_action_hint,
)
from app.schemas.mvp import ClarificationQuestionItem


def build_task_snapshot(service, task: BusinessTask) -> dict[str, Any]:
    clarification_items = []
    for item in sorted(task.clarification_requests, key=lambda row: row.created_at):
        clarification_items.append(
            {
                "clarification_id": str(item.clarification_id),
                "task_id": str(task.business_task_id),
                "state": getattr(item.state, "value", item.state),
                "question_items": [
                    ClarificationQuestionItem(**payload) for payload in item.question_items
                ],
                "created_at": item.created_at,
                "answered_at": item.answered_at,
                "closed_at": item.closed_at,
                "answers": [
                    {
                        "clarification_answer_id": str(answer.clarification_answer_id),
                        "question_code": answer.question_code,
                        "question_text": answer.question_text,
                        "answer_text": answer.answer_text,
                        "sort_order": answer.sort_order,
                        "created_at": answer.created_at,
                    }
                    for answer in sorted(item.answers, key=lambda row: row.sort_order)
                ],
            }
        )
    generation_items = []
    for run in sorted(task.generation_runs, key=lambda row: row.started_at, reverse=True):
        generation_items.append(
            {
                "generation_run_id": str(run.generation_run_id),
                "state": service.map_generation_state(run.status),
                "knowledge_version_id": str(run.knowledge_version_id),
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "solution_version_id": str(run.solution_version.solution_version_id)
                if run.solution_version
                else None,
                "knowledge_scope": service._extract_knowledge_scope(
                    getattr(run, "input_snapshot", None),
                    fallback_version_id=str(run.knowledge_version_id),
                ),
            }
        )
    latest_generation = generation_items[0] if generation_items else None
    verification_items = []
    for run in task.generation_runs:
        solution = getattr(run, "solution_version", None)
        if solution is None:
            continue
        for verification_run in getattr(solution, "verification_runs", []) or []:
            verification_items.append(
                {
                    "state": service.map_verification_run_state(verification_run.status),
                    "started_at": verification_run.started_at,
                    "protocol_id": str(verification_run.protocol.verification_protocol_id)
                    if getattr(verification_run, "protocol", None)
                    else None,
                }
            )
    verification_items.sort(key=lambda row: row["started_at"], reverse=True)
    latest_verification = verification_items[0] if verification_items else None
    now = datetime.now(UTC)
    open_clarification_count = sum(
        1 for item in task.clarification_requests if item.state == ClarificationRequestStatus.OPEN
    )
    overdue_clarification_flag = any(
        item.state == ClarificationRequestStatus.OPEN
        and item.created_at
        and (now - item.created_at).total_seconds() >= 86400
        for item in task.clarification_requests
    )
    metadata = dict(task.task_metadata or {})
    readiness_assessment = service._safe_dict(
        metadata.get("clarification_assessment")
    ) or service.tasks._assess_task_readiness(task)
    task_state = service.tasks._canonical_task_state(task)
    return {
        "task_id": str(task.business_task_id),
        "title": task.title,
        "raw_text": task.task_text,
        "state": task_state,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "created_by": str(task.created_by_user_id),
        "metadata": task.task_metadata,
        "clarification_requests": clarification_items,
        "generation_runs": generation_items,
        "latest_knowledge_version_id": latest_generation["knowledge_version_id"]
        if latest_generation
        else None,
        "latest_generation_state": latest_generation["state"] if latest_generation else None,
        "latest_verification_state": latest_verification["state"]
        if latest_verification
        else None,
        "latest_protocol_id": latest_verification["protocol_id"] if latest_verification else None,
        "open_clarification_count": open_clarification_count,
        "overdue_clarification_flag": overdue_clarification_flag,
        "readiness_assessment": readiness_assessment,
        "next_action_hint": build_next_action_hint(
            task_state=task_state,
            readiness_assessment=readiness_assessment,
            open_clarification_count=open_clarification_count,
        ),
    }


def get_generation_run_payload(
    service, run_id: str, principal: AuthPrincipal, *, generation_run_service_factory
) -> dict[str, Any]:
    run = generation_run_service_factory(service.session, service.settings).get_run(
        run_id, principal
    )
    task = service.tasks._get_task(str(run.business_task_id), principal)
    clarification_request = None
    if service.tasks._canonical_task_state(task) == BusinessTaskStatus.NEEDS_CLARIFICATION.value:
        item = service.tasks._latest_open_clarification(task)
        if item is not None:
            clarification_request = service.build_task_snapshot(task)["clarification_requests"][-1]
    diagnostics = service._safe_dict(run.diagnostics)
    diagnostics.setdefault("operation_kind", "generation_run")
    diagnostics.setdefault("operation_id", str(run.generation_run_id))
    return {
        "generation_run_id": str(run.generation_run_id),
        "task_id": str(run.business_task_id),
        "knowledge_version_id": str(run.knowledge_version_id),
        "state": service.map_generation_state(run.status),
        "run_state": getattr(run.status, "value", run.status),
        "current_stage": run.current_stage,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "solution_version_id": str(run.solution_version.solution_version_id)
        if run.solution_version
        else None,
        "clarification_request": clarification_request,
        "knowledge_scope": service._extract_knowledge_scope(
            getattr(run, "input_snapshot", None), fallback_version_id=str(run.knowledge_version_id)
        ),
        "diagnostics": diagnostics,
    }


def get_active_knowledge_version_payload(
    service, principal: AuthPrincipal | None = None, *, knowledge_base_service_factory
) -> dict[str, Any]:
    knowledge_base_service = knowledge_base_service_factory(service.session)
    try:
        scope = knowledge_base_service.get_effective_scope(principal)
    except TypeError:
        scope = knowledge_base_service.get_effective_scope()
    version = scope.selected_generation_version()
    if version is None:
        raise NotFoundError("KnowledgeVersion", "active")
    return {
        "knowledge_version_id": str(version.knowledge_version_id),
        "version_code": version.version_no,
        "state": getattr(version.status, "value", version.status),
        "created_at": version.created_at,
        "activated_at": version.activated_at,
        "activated_by": str(version.activated_by_user_id) if version.activated_by_user_id else None,
        "summary": version.summary,
        "knowledge_scope": {
            "mandatory_version_id": str(scope.mandatory_version.knowledge_version_id)
            if scope.mandatory_version
            else None,
            "selected_user_version_id": str(scope.selected_user_version.knowledge_version_id)
            if scope.selected_user_version
            else None,
            "selected_user_base_id": str(scope.selected_user_base.knowledge_base_id),
        },
    }
