from __future__ import annotations

from typing import Any

__all__ = ["KnowledgeSourceService", "KnowledgeUpdateService", "KnowledgeVersionService"]


def __getattr__(name: str) -> Any:
    if name == "KnowledgeSourceService":
        from app.domain.services.knowledge.source_service import KnowledgeSourceService

        return KnowledgeSourceService
    if name == "KnowledgeUpdateService":
        from app.domain.services.knowledge.update_service import KnowledgeUpdateService

        return KnowledgeUpdateService
    if name == "KnowledgeVersionService":
        from app.domain.services.knowledge.version_service import KnowledgeVersionService

        return KnowledgeVersionService
    raise AttributeError(name)
