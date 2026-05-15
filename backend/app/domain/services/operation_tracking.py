from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models.operations import OperationStep
from app.db.repositories.operations import OperationStepRepository

TERMINAL_STEP_STATUSES = {
    "completed",
    "warning",
    "failed",
    "canceled",
    "incomplete",
    "not_determined",
    "superseded",
}


class OperationTrackingService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.steps = OperationStepRepository(session)

    def make_json_safe(self, value: Any) -> Any:
        if value is None or isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime | date):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if hasattr(value, "model_dump"):
            return self.make_json_safe(value.model_dump())
        if isinstance(value, Mapping):
            return {str(key): self.make_json_safe(item) for key, item in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            return [self.make_json_safe(item) for item in value]
        return str(value)

    def record_step(
        self,
        *,
        operation_kind: str,
        operation_id: str,
        step_code: str,
        title: str,
        status: str,
        correlation_id: str | None = None,
        actor_user_id: str | None = None,
        detail: str | None = None,
        error_code: str | None = None,
        payload: dict[str, Any] | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> OperationStep:
        entity = self.steps.get_by_scope(
            operation_kind=operation_kind, operation_id=str(operation_id), step_code=step_code
        )
        now = datetime.now(UTC)
        if entity is None:
            entity = OperationStep(
                operation_kind=operation_kind,
                operation_id=str(operation_id),
                step_code=step_code,
                title=title,
                status=status,
                correlation_id=correlation_id,
                actor_user_id=actor_user_id,
                detail=detail,
                error_code=error_code,
                payload=self.make_json_safe(payload) if payload is not None else None,
                started_at=started_at or now,
                finished_at=finished_at,
            )
            if entity.finished_at is None and status in TERMINAL_STEP_STATUSES:
                entity.finished_at = now
            self.steps.add(entity)
            self.session.flush()
            return entity

        entity.title = title
        entity.status = status
        entity.correlation_id = correlation_id or entity.correlation_id
        entity.actor_user_id = actor_user_id or entity.actor_user_id
        if detail is not None:
            entity.detail = detail
        if error_code is not None:
            entity.error_code = error_code
        if payload is not None:
            entity.payload = self.make_json_safe(payload)
        if entity.started_at is None:
            entity.started_at = started_at or now
        if finished_at is not None:
            entity.finished_at = finished_at
        elif status in TERMINAL_STEP_STATUSES:
            entity.finished_at = entity.finished_at or now
        else:
            entity.finished_at = None
        self.steps.add(entity)
        self.session.flush()
        return entity

    def list_steps(self, *, operation_kind: str, operation_id: str) -> list[OperationStep]:
        return self.steps.list_for_operation(
            operation_kind=operation_kind, operation_id=str(operation_id)
        )

    @staticmethod
    def build_operation_ref(
        *,
        operation_kind: str,
        operation_id: str,
        correlation_id: str | None,
        knowledge_version_id: str | None = None,
        entity_refs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "operation_kind": operation_kind,
            "operation_id": str(operation_id),
            "state": None,
            "progress": None,
            "correlation_id": correlation_id,
            "knowledge_version_id": knowledge_version_id,
            "entity_refs": entity_refs or {},
        }
