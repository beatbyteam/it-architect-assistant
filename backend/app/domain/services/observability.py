from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from app.domain.services.knowledge_telemetry import record_stage_metric


class StageObservation(dict):
    """Mutable payload filled by a stage body before metrics/logging finalize."""


def summarize_stage_metrics(stage_metrics: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    metrics = dict(stage_metrics or {})
    if not metrics:
        return {
            "stage_count": 0,
            "total_stage_duration_sec": 0.0,
            "average_stage_duration_sec": None,
            "longest_stage": None,
            "failed_stage_count": 0,
            "warning_stage_count": 0,
        }
    totals = {
        stage: float((payload or {}).get("total_duration_sec") or 0.0)
        for stage, payload in metrics.items()
    }
    count = len(metrics)
    total_stage_duration = round(sum(totals.values()), 6)
    return {
        "stage_count": count,
        "total_stage_duration_sec": total_stage_duration,
        "average_stage_duration_sec": round(total_stage_duration / max(count, 1), 6),
        "longest_stage": max(totals.items(), key=lambda pair: pair[1])[0] if totals else None,
        "failed_stage_count": sum(
            1
            for payload in metrics.values()
            if str((payload or {}).get("last", {}).get("outcome") or "") == "failed"
        ),
        "warning_stage_count": sum(
            1
            for payload in metrics.values()
            if str((payload or {}).get("last", {}).get("outcome") or "") == "warning"
        ),
    }


@contextmanager
def observe_stage(
    stage_metrics: dict[str, dict[str, Any]],
    stage_name: str,
    *,
    logger: logging.Logger | None = None,
    log_message: str | None = None,
    log_context: dict[str, Any] | None = None,
) -> Iterator[StageObservation]:
    started_at = datetime.now(UTC)
    started_perf = perf_counter()
    observation: StageObservation = StageObservation()
    if logger is not None:
        logger.info(
            log_message or f"{stage_name}_started",
            extra={
                "stage": stage_name,
                "stage_status": "running",
                "event_type": "stage_started",
                **dict(log_context or {}),
            },
        )
    try:
        yield observation
    except Exception as exc:
        observation.setdefault("error_code", getattr(exc, "error_code", exc.__class__.__name__))
        observation["outcome"] = "failed"
        finished_at = datetime.now(UTC)
        duration_sec = max(0.0, perf_counter() - started_perf)
        record_stage_metric(
            stage_metrics,
            stage_name,
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            duration_sec=duration_sec,
            extra=dict(observation),
        )
        if logger is not None:
            logger.exception(
                log_message or f"{stage_name}_failed",
                extra={
                    "stage": stage_name,
                    "stage_status": "failed",
                    "error_code": observation.get("error_code"),
                    "duration_ms": round(duration_sec * 1000.0, 3),
                    "outcome": "failed",
                    "event_type": "stage_finished",
                    **dict(log_context or {}),
                },
            )
        raise
    else:
        observation.setdefault("outcome", "completed")
        finished_at = datetime.now(UTC)
        duration_sec = max(0.0, perf_counter() - started_perf)
        record_stage_metric(
            stage_metrics,
            stage_name,
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            duration_sec=duration_sec,
            extra=dict(observation),
        )
        if logger is not None:
            logger.info(
                log_message or f"{stage_name}_completed",
                extra={
                    "stage": stage_name,
                    "stage_status": observation.get("outcome", "completed"),
                    "duration_ms": round(duration_sec * 1000.0, 3),
                    "outcome": observation.get("outcome", "completed"),
                    "event_type": "stage_finished",
                    **dict(log_context or {}),
                },
            )
