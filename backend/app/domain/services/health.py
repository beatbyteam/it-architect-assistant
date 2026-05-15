from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.repositories.knowledge import KnowledgeVersionRepository
from app.domain.services.knowledge_bases import KnowledgeBaseService
from app.integrations.generation.llm_gateway import LLMGateway
from app.integrations.knowledge.embedding import EmbeddingService
from app.schemas.health import (
    DependenciesResponse,
    DependencyHealthResponse,
    LiveResponse,
    ReadyResponse,
)


def _string_detail(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


class HealthService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.knowledge_versions = KnowledgeVersionRepository(session)

    def live(self) -> LiveResponse:
        return LiveResponse(
            status="ok",
            app_name=self.settings.app_name,
            version=self.settings.app_version,
        )

    def dependencies(self) -> DependenciesResponse:
        dependencies = self._collect_dependencies()
        overall = all(item.healthy or not item.blocking for item in dependencies)
        return DependenciesResponse(
            status="ok" if overall else "degraded", dependencies=dependencies
        )

    def ready(self) -> ReadyResponse:
        payload = self.dependencies()
        return ReadyResponse(status=payload.status, dependencies=payload.dependencies)

    def _collect_dependencies(self) -> list[DependencyHealthResponse]:
        dependencies: list[DependencyHealthResponse] = []
        if self.settings.health_check_db:
            dependencies.append(self._probe_db())
        if self.settings.health_check_redis:
            dependencies.append(self._probe_redis())
        if self.settings.health_check_worker:
            dependencies.append(self._probe_worker())
        if self.settings.health_check_embedding:
            dependencies.append(self._probe_embedding())
        if self.settings.health_check_llm:
            dependencies.append(self._probe_llm())
        if self.settings.health_check_active_knowledge_version:
            dependencies.append(self._probe_active_knowledge_version())
        return dependencies

    def _probe_db(self) -> DependencyHealthResponse:
        try:
            self.session.execute(text("SELECT 1"))
            return DependencyHealthResponse(
                name="postgres", healthy=True, status="healthy", category="database"
            )
        except Exception as exc:  # pragma: no cover - defensive path
            return DependencyHealthResponse(
                name="postgres",
                healthy=False,
                status="unhealthy",
                category="database",
                details=str(exc),
                diagnostics={"exception": type(exc).__name__},
            )

    def _probe_redis(self) -> DependencyHealthResponse:
        try:
            from app.tasks.workers.celery_app import redis_client

            redis_client.ping()
            return DependencyHealthResponse(
                name="redis", healthy=True, status="healthy", category="broker"
            )
        except Exception as exc:  # pragma: no cover - defensive path
            return DependencyHealthResponse(
                name="redis",
                healthy=False,
                status="unhealthy",
                category="broker",
                details=str(exc),
                diagnostics={"exception": type(exc).__name__},
            )

    def _probe_worker(self) -> DependencyHealthResponse:
        try:
            from app.tasks.workers.celery_app import celery_app

            reply = celery_app.control.inspect(timeout=1.0).ping() or {}
            if not reply:
                return DependencyHealthResponse(
                    name="celery-worker",
                    healthy=False,
                    status="unhealthy",
                    category="worker",
                    details="No ping response",
                )
            return DependencyHealthResponse(
                name="celery-worker",
                healthy=True,
                status="healthy",
                category="worker",
                diagnostics={"workers": sorted(reply.keys())},
            )
        except Exception as exc:  # pragma: no cover - defensive path
            return DependencyHealthResponse(
                name="celery-worker",
                healthy=False,
                status="unhealthy",
                category="worker",
                details=str(exc),
                diagnostics={"exception": type(exc).__name__},
            )

    def _probe_embedding(self) -> DependencyHealthResponse:
        try:
            service = EmbeddingService(
                profile_code=self.settings.embedding_profile,
                provider_name=self.settings.embedding_provider,
                dimensions=self.settings.embedding_dimensions,
                base_url=self.settings.embedding_base_url,
                api_key=self.settings.embedding_api_key,
                timeout_sec=self.settings.embedding_timeout_sec,
                model_id=self.settings.embedding_model_id,
                batch_size=self.settings.embedding_batch_size,
            )
            probe = service.healthcheck()
            return DependencyHealthResponse(
                name="embedding-provider",
                healthy=bool(probe.get("healthy")),
                status="healthy" if probe.get("healthy") else "unhealthy",
                category="embedding",
                blocking=True,
                details=_string_detail(probe.get("details")),
                diagnostics=probe,
            )
        except Exception as exc:  # pragma: no cover - defensive path
            return DependencyHealthResponse(
                name="embedding-provider",
                healthy=False,
                status="unhealthy",
                category="embedding",
                details=str(exc),
                diagnostics={"exception": type(exc).__name__},
            )

    def _probe_llm(self) -> DependencyHealthResponse:
        try:
            gateway = LLMGateway(
                provider=self.settings.llm_provider,
                base_url=self.settings.llm_base_url,
                api_key=self.settings.llm_api_key,
                timeout_sec=self.settings.llm_timeout_sec,
                model_id=self.settings.llm_model_id,
                fallback_provider=self.settings.llm_fallback_provider,
                fallback_base_url=self.settings.llm_fallback_base_url,
                fallback_api_key=self.settings.llm_fallback_api_key,
                fallback_model_id=self.settings.llm_fallback_model_id,
            )
            probe = gateway.healthcheck()
            return DependencyHealthResponse(
                name="llm-provider",
                healthy=bool(probe.get("healthy")),
                status="healthy" if probe.get("healthy") else "unhealthy",
                category="llm",
                blocking=True,
                details=_string_detail(probe.get("details")),
                diagnostics=probe,
            )
        except Exception as exc:  # pragma: no cover - defensive path
            return DependencyHealthResponse(
                name="llm-provider",
                healthy=False,
                status="unhealthy",
                category="llm",
                details=str(exc),
                diagnostics={"exception": type(exc).__name__},
            )

    def _probe_active_knowledge_version(self) -> DependencyHealthResponse:
        try:
            scope = KnowledgeBaseService(self.session).get_existing_effective_scope()
            if scope is None:
                return DependencyHealthResponse(
                    name="active-knowledge-version",
                    healthy=False,
                    status="missing",
                    category="knowledge",
                    blocking=True,
                    details="Knowledge scope is not initialized",
                )
            if scope.mandatory_version is None and scope.selected_user_version is None:
                return DependencyHealthResponse(
                    name="active-knowledge-version",
                    healthy=False,
                    status="missing",
                    category="knowledge",
                    blocking=True,
                    details="No active knowledge scope available",
                )
            return DependencyHealthResponse(
                name="active-knowledge-version",
                healthy=True,
                status="healthy",
                category="knowledge",
                blocking=True,
                diagnostics={
                    "mandatory_version_id": str(scope.mandatory_version.knowledge_version_id)
                    if scope.mandatory_version
                    else None,
                    "selected_user_version_id": str(
                        scope.selected_user_version.knowledge_version_id
                    )
                    if scope.selected_user_version
                    else None,
                    "selected_user_base_id": str(scope.selected_user_base.knowledge_base_id),
                },
            )
        except Exception as exc:  # pragma: no cover - defensive path
            return DependencyHealthResponse(
                name="active-knowledge-version",
                healthy=False,
                status="unhealthy",
                category="knowledge",
                details=str(exc),
                diagnostics={"exception": type(exc).__name__},
            )
