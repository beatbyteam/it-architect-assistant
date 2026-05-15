from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import uuid_primary_key


class OperationStep(Base):
    __tablename__ = "operation_steps"
    __table_args__ = (
        UniqueConstraint(
            "operation_kind", "operation_id", "step_code", name="uq_operation_steps_scope"
        ),
        Index("ix_operation_steps_lookup", "operation_kind", "operation_id", "started_at"),
        Index("ix_operation_steps_correlation", "correlation_id"),
    )

    operation_step_id: Mapped[str] = uuid_primary_key("operation_step_id")
    operation_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    step_code: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(String(100))
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    detail: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(100))
    payload: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
