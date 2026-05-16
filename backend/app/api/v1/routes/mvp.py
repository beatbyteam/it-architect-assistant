from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import PrincipalDep, SessionDep, SettingsDep, WriteGuardDep, require_roles
from app.core.exceptions import ValidationError
from app.core.security import AuthPrincipal
from app.db.enums import MVP_USER_ROLE_CODES
from app.domain.services.external_architecture_check import ExternalArchitectureCheckService
from app.domain.services.mvp_canonical import CanonicalReadService, CanonicalTaskService
from app.schemas.mvp import (
    ClarificationAnswerRequest,
    ExternalArchitectureCheckRequest,
    ExternalArchitectureCheckResponse,
    GenerationClarificationRequiredResponse,
    GenerationRunAcceptedResponse,
    GenerationRunResponse,
    KnowledgeVersionResponse,
    SolutionArchitectureModelEnvelope,
    SolutionRegistryItemResponse,
    SolutionRenderedResponse,
    SolutionResponse,
    SolutionSectionAssessmentsEnvelope,
    TaskCreateRequest,
    TaskGenerationRunCreateRequest,
    TaskListItemResponse,
    TaskSnapshotResponse,
    TaskUpdateRequest,
    VerificationProtocolRegistryItemResponse,
    VerificationProtocolRenderedResponse,
    VerificationProtocolResponse,
    VerificationProtocolViolationsEnvelope,
    VerificationRunCreateRequest,
    VerificationRunResponse,
)

router = APIRouter(tags=["mvp"])
UserDep = Depends(require_roles(*MVP_USER_ROLE_CODES))


@router.get("/tasks", response_model=list[TaskListItemResponse])
def list_tasks(
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    state: str | None = None,
    search: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    _guard: AuthPrincipal = UserDep,
):
    service = CanonicalTaskService(session, settings)
    read_service = CanonicalReadService(session, settings)
    tasks = service.list_tasks(principal)
    if state:
        tasks = [task for task in tasks if service._canonical_task_state(task) == state]
    if search:
        needle = search.lower()
        tasks = [
            task
            for task in tasks
            if needle
            in f"{task.business_task_id} {task.title or ''} {service._canonical_task_state(task)}".lower()
        ]
    return [
        TaskListItemResponse(**read_service.build_task_snapshot(task)) for task in tasks[:limit]
    ]


@router.post("/tasks", response_model=TaskSnapshotResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreateRequest,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
    _write_guard: AuthPrincipal = WriteGuardDep,
):
    service = CanonicalTaskService(session, settings)
    read_service = CanonicalReadService(session, settings)
    task = service.create_task(
        title=payload.title,
        raw_text=payload.raw_text,
        metadata=payload.metadata,
        save_as_draft=payload.save_as_draft,
        principal=principal,
        idempotency_key=payload.idempotency_key,
    )
    return TaskSnapshotResponse(**read_service.build_task_snapshot(task))


@router.patch("/tasks/{task_id}", response_model=TaskSnapshotResponse)
def update_task(
    task_id: str,
    payload: TaskUpdateRequest,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
    _write_guard: AuthPrincipal = WriteGuardDep,
):
    service = CanonicalTaskService(session, settings)
    read_service = CanonicalReadService(session, settings)
    task = service.update_task(
        task_id,
        title=payload.title,
        raw_text=payload.raw_text,
        metadata=payload.metadata,
        save_as_draft=payload.save_as_draft,
        principal=principal,
    )
    return TaskSnapshotResponse(**read_service.build_task_snapshot(task))


