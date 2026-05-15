from __future__ import annotations

from sqlalchemy import select

from app.db.models.idempotency import IdempotencyRecord
from app.db.repositories.base import Repository


class IdempotencyRecordRepository(Repository[IdempotencyRecord]):
    model = IdempotencyRecord

    def get_by_scope(
        self, *, actor_user_id: str, operation_name: str, idempotency_key: str
    ) -> IdempotencyRecord | None:
        statement = select(IdempotencyRecord).where(
            IdempotencyRecord.actor_user_id == actor_user_id,
            IdempotencyRecord.operation_name == operation_name,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
        return self.session.scalar(statement)
