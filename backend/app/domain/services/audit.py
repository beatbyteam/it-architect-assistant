from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import Enum
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.enums import AuditSeverity
from app.db.models.audit import AuditEvent
from app.db.repositories.audit import AuditEventRepository


class AuditService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.events = AuditEventRepository(session)

    def _make_json_safe(self, value):
        if value is None or isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime | date):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if hasattr(value, "model_dump"):
            return self._make_json_safe(value.model_dump())
        if isinstance(value, Mapping):
            return {str(key): self._make_json_safe(item) for key, item in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            return [self._make_json_safe(item) for item in value]
        return str(value)

    def record(
        self,
        *,
        event_type: str,
        target_type: str,
        target_id,
        message: str,
        severity: AuditSeverity = AuditSeverity.INFO,
        actor_user_id=None,
        payload: dict | None = None,
        correlation_id: str | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_type=event_type,
            actor_user_id=actor_user_id,
            target_type=target_type,
            target_id=target_id,
            severity=severity,
            message=message,
            payload=self._make_json_safe(payload) if payload is not None else None,
            correlation_id=correlation_id,
        )
        self.events.add(event)
        self.session.flush()
        return event
