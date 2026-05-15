from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ValidationError
from app.db.models.idempotency import IdempotencyRecord
from app.db.repositories.idempotency import IdempotencyRecordRepository


class IdempotencyService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.records = IdempotencyRecordRepository(session)

    @staticmethod
    def _normalize_actor_user_id(actor_user_id: str | None) -> str:
        if not actor_user_id:
            raise ValidationError(
                "Authenticated actor is required for idempotent operations",
                error_code="IDEMPOTENCY_ACTOR_REQUIRED",
            )
        return str(actor_user_id)

    @staticmethod
    def _fingerprint(request_payload: dict[str, Any]) -> str:
        serialized = json.dumps(
            request_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def resolve_existing(
        self,
        *,
        actor_user_id: str | None,
        operation_name: str,
        idempotency_key: str | None,
        request_payload: dict[str, Any],
    ) -> IdempotencyRecord | None:
        if not idempotency_key:
            return None
        actor_scope = self._normalize_actor_user_id(actor_user_id)
        record = self.records.get_by_scope(
            actor_user_id=actor_scope,
            operation_name=operation_name,
            idempotency_key=idempotency_key,
        )
        if record is None:
            return None
        fingerprint = self._fingerprint(request_payload)
        if record.request_fingerprint != fingerprint:
            raise ConflictError(
                "Idempotency key was already used with different request parameters",
                error_code="IDEMPOTENCY_KEY_CONFLICT",
            )
        record.last_seen_at = datetime.now(UTC)
        self.session.add(record)
        self.session.flush()
        return record

    def register(
        self,
        *,
        actor_user_id: str | None,
        operation_name: str,
        idempotency_key: str | None,
        request_payload: dict[str, Any],
        target_type: str,
        target_id: str,
        correlation_id: str | None = None,
    ) -> IdempotencyRecord | None:
        if not idempotency_key:
            return None
        actor_scope = self._normalize_actor_user_id(actor_user_id)
        existing = self.resolve_existing(
            actor_user_id=actor_scope,
            operation_name=operation_name,
            idempotency_key=idempotency_key,
            request_payload=request_payload,
        )
        if existing is not None:
            return existing
        record = IdempotencyRecord(
            actor_user_id=actor_scope,
            operation_name=operation_name,
            idempotency_key=idempotency_key,
            request_fingerprint=self._fingerprint(request_payload),
            target_type=target_type,
            target_id=str(target_id),
            correlation_id=correlation_id,
        )
        begin_nested = getattr(self.session, "begin_nested", None)
        if callable(begin_nested):
            try:
                with begin_nested():
                    self.session.add(record)
                    self.session.flush()
            except IntegrityError:
                existing = self.resolve_existing(
                    actor_user_id=actor_scope,
                    operation_name=operation_name,
                    idempotency_key=idempotency_key,
                    request_payload=request_payload,
                )
                if existing is None:
                    raise
                return existing
            return record
        self.session.add(record)
        self.session.flush()
        return record