@router.get("/tasks/{task_id}", response_model=TaskSnapshotResponse)
def get_task(
    task_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    service = CanonicalTaskService(session, settings)
    read_service = CanonicalReadService(session, settings)
    task = service.get_task(task_id, principal)
    return TaskSnapshotResponse(**read_service.build_task_snapshot(task))


@router.get("/solutions", response_model=list[SolutionRegistryItemResponse])
def list_solutions(
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    task_id: str | None = None,
    state: str | None = None,
    knowledge_version_id: str | None = None,
    limit: int = 50,
    _guard: AuthPrincipal = UserDep,
):
    items = CanonicalReadService(session, settings).list_solutions(
        principal,
        task_id=task_id,
        state=state,
        knowledge_version_id=knowledge_version_id,
        limit=limit,
    )
    return [SolutionRegistryItemResponse(**item) for item in items]


@router.get(
    "/verification-protocols", response_model=list[VerificationProtocolRegistryItemResponse]
)
def list_verification_protocols(
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    solution_version_id: str | None = None,
    summary_status: str | None = None,
    knowledge_version_id: str | None = None,
    limit: int = 50,
    _guard: AuthPrincipal = UserDep,
):
    items = CanonicalReadService(session, settings).list_protocols(
        principal,
        solution_version_id=solution_version_id,
        summary_status=summary_status,
        knowledge_version_id=knowledge_version_id,
        limit=limit,
    )
    return [VerificationProtocolRegistryItemResponse(**item) for item in items]


@router.post(
    "/tasks/{task_id}/clarifications/{clarification_id}/answers",
    response_model=TaskSnapshotResponse,
)
def answer_clarification(
    task_id: str,
    clarification_id: str,
    payload: ClarificationAnswerRequest,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
    _write_guard: AuthPrincipal = WriteGuardDep,
):
    service = CanonicalTaskService(session, settings)
    read_service = CanonicalReadService(session, settings)
    task = service.answer_clarification(
        task_id,
        clarification_id,
        answers=[
            {"question_code": item.question_code, "answer_text": item.answer_text}
            for item in payload.answers
        ],
        principal=principal,
    )
    return TaskSnapshotResponse(**read_service.build_task_snapshot(task))


@router.post(
    "/tasks/{task_id}/generation-runs",
    response_model=GenerationRunAcceptedResponse | GenerationClarificationRequiredResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_generation_run(
    task_id: str,
    payload: TaskGenerationRunCreateRequest,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    response: Response,
    _guard: AuthPrincipal = UserDep,
    _write_guard: AuthPrincipal = WriteGuardDep,
):
    service = CanonicalTaskService(session, settings)
    result = service.start_generation(
        task_id,
        correlation_id=payload.correlation_id,
        principal=principal,
        idempotency_key=payload.idempotency_key,
        execute_inline=payload.execute_inline,
    )
    if result["dispatch_type"] == "needs_clarification":
        response.status_code = status.HTTP_200_OK
        return GenerationClarificationRequiredResponse(**result)
    return GenerationRunAcceptedResponse(**result)


@router.get("/generation-runs/{generation_run_id}", response_model=GenerationRunResponse)
def get_generation_run(
    generation_run_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    return GenerationRunResponse(
        **CanonicalReadService(session, settings).get_generation_run_payload(
            generation_run_id, principal
        )
    )


@router.get("/solutions/{solution_version_id}", response_model=SolutionResponse)
def get_solution(
    solution_version_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    return SolutionResponse(
        **CanonicalReadService(session, settings).get_solution_payload(
            solution_version_id, principal
        )
    )


@router.get(
    "/solutions/{solution_version_id}/model", response_model=SolutionArchitectureModelEnvelope
)
def get_solution_model(
    solution_version_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    return SolutionArchitectureModelEnvelope(
        **CanonicalReadService(session, settings).get_solution_model_payload(
            solution_version_id, principal
        )
    )


@router.get(
    "/solutions/{solution_version_id}/section-assessments",
    response_model=SolutionSectionAssessmentsEnvelope,
)
def get_solution_section_assessments(
    solution_version_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    return SolutionSectionAssessmentsEnvelope(
        **CanonicalReadService(session, settings).get_solution_section_assessments_payload(
            solution_version_id, principal
        )
    )


@router.get("/solutions/{solution_version_id}/rendered", response_model=SolutionRenderedResponse)
def get_solution_rendered(
    solution_version_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    return SolutionRenderedResponse(
        **CanonicalReadService(session, settings).get_solution_rendered_payload(
            solution_version_id, principal
        )
    )


@router.delete("/solutions/{solution_version_id}", include_in_schema=False)
def delete_solution_not_supported(solution_version_id: str, _guard: AuthPrincipal = UserDep):
    _ = solution_version_id
    raise ValidationError(
        "Физическое удаление опубликованных решений в MVP не поддерживается; создайте новую ревизию или отправьте решение в архив",
        error_code="SOLUTION_DELETE_UNSUPPORTED",
    )


@router.delete("/verification-protocols/{protocol_id}", include_in_schema=False)
def delete_verification_protocol_not_supported(protocol_id: str, _guard: AuthPrincipal = UserDep):
    _ = protocol_id
    raise ValidationError(
        "Физическое удаление протоколов проверки в MVP не поддерживается; ревизии сохраняются для прослеживаемости",
        error_code="VERIFICATION_PROTOCOL_DELETE_UNSUPPORTED",
    )


@router.post(
    "/solutions/{solution_version_id}/verification-runs",
    response_model=VerificationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_verification_run(
    solution_version_id: str,
    payload: VerificationRunCreateRequest,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
    _write_guard: AuthPrincipal = WriteGuardDep,
):
    run = CanonicalReadService(session, settings).start_verification(
        solution_version_id,
        correlation_id=payload.correlation_id,
        principal=principal,
        idempotency_key=payload.idempotency_key,
        knowledge_document_ids=payload.knowledge_document_ids,
    )
    return VerificationRunResponse(
        **CanonicalReadService(session, settings).get_verification_run_payload(
            str(run.verification_run_id), principal
        )
    )


@router.post(
    "/external-architectures/check",
    response_model=ExternalArchitectureCheckResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def check_external_architecture(
    payload: ExternalArchitectureCheckRequest,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
    _write_guard: AuthPrincipal = WriteGuardDep,
):
    return ExternalArchitectureCheckResponse(
        **ExternalArchitectureCheckService(session, settings).import_and_start_check(
            payload, principal
        )
    )


@router.get("/verification-runs/{verification_run_id}", response_model=VerificationRunResponse)
def get_verification_run(
    verification_run_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    return VerificationRunResponse(
        **CanonicalReadService(session, settings).get_verification_run_payload(
            verification_run_id, principal
        )
    )


@router.get("/verification-protocols/{protocol_id}", response_model=VerificationProtocolResponse)
def get_verification_protocol(
    protocol_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    return VerificationProtocolResponse(
        **CanonicalReadService(session, settings).get_verification_protocol_payload(
            protocol_id, principal
        )
    )


@router.get(
    "/verification-protocols/{protocol_id}/violations",
    response_model=VerificationProtocolViolationsEnvelope,
)
def get_verification_protocol_violations(
    protocol_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    return VerificationProtocolViolationsEnvelope(
        **CanonicalReadService(session, settings).get_verification_protocol_violations_payload(
            protocol_id, principal
        )
    )


@router.get(
    "/verification-protocols/{protocol_id}/rendered",
    response_model=VerificationProtocolRenderedResponse,
)
def get_verification_protocol_rendered(
    protocol_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    return VerificationProtocolRenderedResponse(
        **CanonicalReadService(session, settings).get_verification_protocol_rendered_payload(
            protocol_id, principal
        )
    )


@router.get("/knowledge/versions/active", response_model=KnowledgeVersionResponse)
def get_active_knowledge_version(
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    return KnowledgeVersionResponse(
        **CanonicalReadService(session, settings).get_active_knowledge_version_payload(principal)
    )
