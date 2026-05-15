from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DependencyHealthResponse(BaseModel):
    name: str
    healthy: bool
    status: str = "healthy"
    category: str | None = None
    blocking: bool = True
    details: str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class LiveResponse(BaseModel):
    status: str
    app_name: str
    version: str


class ReadyResponse(BaseModel):
    status: str
    dependencies: list[DependencyHealthResponse]


class DependenciesResponse(ReadyResponse):
    pass
