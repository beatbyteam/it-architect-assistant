from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import (
    BusinessTaskStatus,
    ClarificationRequestStatus,
    GenerationRunStatus,
)
from app.db.models.generation import (
    BusinessTask,
    ClarificationAnswer,
    ClarificationRequest,
    GenerationRun,
    SolutionVersion,
)
from app.db.models.verification import VerificationRun
from app.domain.services.principal_keys import principal_owner_key
from app.domain.services.task_readiness import QUESTION_TEMPLATES
from app.schemas.generation import InternalGenerationRunStartRequest


def list_tasks(service, principal: AuthPrincipal) -> list[BusinessTask]:
    statement = (
        select(BusinessTask)
        .options(
            selectinload(BusinessTask.clarification_requests).selectinload(
                ClarificationRequest.answers
            ),
            selectinload(BusinessTask.generation_runs).selectinload(GenerationRun.solution_version),
            selectinload(BusinessTask.generation_runs)
            .selectinload(GenerationRun.solution_version)
            .selectinload(SolutionVersion.verification_runs)
            .selectinload(VerificationRun.protocol),
        )
        .order_by(BusinessTask.created_at.desc())
    )
    owner_key = principal_owner_key(principal)
    if not service._has_global_scope(principal) and owner_key is not None:
        statement = statement.where(BusinessTask.created_by_user_id == owner_key)
    return list(service.session.scalars(statement))


def get_task(service, task_id: str, principal: AuthPrincipal) -> BusinessTask:
    return service._get_task(task_id, principal)


def create_task(
    service,
    *,
    title: str | None,
    raw_text: str,
    metadata: dict[str, Any] | None,
    save_as_draft: bool,
    principal: AuthPrincipal,
    idempotency_key: str | None = None,
) -> BusinessTask:
    normalized_text = raw_text.strip()
    if not normalized_text:
        raise ValidationError(
            "Business task text is required",
            error_code="BUSINESS_TASK_TEXT_REQUIRED",
        )
    if not save_as_draft and len(normalized_text) < 20:
        raise ValidationError(
            "Business task text is too short for interpretation",
            error_code="BUSINESS_TASK_TEXT_TOO_SHORT",
        )
    owner_key = principal_owner_key(principal)
    request_payload = {
        "title": title,
        "raw_text": raw_text,
        "metadata": metadata or {},
        "save_as_draft": save_as_draft,
    }
    existing = service.idempotency.resolve_existing(
        actor_user_id=owner_key,
        operation_name="mvp.task.create",
        idempotency_key=idempotency_key,
        request_payload=request_payload,
    )
    if existing is not None:
        return service._get_task(existing.target_id, principal)
    task = BusinessTask(
        created_by_user_id=owner_key,
        title=title,
        task_text=raw_text,
        task_metadata=metadata or {},
        status=BusinessTaskStatus.DRAFT if save_as_draft else BusinessTaskStatus.SUBMITTED,
    )
    service.session.add(task)
    service.session.flush()
    if not save_as_draft:
        service._reassess_task(task, principal, reopen=True)
    service.idempotency.register(
        actor_user_id=owner_key,
        operation_name="mvp.task.create",
        idempotency_key=idempotency_key,
        request_payload=request_payload,
        target_type="business_task",
        target_id=str(task.business_task_id),
    )
    service.audit.record(
        event_type="generation.business_task.created",
        target_type="business_task",
        target_id=task.business_task_id,
        message="Business task created through canonical MVP intake",
        actor_user_id=owner_key,
        payload={
            "title": title,
            "initial_state": service._canonical_task_state(task),
            "save_as_draft": save_as_draft,
        },
    )
    service.session.commit()
    return service._get_task(str(task.business_task_id), principal)


