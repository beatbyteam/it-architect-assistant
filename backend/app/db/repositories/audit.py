from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.db.models.audit import AuditEvent
from app.db.repositories.base import Repository


def _coerce_uuid(value: str | UUID | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


class AuditEventRepository(Repository[AuditEvent]):
    model = AuditEvent

    def get(self, primary_key: str | UUID) -> AuditEvent | None:
        audit_event_id = _coerce_uuid(primary_key)
        if audit_event_id is None:
            return None
        return super().get(audit_event_id)

    def list_filtered(
        self,
        *,
        target_type: str | None = None,
        target_id: str | UUID | None = None,
        correlation_id: str | None = None,
        severity: str | None = None,
        actor_user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEvent]:
        statement = select(AuditEvent).order_by(AuditEvent.event_time.desc())

        if target_type is not None:
            statement = statement.where(AuditEvent.target_type == target_type)

        if target_id is not None:
            target_uuid = _coerce_uuid(target_id)
            if target_uuid is None:
                return []
            statement = statement.where(AuditEvent.target_id == target_uuid)

        if correlation_id is not None:
            statement = statement.where(AuditEvent.correlation_id == correlation_id)

        if severity is not None:
            statement = statement.where(AuditEvent.severity == severity)

        if actor_user_id is not None:
            statement = statement.where(AuditEvent.actor_user_id == actor_user_id)

        return list(self.session.scalars(statement.offset(offset).limit(limit)).all())
