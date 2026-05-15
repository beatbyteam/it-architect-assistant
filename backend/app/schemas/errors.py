from __future__ import annotations

from pydantic import BaseModel, Field


class ApiErrorResponse(BaseModel):
    code: str = Field(..., examples=["ACCESS_DENIED"])
    user_message: str
    technical_message: str | None = None
    operation_id: str | None = None
    request_id: str | None = None
    details: dict[str, object] = Field(default_factory=dict)

    # backwards-compatible fields
    error_code: str | None = None
    message: str | None = None
    recoverable: bool | None = None
