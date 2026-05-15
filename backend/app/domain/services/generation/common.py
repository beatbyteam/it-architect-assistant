from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

import numpy as np

from app.db.enums import (
    GenerationRunStatus,
)
from app.db.models.generation import (
    BusinessTask,
)
from app.integrations.generation import (
    RetrievedFragment,
)

logger = logging.getLogger(__name__)

TERMINAL_GENERATION_STATUSES = {
    GenerationRunStatus.COMPLETED,
    GenerationRunStatus.FAILED,
    GenerationRunStatus.CANCELED,
}


@dataclass(slots=True)
class RetrievalResult:
    fragments: list[RetrievedFragment]
    diagnostics: dict[str, Any]


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value

    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, datetime | date):
        return value.isoformat()

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, np.generic):
        return _json_safe(value.item())

    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]

    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}

    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_json_safe(item) for item in value]

    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())

    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass

    return str(value)


def _task_metadata(task: BusinessTask) -> dict[str, Any]:
    return dict(task.task_metadata or {}) if isinstance(task.task_metadata, dict) else {}


def _clarification_context_lines(task: BusinessTask) -> list[str]:
    metadata = _task_metadata(task)
    answers = metadata.get("clarification_answers") or {}
    if not isinstance(answers, dict):
        return []
    return [f"{key}: {value}" for key, value in answers.items() if value]


def _context_notes(task: BusinessTask) -> list[str]:
    metadata = _task_metadata(task)
    raw_value = metadata.get("context_notes")
    if raw_value is None:
        raw_value = metadata.get("context")
    if isinstance(raw_value, str):
        note = raw_value.strip()
        return [note] if note else []
    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    return []


def _prompt_context_items(task: BusinessTask) -> list[str]:
    return [*_context_notes(task), *_clarification_context_lines(task)]
