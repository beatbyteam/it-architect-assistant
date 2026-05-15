from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from logging.config import dictConfig

from app.core.config import Settings
from app.core.request_context import get_log_context


class JsonFormatter(logging.Formatter):
    CONTEXT_FIELDS = (
        "request_id",
        "correlation_id",
        "operation_kind",
        "operation_id",
        "business_task_id",
        "generation_run_id",
        "verification_run_id",
        "knowledge_update_run_id",
        "knowledge_version_id",
        "solution_version_id",
        "verification_protocol_id",
    )
    RECORD_FIELDS = (
        "entity_id",
        "run_id",
        "stage",
        "stage_status",
        "error_code",
        "metric_name",
        "duration_ms",
        "outcome",
        "event_type",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(get_log_context())
        for key in self.CONTEXT_FIELDS:
            if key not in payload:
                value = getattr(record, key, None)
                if value is not None:
                    payload[key] = value
        for key in self.RECORD_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_configured = False


def configure_logging(settings: Settings) -> None:
    global _configured
    if _configured:
        logging.getLogger().setLevel(settings.log_level.upper())
        return

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"json": {"()": JsonFormatter}},
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                }
            },
            "root": {
                "level": settings.log_level.upper(),
                "handlers": ["default"],
            },
        }
    )
    _configured = True