def update_task(
    service,
    task_id: str,
    *,
    title: str | None,
    raw_text: str | None,
    metadata: dict[str, Any] | None,
    save_as_draft: bool | None,
    principal: AuthPrincipal,
) -> BusinessTask:
    task = service._get_task(task_id, principal)
    if task.generation_runs:
        raise ConflictError(
            "Business task cannot be edited after generation has started",
            error_code="BUSINESS_TASK_IMMUTABLE",
        )
    if title is not None:
        task.title = title
    if raw_text is not None:
        normalized_text = raw_text.strip()
        if not normalized_text:
            raise ValidationError(
                "Business task text is required", error_code="BUSINESS_TASK_TEXT_REQUIRED"
            )
        task.task_text = raw_text
    if metadata is not None:
        merged_metadata = dict(task.task_metadata or {})
        merged_metadata.update(metadata)
        task.task_metadata = merged_metadata
    should_submit = save_as_draft is False or (
        save_as_draft is None and task.status != BusinessTaskStatus.DRAFT
    )
    if save_as_draft is True:
        task.status = BusinessTaskStatus.DRAFT
        service._cancel_open_clarifications(task)
    elif should_submit:
        if len((task.task_text or "").strip()) < 20:
            raise ValidationError(
                "Business task text is too short for interpretation",
                error_code="BUSINESS_TASK_TEXT_TOO_SHORT",
            )
        task.status = BusinessTaskStatus.SUBMITTED
        service._reassess_task(task, principal, reopen=True)
    task.updated_at = datetime.now(UTC)
    service.session.add(task)
    service.audit.record(
        event_type="generation.business_task.updated",
        target_type="business_task",
        target_id=task.business_task_id,
        message="Business task updated",
        actor_user_id=principal_owner_key(principal),
        payload={"state": service._canonical_task_state(task), "save_as_draft": save_as_draft},
    )
    service.session.commit()
    return service._get_task(str(task.business_task_id), principal)


def answer_clarification(
    service,
    task_id: str,
    clarification_id: str,
    answers: list[dict[str, str]],
    principal: AuthPrincipal,
) -> BusinessTask:
    task = service._get_task(task_id, principal)
    clarification = next(
        (
            item
            for item in task.clarification_requests
            if str(item.clarification_id) == str(clarification_id)
        ),
        None,
    )
    if clarification is None:
        raise NotFoundError("ClarificationRequest", clarification_id)
    if clarification.state not in {
        ClarificationRequestStatus.OPEN,
        ClarificationRequestStatus.ANSWERED,
    }:
        raise ConflictError(
            "Clarification request is already closed", error_code="CLARIFICATION_ALREADY_CLOSED"
        )

    question_text_by_code = {
        str(item.get("question_code")): str(item.get("question_text"))
        for item in clarification.question_items
    }
    existing_answer_codes = {
        str(item.question_code)
        for item in clarification.answers
        if getattr(item, "question_code", None)
    }
    seen_codes: set[str] = set()
    for answer in answers:
        code = str(answer["question_code"]).strip()
        if code not in question_text_by_code:
            raise ValidationError(
                "Answer does not match current clarification request",
                error_code="CLARIFICATION_ANSWER_SCOPE_ERROR",
            )
        if code in seen_codes:
            raise ValidationError(
                "Duplicate answers for the same clarification question are not allowed",
                error_code="CLARIFICATION_ANSWER_DUPLICATE",
            )
        if code in existing_answer_codes:
            raise ValidationError(
                "Clarification question already has an answer",
                error_code="CLARIFICATION_ANSWER_ALREADY_EXISTS",
            )
        seen_codes.add(code)
    next_sort_order = max((item.sort_order for item in clarification.answers), default=0) + 1
    for index, answer in enumerate(answers, start=next_sort_order):
        service.session.add(
            ClarificationAnswer(
                clarification_id=clarification.clarification_id,
                question_code=answer["question_code"],
                question_text=question_text_by_code.get(answer["question_code"]),
                answer_text=answer["answer_text"],
                sort_order=index,
            )
        )

    metadata = dict(getattr(task, "task_metadata", None) or {})
    stored_answers = dict(metadata.get("clarification_answers") or {})
    for answer in answers:
        stored_answers[answer["question_code"]] = answer["answer_text"]
    metadata["clarification_answers"] = stored_answers
    task.task_metadata = metadata
    task.status = BusinessTaskStatus.CLARIFIED
    clarification.state = ClarificationRequestStatus.ANSWERED
    clarification.answered_at = datetime.now(UTC)
    service.session.add(task)
    service.session.add(clarification)
    service._reassess_task(task, principal, reopen=True)
    service.audit.record(
        event_type="generation.business_task.clarification.answered",
        target_type="business_task",
        target_id=task.business_task_id,
        message="Clarification answers submitted",
        actor_user_id=principal_owner_key(principal),
        payload={
            "clarification_id": clarification_id,
            "answer_count": len(answers),
            "state": service._canonical_task_state(task),
        },
    )
    service.session.commit()
    return service._get_task(task_id, principal)


