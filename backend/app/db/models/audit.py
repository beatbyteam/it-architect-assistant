from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import AuditSeverity
from app.db.models.common import enum_column, uuid_primary_key


class AuditEvent(Base):
    __tablename__ = "audit_events"

    audit_event_id: Mapped[UUID] = uuid_primary_key("audit_event_id")
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(String(100))
    target_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    severity: Mapped[AuditSeverity] = enum_column(AuditSeverity)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    correlation_id: Mapped[str | None] = mapped_column(String(100))
