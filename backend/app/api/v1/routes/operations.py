from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import SessionDep, SettingsDep, require_roles
from app.core.security import AuthPrincipal
from app.db.enums import ROLE_USER
from app.domain.services.operations import OperationsQueryService
from app.schemas.operations import (
    AuditEventResponse,
    OperationDetailResponse,
    OperationJournalItemResponse,
    OperationMetricsResponse,
)

router = APIRouter(tags=["operations"])
UserDep = Depends(require_roles(ROLE_USER))


@router.get("/operations", response_model=list[OperationJournalItemResponse])
def list_operations(
    session: SessionDep,
    settings: SettingsDep,
    operation_kind: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    correlation_id: str | None = Query(default=None),
    solution_version_id: str | None = Query(default=None),
    verification_protocol_id: str | None = Query(default=None),
    knowledge_version_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    principal: AuthPrincipal = UserDep,
):
    items = OperationsQueryService(session, settings).list_operations(
        operation_kind=operation_kind,
        status=status_filter,
        correlation_id=correlation_id,
        solution_version_id=solution_version_id,
        verification_protocol_id=verification_protocol_id,
        knowledge_version_id=knowledge_version_id,
        limit=limit,
        principal=principal,
    )
    return [OperationJournalItemResponse.model_validate(item) for item in items]


@router.get("/audit-events", response_model=list[AuditEventResponse])
def list_audit_events(
    session: SessionDep,
    settings: SettingsDep,
    target_type: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    correlation_id: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    principal: AuthPrincipal = UserDep,
):
    items = OperationsQueryService(session, settings).list_audit_events(
        target_type=target_type,
        target_id=target_id,
        correlation_id=correlation_id,
        severity=severity,
        limit=limit,
        principal=principal,
    )
    return [AuditEventResponse.model_validate(item, from_attributes=True) for item in items]


@router.get("/audit-events/{audit_event_id}", response_model=AuditEventResponse)
def get_audit_event(
    audit_event_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: AuthPrincipal = UserDep,
):
    item = OperationsQueryService(session, settings).get_audit_event(
        audit_event_id, principal=principal
    )
    return AuditEventResponse.model_validate(item, from_attributes=True)


@router.get("/operations/metrics", response_model=OperationMetricsResponse)
def get_operation_metrics(
    session: SessionDep, settings: SettingsDep, principal: AuthPrincipal = UserDep
):
    return OperationMetricsResponse.model_validate(
        OperationsQueryService(session, settings).get_metrics_snapshot(principal=principal)
    )


@router.get("/operations/{operation_id}", response_model=OperationDetailResponse)
def get_operation_detail(
    operation_id: str,
    session: SessionDep,
    settings: SettingsDep,
    principal: AuthPrincipal = UserDep,
):
    item = OperationsQueryService(session, settings).get_operation_detail(
        operation_id, principal=principal
    )
    return OperationDetailResponse.model_validate(item)
