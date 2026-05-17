from __future__ import annotations

from .knowledge_routes_common import (
    APIRouter,
    AuthPrincipal,
    KnowledgeNotificationResponse,
    KnowledgeUpdateRunResponse,
    KnowledgeUpdateRunStartRequest,
    KnowledgeUpdateRunStatusResponse,
    KnowledgeUpdateService,
    KnowledgeUpdateStatus,
    PrincipalDep,
    Query,
    ScheduledKnowledgeSyncResponse,
    SessionDep,
    SettingsDep,
    UserDep,
    WriteGuardDep,
    principal_requested_by,
    status,
)

router = APIRouter()


@router.get("/notifications", response_model=list[KnowledgeNotificationResponse])
def list_knowledge_notifications(
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    knowledge_base_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    _guard: AuthPrincipal = UserDep,
):
    payload = KnowledgeUpdateService(session, settings).list_notifications(
        limit=limit,
        knowledge_base_id=knowledge_base_id,
        principal=principal,
    )
    return [KnowledgeNotificationResponse.model_validate(item) for item in payload]


@router.get("/update-runs", response_model=list[KnowledgeUpdateRunResponse])
def list_knowledge_update_runs(
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    limit: int = Query(default=20, ge=1, le=100),
    knowledge_base_id: str | None = Query(default=None),
    status_filter: KnowledgeUpdateStatus | None = Query(default=None, alias="status"),
    _guard: AuthPrincipal = UserDep,
):
    service = KnowledgeUpdateService(session, settings)
    payload = service.list_run_responses(
        limit=limit,
        status=status_filter,
        knowledge_base_id=knowledge_base_id,
        principal=principal,
    )
    return [KnowledgeUpdateRunResponse.model_validate(item) for item in payload]


@router.post(
    "/update-runs",
    response_model=KnowledgeUpdateRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_knowledge_update(
    payload: KnowledgeUpdateRunStartRequest,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    payload = payload.model_copy(update={"requested_by": principal_requested_by(principal)})
    run_payload = KnowledgeUpdateService(session, settings).build_public_start_payload(
        payload,
        principal,
    )
    return KnowledgeUpdateService(session, settings).start_run(run_payload, principal)


@router.get("/update-runs/{update_run_id}", response_model=KnowledgeUpdateRunResponse)
def get_knowledge_update(
    update_run_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    return KnowledgeUpdateService(session, settings).get_run_response(update_run_id, principal)


@router.post("/update-runs/{update_run_id}/cancel", response_model=KnowledgeUpdateRunResponse)
def cancel_knowledge_update(
    update_run_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
    _write_guard: AuthPrincipal = WriteGuardDep,
):
    return KnowledgeUpdateService(session, settings).cancel_run(update_run_id, principal)


@router.get("/update-runs/{update_run_id}/status", response_model=KnowledgeUpdateRunStatusResponse)
def get_knowledge_update_status(
    update_run_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    return KnowledgeUpdateService(session, settings).get_run_status_payload(
        update_run_id,
        principal,
    )


@router.post("/update-runs/scheduled/execute", response_model=ScheduledKnowledgeSyncResponse)
def execute_scheduled_syncs(
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    _guard: AuthPrincipal = UserDep,
):
    payload = KnowledgeUpdateService(session, settings).run_due_scheduled_syncs(
        execute_inline=False,
        principal=principal,
    )
    return ScheduledKnowledgeSyncResponse.model_validate(payload)
