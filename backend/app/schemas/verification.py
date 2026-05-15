from __future__ import annotations

from pydantic import BaseModel, Field


class InternalVerificationRunStartRequest(BaseModel):
    solution_version_id: str
    validation_scope: str = Field(default="full")
    knowledge_document_ids: list[str] = Field(default_factory=list)
    correlation_id: str | None = Field(default=None, max_length=100)
    idempotency_key: str | None = Field(default=None, max_length=100)