def start_generation(
    service,
    task_id: str,
    *,
    correlation_id: str | None,
    principal: AuthPrincipal,
    idempotency_key: str | None = None,
    execute_inline: bool | None = None,
    generation_run_service_factory,
    read_service_factory,
) -> dict[str, Any]:
    task = service._get_task(task_id, principal)
    metadata = dict(getattr(task, "task_metadata", None) or {})
    if metadata.get("source") == "external_architecture" and metadata.get("verification_only") is True:
        raise ConflictError(
            "Черновик проверки архитектуры нельзя запускать как генерацию решения",
            error_code="VERIFICATION_ONLY_TASK_GENERATION_FORBIDDEN",
        )
    effective_correlation = correlation_id or idempotency_key
    owner_key = principal_owner_key(principal)
    request_payload = {"task_id": str(task.business_task_id)}
    existing = service.idempotency.resolve_existing(
        actor_user_id=owner_key,
        operation_name="mvp.task.start_generation",
        idempotency_key=idempotency_key,
        request_payload=request_payload,
    )
    read_service = read_service_factory(service.session, service.settings)
    if existing is not None:
        run_payload = read_service.get_generation_run_payload(existing.target_id, principal)
        return {
            "dispatch_type": "generation_run",
            "task_id": str(task.business_task_id),
            "task_state": service._canonical_task_state(task),
            "generation_run": run_payload,
        }

    readiness = service._assess_task_readiness(task)
    if (
        readiness["missing_inputs"]
        or service._latest_open_clarification(task) is not None
        or service._canonical_task_state(task) != BusinessTaskStatus.READY_FOR_GENERATION.value
    ):
        service._reassess_task(task, principal, reopen=True)
        service.session.commit()
        refreshed_task = service._get_task(task_id, principal)
        refreshed_readiness = service._assess_task_readiness(refreshed_task)
        open_request = service._latest_open_clarification(refreshed_task)
        if (
            refreshed_readiness["missing_inputs"]
            or open_request is not None
            or service._canonical_task_state(refreshed_task)
            != BusinessTaskStatus.READY_FOR_GENERATION.value
        ):
            clarification_payload = None
            if open_request is not None:
                task_snapshot = read_service.build_task_snapshot(refreshed_task)
                clarification_payload = next(
                    (
                        item
                        for item in task_snapshot["clarification_requests"]
                        if item["clarification_id"] == str(open_request.clarification_id)
                    ),
                    None,
                )
            return {
                "dispatch_type": "needs_clarification",
                "task_id": str(refreshed_task.business_task_id),
                "task_state": service._canonical_task_state(refreshed_task),
                "missing_inputs": refreshed_readiness["missing_inputs"],
                "clarification_request": clarification_payload,
            }
        task = refreshed_task
    run = generation_run_service_factory(service.session, service.settings).start_run(
        InternalGenerationRunStartRequest(
            business_task_id=str(task.business_task_id),
            correlation_id=effective_correlation,
            idempotency_key=idempotency_key,
            execute_inline=execute_inline,
        ),
        principal,
    )
    service.idempotency.register(
        actor_user_id=owner_key,
        operation_name="mvp.task.start_generation",
        idempotency_key=idempotency_key,
        request_payload=request_payload,
        target_type="generation_run",
        target_id=str(run.generation_run_id),
        correlation_id=effective_correlation,
    )
    service.session.commit()
    run_payload = read_service.get_generation_run_payload(str(run.generation_run_id), principal)
    return {
        "dispatch_type": "generation_run",
        "task_id": str(task.business_task_id),
        "task_state": service._canonical_task_state(task),
        "generation_run": run_payload,
    }


