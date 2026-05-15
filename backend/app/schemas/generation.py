from __future__ import annotations

from pydantic import BaseModel, Field


class BusinessTaskCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    task_text: str = Field(min_length=20)
    metadata: dict | None = None


class InternalGenerationRunStartRequest(BaseModel):
    business_task_id: str
    correlation_id: str | None = Field(default=None, max_length=100)
    idempotency_key: str | None = Field(default=None, max_length=100)
    execute_inline: bool | None = None
