from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings
from app.domain.services.operation_tracking import OperationTrackingService


def append_stage_history(
    diagnostics: dict[str, Any] | None,
    stage: str,
    *,
    detail: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    payload = dict(diagnostics or {})
    history = list(payload.get("stage_history") or [])
    history.append(
        {
            "stage": stage,
            "status": status or stage,
            "timestamp": datetime.now(UTC).isoformat(),
            "detail": detail,
        }
    )
    payload["stage_history"] = history
    return payload


def build_stage_event(
    stage: str, *, detail: str | None = None, status: str | None = None
) -> dict[str, Any]:
    return {
        "stage": stage,
        "status": status or stage,
        "timestamp": datetime.now(UTC).isoformat(),
        "detail": detail,
    }


def record_operation_step(
    operations: OperationTrackingService,
    *,
    operation_kind: str,
    operation_id: str,
    step_code: str,
    title: str,
    status: str,
    correlation_id: str | None,
    actor_user_id: str | None,
    detail: str | None = None,
    error_code: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    operations.record_step(
        operation_kind=operation_kind,
        operation_id=operation_id,
        step_code=step_code,
        title=title,
        status=status,
        correlation_id=correlation_id,
        actor_user_id=actor_user_id,
        detail=detail,
        error_code=error_code,
        payload=payload,
    )


def should_execute_inline(settings: Settings, requested_inline: bool | None) -> bool:
    if not requested_inline:
        return False
    is_prod_like = getattr(settings, "is_prod_like_env", None)
    if callable(is_prod_like):
        return not bool(is_prod_like())
    normalized_env = str(getattr(settings, "app_env", "") or "").strip().lower()
    return normalized_env not in {"prod", "production", "release"}


def dispatch_run(
    *,
    settings: Settings,
    requested_inline: bool | None,
    inline_executor: Callable[[], Any],
    queue_dispatcher: Callable[[], Any],
    queue_failure_handler: Callable[[Exception], Any] | None = None,
) -> Any:
    if should_execute_inline(settings, requested_inline):
        return inline_executor()
    try:
        return queue_dispatcher()
    except Exception as exc:
        if queue_failure_handler is None:
            raise
        return queue_failure_handler(exc)