def _latest_open_clarification(service, task: BusinessTask) -> ClarificationRequest | None:
    open_items = [
        item
        for item in task.clarification_requests
        if item.state == ClarificationRequestStatus.OPEN
    ]
    open_items.sort(key=lambda item: item.created_at, reverse=True)
    return open_items[0] if open_items else None


def _cancel_open_clarifications(service, task: BusinessTask) -> None:
    now = datetime.now(UTC)
    for item in task.clarification_requests:
        if item.state in {ClarificationRequestStatus.OPEN, ClarificationRequestStatus.ANSWERED}:
            item.state = ClarificationRequestStatus.CANCELED
            item.closed_at = now
            service.session.add(item)


def _reassess_task(service, task: BusinessTask, principal: AuthPrincipal, *, reopen: bool) -> None:
    assessment = service.readiness_policy.assess(task).as_dict()
    missing = assessment["missing_inputs"]
    metadata = dict(task.task_metadata or {})
    metadata["clarification_assessment"] = assessment
    task.task_metadata = metadata
    now = datetime.now(UTC)
    if not missing:
        task.status = BusinessTaskStatus.READY_FOR_GENERATION
        for item in task.clarification_requests:
            if item.state in {ClarificationRequestStatus.OPEN, ClarificationRequestStatus.ANSWERED}:
                item.state = ClarificationRequestStatus.CLOSED
                item.closed_at = now
                service.session.add(item)
        task.updated_at = now
        service.session.add(task)
        return

    task.status = BusinessTaskStatus.NEEDS_CLARIFICATION
    task.updated_at = now
    service.session.add(task)
    if not reopen:
        return
    open_request = service._latest_open_clarification(task)
    question_items = assessment.get("question_items") or [
        {"question_code": code, "question_text": QUESTION_TEMPLATES[code], "required": True}
        for code in missing
    ]
    if open_request is not None:
        open_request.question_items = question_items
        service.session.add(open_request)
        return
    service.session.add(
        ClarificationRequest(
            business_task_id=task.business_task_id,
            state=ClarificationRequestStatus.OPEN,
            question_items=question_items,
        )
    )


def _detect_missing_inputs(service, task: BusinessTask) -> list[str]:
    return list(service.readiness_policy.assess(task).missing_inputs)


def _assess_task_readiness(service, task: BusinessTask) -> dict[str, Any]:
    return service.readiness_policy.assess(task).as_dict()


def _is_substantive_answer(service, value: str | None, *, code: str | None = None) -> bool:
    return service.readiness_policy.is_substantive_answer(value, code=code)


def _canonical_task_state(task: BusinessTask) -> str:
    status = getattr(task.status, "value", task.status)
    if status != BusinessTaskStatus.READY_FOR_GENERATION.value:
        return status
    generation_runs = list(getattr(task, "generation_runs", None) or [])
    if not generation_runs:
        return status
    latest_run = max(
        generation_runs,
        key=lambda run: getattr(run, "started_at", None)
        or datetime.min.replace(tzinfo=UTC),
    )
    raw_run_status = getattr(latest_run, "status", None)
    run_status = getattr(raw_run_status, "value", raw_run_status)
    if (
        run_status == GenerationRunStatus.COMPLETED.value
        and getattr(latest_run, "solution_version", None) is not None
    ):
        return BusinessTaskStatus.COMPLETED.value
    return status
