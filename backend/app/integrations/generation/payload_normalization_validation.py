from __future__ import annotations

from typing import Any

from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import ValidationError
from app.integrations.generation.contracts import GenerationSolutionPayload

from .payload_normalization_top_level import _normalize_generation_payload_shape


def _coerce_generation_solution_payload(payload: dict[str, Any]) -> GenerationSolutionPayload:
    normalized_payload = _normalize_generation_payload_shape(payload)
    return GenerationSolutionPayload.model_validate(normalized_payload)


def _validate_generation_solution_payload(payload: dict[str, Any]) -> GenerationSolutionPayload:
    try:
        return _coerce_generation_solution_payload(payload)
    except PydanticValidationError as exc:
        raise ValidationError(
            f"LLM output does not match generation schema: {exc}",
            error_code="LLM_OUTPUT_SCHEMA_INVALID",
        ) from exc
